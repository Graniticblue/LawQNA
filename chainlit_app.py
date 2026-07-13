#!/usr/bin/env python3
"""
chainlit_app.py -- 건축법규 AI 자문 시스템 (Chainlit 인터페이스)
"""

import asyncio
import importlib.util
import json
import os
import queue as _queue
import random
import re
import sys
import threading
import uuid
from pathlib import Path

import chainlit as cl

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))


# ── 익명 인증 + 대화 영속성 (Chat History) ──────────────────────
# 로그인 화면 없이 브라우저별 익명 사용자로 식별해 사이드바에 대화 내역을 유지한다.
# custom.js가 발급한 anon_id 쿠키를 읽어 사용자로 매핑한다.

@cl.header_auth_callback
def header_auth(headers) -> cl.User | None:
    cookie = headers.get("cookie", "") or ""
    anon_id = None
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith("anon_id="):
            anon_id = part[len("anon_id="):]
            break
    # 쿠키 발급 전(첫 요청)이면 임시 ID — custom.js가 reload하면 안정 ID로 대체된다.
    if not anon_id:
        anon_id = "anon_" + uuid.uuid4().hex[:16]
    return cl.User(identifier=anon_id, metadata={"role": "anonymous"})


def _asyncpg_conninfo() -> str | None:
    """Railway가 주는 DATABASE_URL(postgres://…)을 asyncpg 드라이버 형식으로 변환.
    DATABASE_URL이 없으면(로컬 등) None → 영속성 비활성."""
    url = (os.environ.get("DATABASE_URL", "") or "").strip()
    if not url:
        return None
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


# ── 인용 팝업(element) 영속화 — 볼륨 기반 storage client ──────────
# SQLAlchemyDataLayer는 storage_provider 없이는 element를 저장하지 못해
# (create_element: "No blob_storage_client"), 재개된 대화에서 인용 팝업이 사라진다.
# S3 대신 Railway 영구 볼륨(chroma_db와 같은 볼륨)에 저장하는 파일시스템 client.
from chainlit.data.storage_clients.base import BaseStorageClient

# chroma_db 볼륨 내부에 둬 재배포에도 영속(볼륨 마운트 경로와 무관하게 보존).
# FORCE_REINDEX 시엔 함께 지워지지만(드묾) 오래된 대화 팝업만 잃는 정도로 수용.
_chroma_path = os.environ.get("CHROMA_DB_PATH", str(BASE_DIR / "data" / "chroma_db"))
ELEMENT_DIR = Path(os.environ.get(
    "ELEMENT_STORAGE_DIR", str(Path(_chroma_path) / "_element_storage")))


class VolumeStorageClient(BaseStorageClient):
    async def upload_file(self, object_key, data, mime="application/octet-stream", overwrite=True):
        p = ELEMENT_DIR / object_key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
        return {"url": f"/element-files/{object_key}", "object_key": object_key}

    async def get_read_url(self, object_key):
        return f"/element-files/{object_key}"

    async def delete_file(self, object_key):
        try:
            (ELEMENT_DIR / object_key).unlink()
            return True
        except Exception:
            return False


# element 파일을 서빙하는 라우트를 Chainlit FastAPI 앱에 등록 (프런트가 url로 fetch)
try:
    from chainlit.server import app as _cl_server_app
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    @_cl_server_app.get("/element-files/{object_key:path}")
    async def _serve_element_file(object_key: str):
        base = ELEMENT_DIR.resolve()
        p = (ELEMENT_DIR / object_key).resolve()
        if not str(p).startswith(str(base)) or not p.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(str(p), media_type="text/plain; charset=utf-8")

    # 내장 법령 목록 HTML (헤더 버튼 모달이 fetch)
    from fastapi import Request
    from fastapi.responses import HTMLResponse, JSONResponse

    @_cl_server_app.get("/law-list")
    async def _law_list_html():
        return HTMLResponse(build_law_db_html())

    # 업로드 캐시 조회/삭제 (헤더 버튼 모달 — anon_id 쿠키로 본인 것만)
    def _upload_col(key: str):
        import chromadb
        path = os.environ.get("CHROMA_DB_PATH", str(BASE_DIR / "data" / "chroma_db"))
        return chromadb.PersistentClient(path=path).get_collection(f"upload_{key[:16]}")

    @_cl_server_app.get("/upload-cache")
    async def _upload_cache_html(request: Request):
        import html as _h
        key = request.cookies.get("anon_id", "")
        agg: dict = {}
        if key:
            try:
                metas = _upload_col(key).get(include=["metadatas"], limit=10000)["metadatas"]
                for m in metas:
                    ln = m.get("law_name", "업로드 법령")
                    e = agg.setdefault(ln, {"chunks": 0, "ord": False, "scoped": False})
                    e["chunks"] += 1
                    if m.get("is_ordinance") == "true":
                        e["ord"] = True
                        if m.get("thread_id", ""):   # thread_id 있으면 특정 대화 한정
                            e["scoped"] = True
            except Exception:
                pass
        parts = ['<div class="law-db">', "<h2>📂 조례 라이브러리</h2>"]
        if not agg:
            parts.append("<p>업로드된 자료가 없습니다. PDF를 첨부하면 여기에 저장됩니다.</p>")
        else:
            parts.append("<table><thead><tr><th>자료</th><th>청크</th><th></th></tr></thead><tbody>")
            for ln in sorted(agg):
                e = agg[ln]
                if e["ord"]:
                    tag = " · 조례(이 대화 한정)" if e["scoped"] else " · 조례(모든 대화)"
                else:
                    tag = ""
                law_attr = _h.escape(ln, quote=True)
                btns = ""
                if e["scoped"]:   # 대화 한정 조례만 '전역 재캐싱' 노출
                    btns += f'<button class="law-list-recache" data-law="{law_attr}">전역 재캐싱</button> '
                btns += f'<button class="law-list-replace" data-law="{law_attr}">교체</button> '
                btns += f'<button class="law-list-del" data-law="{law_attr}">삭제</button>'
                parts.append(
                    f"<tr><td>{_h.escape(ln)}{_h.escape(tag)}</td><td>{e['chunks']}</td>"
                    f"<td>{btns}</td></tr>")
            parts.append("</tbody></table>")
            parts.append('<p class="law-db-foot">지역조례와 별표를 직접 라이브러리에 등록시 답변 성능이 개선됩니다.</p>')
        parts.append("</div>")
        return HTMLResponse("\n".join(parts))

    @_cl_server_app.post("/upload-cache/delete")
    async def _upload_cache_delete(request: Request):
        key = request.cookies.get("anon_id", "")
        try:
            body = await request.json()
        except Exception:
            body = {}
        law = (body or {}).get("law_name", "")
        n = 0
        if key and law:
            try:
                col = _upload_col(key)
                ids = col.get(where={"law_name": {"$eq": law}}, include=[], limit=10000)["ids"]
                if ids:
                    col.delete(ids=ids)
                n = len(ids)
            except Exception:
                pass
        return JSONResponse({"deleted": n})

    @_cl_server_app.post("/upload-cache/recache")
    async def _upload_cache_recache(request: Request):
        # 전역 재캐싱: 그 법령 청크의 thread_id 메타만 ""로 바꿔 모든 대화에서
        # 검색되게 한다(재파싱·재임베딩 없이 메타만 update). 조례의 '이 대화 한정'
        # 격리를 파일 재선택 없이 해제하는 용도.
        key = request.cookies.get("anon_id", "")
        try:
            body = await request.json()
        except Exception:
            body = {}
        law = (body or {}).get("law_name", "")
        n = 0
        if key and law:
            try:
                col = _upload_col(key)
                got = col.get(where={"law_name": {"$eq": law}},
                              include=["metadatas"], limit=10000)
                ids, metas = got["ids"], got["metadatas"]
                if ids:
                    for m in metas:
                        m["thread_id"] = ""   # 전역화
                    col.update(ids=ids, metadatas=metas)
                    n = len(ids)
            except Exception:
                pass
        return JSONResponse({"recached": n})

    @_cl_server_app.post("/upload-cache/add")
    async def _upload_cache_add(request: Request):
        # 채팅과 무관하게 PDF를 업로드 캐시에 등록 (질문 입력 불필요).
        # anon_id로 채팅과 동일한 컬렉션(upload_{key[:16]})에 저장하고, thread_id=""
        # 로 두어 조례라도 특정 대화에 묶이지 않고 모든 대화에서 검색되게 한다.
        import asyncio as _asyncio
        import tempfile
        key = request.cookies.get("anon_id", "")
        if not key:
            return JSONResponse({"error": "세션이 없습니다 — 페이지를 새로고침하세요"}, status_code=400)
        try:
            form = await request.form()
        except Exception:
            return JSONResponse({"error": "폼 파싱 실패"}, status_code=400)
        upload = form.get("file")
        filename = getattr(upload, "filename", "") or ""
        if not filename:
            return JSONResponse({"error": "파일이 없습니다"}, status_code=400)
        if not filename.lower().endswith(".pdf"):
            return JSONResponse({"error": "PDF 파일만 등록할 수 있습니다"}, status_code=400)
        data = await upload.read()
        if not data:
            return JSONResponse({"error": "빈 파일입니다"}, status_code=400)

        def _do_upload():
            fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                law_label = filename.rsplit(".", 1)[0]
                text = parse_pdf(tmp_path)
                chunks = chunk_law_pdf(text, law_label)
                gen = get_generator()
                retriever = gen._get_retriever()
                retriever.create_session_collection(key)   # _session_cols에 등록(채팅과 공유)
                n = retriever.index_uploaded_chunks(key, chunks, "")  # thread_id="" → 전역
                return law_label, n
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        try:
            law_label, n = await _asyncio.to_thread(_do_upload)
        except Exception as e:
            return JSONResponse({"error": f"처리 실패: {e}"}, status_code=500)
        if n == 0:
            return JSONResponse({"error": "인덱싱된 내용이 없습니다 (텍스트 추출 실패 PDF?)"}, status_code=400)
        return JSONResponse({"law_name": law_label, "chunks": n})

    # Chainlit SPA catch-all(/{full_path:path} → index.html)보다 먼저 매칭되도록
    # 커스텀 라우트들을 라우터 맨 앞으로 재배열.
    _MY_PATHS = {"/element-files/{object_key:path}", "/law-list", "/upload-cache",
                 "/upload-cache/delete", "/upload-cache/add", "/upload-cache/recache"}
    _front = [r for r in _cl_server_app.router.routes if getattr(r, "path", "") in _MY_PATHS]
    _rest  = [r for r in _cl_server_app.router.routes if getattr(r, "path", "") not in _MY_PATHS]
    _cl_server_app.router.routes[:] = _front + _rest
    print("[element-storage] /element-files·/law-list·/upload-cache 라우트 등록(우선순위 최상단)")
except Exception as _e:
    print(f"[element-storage] 서빙 라우트 등록 실패: {_e}")


@cl.data_layer
def get_data_layer():
    conninfo = _asyncpg_conninfo()
    if not conninfo:
        return None  # DATABASE_URL 미설정 시 영속성 없이 동작
    from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
    return SQLAlchemyDataLayer(conninfo=conninfo, storage_provider=VolumeStorageClient())


# ── Generator 싱글턴 ────────────────────────────────────────

_generator_instance = None


def get_generator():
    global _generator_instance
    if _generator_instance is None:
        spec = importlib.util.spec_from_file_location(
            "generator_mod", BASE_DIR / "pipeline" / "06_Generator.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _generator_instance = mod.Generator()
    return _generator_instance


# ── PDF 파싱 ────────────────────────────────────────────────

def parse_pdf(path: str) -> str:
    try:
        import fitz
        doc = fitz.open(path)
        pages = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(pages)
    except Exception:
        pass
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception:
        return ""


# ── PDF 청킹 ────────────────────────────────────────────────

# 항(項) 분할 — 02_Indexer_BASE.split_article_into_hangs와 동일 로직.
# 다항 조문이 하나의 청크로 임베딩되면 max_seq_length(128토큰)에 뒷항이 잘려
# 검색되지 않으므로(예: 제55조의2 제3항 돌봄센터 단서), 항 단위로 쪼갠다.
_HANG_MARKERS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚"


def _split_hangs(content: str):
    positions = [(m.start(), m.group()) for m in re.finditer(f"[{_HANG_MARKERS}]", content)]
    if len(positions) < 2:
        return None
    return [
        (marker, content[pos:(positions[i + 1][0] if i + 1 < len(positions) else len(content))].strip())
        for i, (pos, marker) in enumerate(positions)
    ]


def chunk_law_pdf(text: str, law_name: str) -> list[dict]:
    # 국가법령정보센터 PDF 정제 (법령 DB 파서와 동일 룰):
    #  ① 페이지 헤더/푸터 제거  ② 부칙 이전 본문만  ③ 조문번호 단조증가(인용 오인 방지)
    text = re.sub(r"법제처\s+\d+\s+국가법령정보센터\s*\n?", "\n", text)
    bu = re.search(r"\n부\s*칙\s*[<\[]", text)
    body = text[:bu.start()] if bu else text

    # 조문 시작은 항상 '제N조(제목)' 형태 — 제목 괄호 필수로 잡아야
    # 본문 중 인용('제52조에 따라', '제52조제1항')을 조문 시작으로 오인하지 않는다.
    cand = list(re.finditer(r"제(\d+)조(?:의(\d+))?\([^)\n]{1,40}\)", body))
    matches, last = [], (0, 0)
    for m in cand:
        key = (int(m.group(1)), int(m.group(2) or 0))
        if key > last:        # 번호가 역행하면 본문 중 인용(예: '제11조(허가)에 따라')
            matches.append(m)
            last = key

    chunks = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        article_no = f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")
        part = body[start:end].strip()
        if len(part) < 15:
            continue
        # 다항 조문은 항 단위로 분할 (법령 DB와 동일 룰). 단항/짧은 조문은 통째로.
        hangs = _split_hangs(part)
        if hangs:
            # 항 청크 본문에 조 헤더('제3조(적용의 완화)')를 프리픽스 — 항 텍스트만으로는
            # 임베딩이 무슨 조(제목·주제)의 항인지 몰라 제목 키워드 검색에서 누락된다.
            m_h = re.match(r'\s*(제\d+조(?:의\d+)?\([^)\n]{1,40}\))', part)
            header = m_h.group(1) if m_h else article_no
            for marker, htext in hangs:
                if len(htext) <= 3:     # 마커만 있는 빈 항 제외
                    continue
                chunks.append({
                    "law_name": law_name,
                    "article_no": f"{article_no} {marker}",
                    "content": f"[{header}] {htext}"[:6000],
                })
        else:
            chunks.append({
                "law_name": law_name,
                "article_no": article_no,
                "content": part[:6000],
            })
    # 조문 패턴이 없는 비법령 PDF는 길이 기반 분할 (fallback)
    if not chunks:
        for i in range(0, len(text), 500):
            chunks.append({
                "law_name": law_name,
                "article_no": f"p{i // 500 + 1}",
                "content": text[i:i + 500],
            })
    return chunks


# ── 날짜 포맷 ────────────────────────────────────────────────

def fmt_date(d: str) -> str:
    if d and len(d) == 8 and d.isdigit():
        return f"{d[:4]}.{d[4:6]}.{d[6:]}"
    return d


# ── 개정이력 조회 (공포번호·공포일) ──────────────────────────

_amendment_lookup: dict = {}

# amendments.jsonl 축약키 → all_articles 전체명(공백제거) 매핑
_AMEND_KEY_MAP = {
    "건축법":           "건축법",
    "건축법시행령":      "건축법시행령",
    "건축법시행규칙":    "건축법시행규칙",
    "국토계획법":        "국토의계획및이용에관한법률",
    "국토계획법시행령":  "국토의계획및이용에관한법률시행령",
    "국토계획법시행규칙":"국토의계획및이용에관한법률시행규칙",
    "주택법":           "주택법",
    "주택법시행령":      "주택법시행령",
    "주택법시행규칙":    "주택법시행규칙",
}


def get_amendment_lookup() -> dict:
    global _amendment_lookup
    if _amendment_lookup:
        return _amendment_lookup
    path = BASE_DIR / "data/law_amendments/amendments.jsonl"
    if not path.exists():
        return {}
    lookup: dict = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        aid = rec.get("amendment_id", "")
        m = re.match(r'^([^_]+)_(\d{8})_(.+)$', aid)
        if not m:
            continue
        amend_key = m.group(1)           # "국토계획법시행령"
        enf_date  = m.group(2)           # "20250701"
        law_no    = m.group(3)           # "35378호"
        pub_date  = rec.get("공포일", "").replace("-", ".")
        pub_digits = pub_date.replace(".", "")  # "20250415"

        # 전체명 키 (all_articles와 동일 형태)
        full_key = _AMEND_KEY_MAP.get(amend_key, amend_key)

        # 시행일 기준 키
        lookup[(full_key, enf_date)] = (law_no, pub_date)
        # 공포일도 fallback 키로 등록 (enforcement_date가 공포일인 경우 대비)
        if pub_digits and pub_digits != enf_date:
            lookup.setdefault((full_key, pub_digits), (law_no, pub_date))
        # 원래 abbreviated 키도 유지 (건축법 등 동일한 경우)
        if full_key != amend_key:
            lookup[(amend_key, enf_date)] = (law_no, pub_date)

    _amendment_lookup = lookup
    return lookup


def get_law_header(law_name: str, enforcement_date: str) -> str:
    """law.go.kr 형식: [시행 2026.02.27.] [법률 제21035호, 2025.08.26., 일부개정]"""
    lookup = get_amendment_lookup()
    # 공백 제거한 전체 법령명으로 조회 (amendments 전체명 키)
    law_key = re.sub(r'[\s·ㆍ]+', '', law_name)
    law_key = law_key.replace('ㆍ', '').replace('·', '')
    info = lookup.get((law_key, enforcement_date))
    edate_str = fmt_date(enforcement_date)
    if not edate_str:
        return ""
    if info:
        law_no, pub_date = info
        return f"[시행 {edate_str}.] [제{law_no}, {pub_date}., 일부개정]"
    return f"[시행 {edate_str}.]"


# ── content 중복 번호 제거 ────────────────────────────────────

def _clean_precedent_body(raw: str) -> str:
    """해석례/판례 팝업 본문 정리: 인제스트 때 붙인 내부 섹션과 프린트 잔재 제거.
    - 서울시 질의회신형(enrich 문서): [최종 답변] 이후가 회신 원문 — 그것만 표시.
      (앞부분 [질문 원인 분석]/[법리적 판단 로직]/[검토 결과]는 내부 분석문이라
      팝업에 노출하면 원문처럼 오인됨)
    - 법제처형: [답변] 이후만 남김(앞의 [태그]/[요약]/[질문]/[참조] 프리앰블 제거)
    - 위치 무관 내부 마커([태그]/[요약]/[검색 태그]/[참조]/[질문]) 제거
    - moleg 프린트 URL·페이지번호·타임스탬프, 서울시 자료집 인쇄 잔재(.indd) 제거
    """
    mk = re.search(r"\[\s*최종\s*답변\s*\]", raw)
    if mk:
        body = raw[mk.end():]
        if len(body.strip()) < 20:   # 원문 추출 실패 방어 — 전체로 폴백
            body = raw
    else:
        mk = re.search(r"\[\s*답변\s*\]", raw)
        body = raw[mk.end():] if mk else raw
    body = re.sub(r"\[\s*(?:검색\s*태그|태그|요약|참조|질문|질의배경)\s*\][^\n]*", "", body)
    body = re.sub(r"https?://[^\s]*moleg\.go\.kr[^\s]*", "", body)
    # 서울시 자료집 인쇄 잔재: "40조-끝.indd 569 2015. 2. 10. 오후 3:27"
    # (페이지 넘김 지점에 단어 중간 삽입됨 → 앞뒤 공백째 제거해 단어를 다시 잇는다)
    body = re.sub(
        r"\s*\S+\.indd\s*\d*\s*(?:20\d{2}\.\s*\d{1,2}\.\s*\d{1,2}\.?\s*)?"
        r"(?:오[전후]\s*\d{1,2}:\d{2})?\s*", "", body)
    # "1 / 4", "4 / 42026-05-28 오후 3:26" 류 페이지·인쇄시각 잔재
    body = re.sub(r"\d+\s*/\s*\d+\s*(?:20\d{2}-\d{1,2}-\d{1,2}\s*오[전후]\s*\d{1,2}:\d{2})?", "", body)
    body = re.sub(r"20\d{2}-\d{1,2}-\d{1,2}\s*오[전후]\s*\d{1,2}:\d{2}", "", body)
    return body.strip()


def clean_article_content(text: str) -> str:
    """① ①, 1. 1., 가. 가. 중복 제거 + PDF 하드랩 개행 정리 + 항 마커 문단 분리"""
    # (join 전) 끝에 딸린 '제N장/절/관 제목' 줄 제거 — 개행으로 겹쳐진 것들 반복 제거.
    _chap_raw = re.compile(r'\n[ \t]*제\d+[장절관][ \t]+[^\n]{0,80}(?:\n[ \t]*<[^>]*>)?[ \t]*$')
    for _ in range(4):
        s = _chap_raw.sub('', text)
        if s == text:
            break
        text = s
    # 개정/신설 태그 내부의 하드랩 개행을 먼저 이어붙임 — '<개정 2009. 7.\n16., …>'
    # 처럼 날짜가 줄로 갈라지면 다음 줄 시작('16.,')이 아래 _STRUCT의 호 마커
    # (\d{1,2}\.)로 오인돼 줄바꿈이 보존되는 문제 방지.
    text = re.sub(r'<[^>]*>', lambda m: re.sub(r'\s*\n\s*', ' ', m.group(0)), text)
    text = re.sub(r'([①-⑳])\s+\1', r'\1', text)
    # 호 번호 중복(1. 1.) 제거 — 앞이 숫자·점이면 제외: '2013. 3. 23.'의 연도 꼬리
    # '3.'과 월 '3.'을 중복으로 오판해 월을 지우던 버그(→ '2013. 23.') 방지.
    text = re.sub(r'(?<![\d.])(\d+\.)\s+\1\s*', r'\1 ', text)
    text = re.sub(r'([가-힣]\.)\s+\1\s*', r'\1 ', text)
    # PDF 하드랩 개행(단어 중간 '높이\n는', '채광\n(採光)') 제거.
    # 개행 뒤가 구조 마커(항①/호1./목가./[/제N조/<개정/마크다운헤더#)면 진짜 줄바꿈 → 보존.
    _STRUCT = r'(?=[ \t]*(?:[①-⑳]|\d{1,2}\.|[가-힣]\.|\[|제\d+조|<|#))'
    text = re.sub(r'\n' + _STRUCT, '\x00', text)   # 구조 개행 보호
    text = text.replace('\n', '')                   # 하드랩 개행 이어붙임
    text = text.replace('\x00', '\n')               # 구조 개행 복원
    # 항①·[전문개정]·마크다운헤더(#) 앞은 문단 분리(\n\n) — 단일 개행은 마크다운서 공백
    text = re.sub(r'\n+[ \t]*(?=[①-⑳]|\[|#)', '\n\n', text)
    # 파싱 시 다음 조 앞에 딸려온 '제N장/절/관 제목'을 끝에서 제거 (하드랩 join 후 한 줄이 된 상태).
    # 제목은 개행/2칸+공백으로 앞 내용과 분리됨 → 인라인 '제7장 …'(단일 공백)은 제외.
    # 개정태그(<개정 …>)가 같은 줄이나 다음 줄에 붙어도 함께 제거. 절 제목이 겹치면 반복 제거.
    _chap = re.compile(r'(?:\n[ \t]*|[ \t]{2,})제\d+[장절관]\s+[^\n]{1,80}?(?:\s*<[^>]*>)?\s*$')
    for _ in range(4):
        stripped = _chap.sub('', text)
        if stripped == text:
            break
        text = stripped
    return text


# ── 인라인 인용 마커 파싱 ───────────────────────────────────

def _format_amendment_content(rec: dict) -> str:
    """amendment dict → 사이드패널 마크다운 문자열"""
    law  = rec.get("law_name", "")
    date = rec.get("시행일", "")
    pub  = rec.get("공포번호", "")
    lines = [f"**{law}** [{pub}, {date}.]", ""]

    이유 = rec.get("개정이유", "")
    if 이유:
        lines += [f"**개정이유**", 이유, ""]

    주요 = rec.get("주요내용", "")
    if 주요:
        lines.append("**주요 개정 내용**")
        if isinstance(주요, str):
            lines.append(주요)
        else:
            for item in 주요:
                조문 = ", ".join(item.get("조문", []))
                lines.append(f"· [{조문}] {item.get('항목','')}: {item.get('내용','')}")
        lines.append("")

    kp = rec.get("목적론적_키포인트", "")
    if kp:
        lines.append("**목적론적 키포인트**")
        if isinstance(kp, list):
            for k in kp:
                lines.append(f"· {k}")
        else:
            lines.append(kp)
        lines.append("")

    부칙 = rec.get("부칙_상세", [])
    if 부칙:
        lines.append("**부칙(적용례·경과조치)**")
        if isinstance(부칙, dict):
            for k, v in 부칙.items():
                v_str = v if isinstance(v, str) else str(v)
                lines.append(f"· {k}: {v_str[:200]}")
        else:
            for b in 부칙:
                if isinstance(b, dict):
                    lines.append(f"· {b.get('조항','')}: {b.get('내용','')}")
                else:
                    lines.append(f"· {b}")

    return "\n".join(lines)


def _strip_internal_markers(text: str) -> str:
    """답변에 잘못 남은 내부 마커들을 제거.

    - [법령원문N], [법령N], [해석례N], [판례N], [입법요지N], [memo_NNN], [P-NNN]
    - [해석례2, 해석례3 참조], [P-004 참조] 같은 결합 형태
    - 뒤에 따라붙는 공백·구두점도 정리
    """
    # 모든 변종을 한 번에 잡는 패턴 (대괄호 안에 마커류 토큰만 포함된 경우)
    inner = r'(?:법령원문|법령|해석례|판례|입법요지|memo_\d+|P-\d+|직접)'
    pattern = re.compile(
        rf'\s*\[\s*{inner}\s*[\d\s,·、]*(?:참조|참고)?\s*\]'
    )
    text = pattern.sub('', text)
    # 낫표(「」) 변종도 제거 — 단, 「건축법」 등 실제 법령명은 보존해야 하므로
    # '법령원문N/법령N/해석례N/판례N/입법요지N'(숫자 필수)·memo_·P- 만 대상.
    # 결합형(「해석례2, 해석례3 참조」)도 반복 허용으로 처리.
    _tok = r'(?:(?:법령원문|법령|해석례|판례|입법요지)\s*\d+|memo_\d+|P-\d+)'
    corner = re.compile(rf'\s*「\s*{_tok}(?:\s*[,·、]\s*{_tok})*\s*(?:참조|참고)?\s*」')
    text = corner.sub('', text)
    # 빈 괄호류 제거
    text = re.sub(r'\(\s*\)', '', text)
    # 중복 공백 정리
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text


# 법령명 alias — DB 정식명 → 답변에 등장 가능한 모든 표기 형태 (정식 + 축약)
# 모델이 "국토계획법 시행령" 등 축약형을 써도 사이드 패널과 연결되도록 필요.
LAW_ALIASES: dict[str, list[str]] = {
    "건축법":                              ["건축법"],
    "건축법 시행령":                        ["건축법 시행령", "건축법시행령"],
    "건축법 시행규칙":                      ["건축법 시행규칙", "건축법시행규칙"],
    "국토의 계획 및 이용에 관한 법률":       ["국토의 계획 및 이용에 관한 법률", "국토계획법"],
    "국토의 계획 및 이용에 관한 법률 시행령": [
        "국토의 계획 및 이용에 관한 법률 시행령",
        "국토계획법 시행령",
        "국토계획법시행령",
    ],
    "국토의 계획 및 이용에 관한 법률 시행규칙": [
        "국토의 계획 및 이용에 관한 법률 시행규칙",
        "국토계획법 시행규칙",
        "국토계획법시행규칙",
    ],
    "주택법":                              ["주택법"],
    "주택법 시행령":                        ["주택법 시행령", "주택법시행령"],
    "주택법 시행규칙":                      ["주택법 시행규칙", "주택법시행규칙"],
    "도시 및 주거환경정비법":               ["도시 및 주거환경정비법", "도시정비법"],
    "도시 및 주거환경정비법 시행령":         ["도시 및 주거환경정비법 시행령", "도시정비법 시행령"],
    "장애인·노인·임산부 등의 편의증진 보장에 관한 법률": [
        "장애인·노인·임산부 등의 편의증진 보장에 관한 법률",
        "장애인편의법",
    ],
    "다중이용업소의 안전관리에 관한 특별법":  [
        "다중이용업소의 안전관리에 관한 특별법",
        "다중이용업법",
    ],
    "소방시설 설치 및 관리에 관한 법률":     ["소방시설 설치 및 관리에 관한 법률", "소방시설법"],
    "소방시설 설치 및 관리에 관한 법률 시행령": [
        "소방시설 설치 및 관리에 관한 법률 시행령",
        "소방시설법 시행령",
    ],
    "주차장법":                            ["주차장법"],
    "주차장법 시행령":                      ["주차장법 시행령", "주차장법시행령"],
    "주차장법 시행규칙":                    ["주차장법 시행규칙", "주차장법시행규칙"],
    "농지법":                              ["농지법"],
}


def _get_law_aliases(law: str) -> list[str]:
    """DB 정식 법령명에 대응하는 모든 인용 표기 형태(정식+축약) 반환.
    매핑에 없는 법령은 원본 이름만 사용."""
    return LAW_ALIASES.get(law, [law])


# 자연 산문 인용 패턴 — 전체 인용 문자열을 통째로 캡처하여 element 이름으로 사용
# Chainlit auto-link은 element name이 답변 텍스트에 정확히 substring으로 있어야 발동.
#
# 매칭 형태 예시 (group 1 = 전체 인용, group 2 = doc_code/case_id):
#   "법제처 22-0155"
#   "법제처 2022. 1. 28. 회신 22-0155"
#   "법제처 2024. 4. 4. 회신 24-0243"
#   "대법원 2017두73693"
#   "대법원 2013. 1. 17. 선고 2011다83431"
_QA_PROSE_PAT = re.compile(
    r'(?<![가-힣\d])'
    r'(법제처\s+(?:\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.\s*회신\s+)?'
    r'(\d{2}-\d{4}))'
    r'(?!\d)'
)
_CASE_PROSE_PAT = re.compile(
    r'(?<![가-힣\d])'
    r'(대법원\s+(?:\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.\s*선고\s+)?'
    r'(\d{2,4}[가-힣]\d{3,5}))'
    r'(?!\d)'
)


_article_index: dict = {}


def _get_article_index() -> dict:
    """all_articles.jsonl → {(공백·가운뎃점 제거 법령명, 조번호): rec}. 검색 안 된
    인용 조문도 팝업 마킹하기 위한 조회용(전체 조문 보유). 1회 로드 후 캐시."""
    global _article_index
    if _article_index:
        return _article_index
    idx: dict = {}
    p = BASE_DIR / "data" / "raw_laws" / "all_articles.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            ln, art = r.get("law_name", ""), r.get("article_no", "")
            if not ln or not art:
                continue
            key = (re.sub(r"[\s·ㆍ]+", "", ln), art)
            idx.setdefault(key, r)
    _article_index = idx
    return idx


def build_citation_elements(answer: str, result: dict) -> tuple[str, list]:
    law_docs       = result.get("law_docs",       [])
    qa_docs        = result.get("qa_docs",        [])
    case_docs      = result.get("case_docs",      [])
    amendment_docs = result.get("amendment_docs", [])

    elements: list = []
    seen_names: set[str] = set()

    # 0) 입법요지N → "재개정이유 - 공포번호" 치환 + 클릭 element (개정이유 줌인)
    #    부록의 "…대통령령 제NNNNN호 개정이유" 형식도 같은 팝업으로 마킹.
    for i, rec in enumerate(amendment_docs, 1):
        prom = rec.get("공포번호", "") or ""
        enf  = rec.get("시행일", "") or ""
        reason = rec.get("개정이유", "") or ""
        kp = rec.get("목적론적_키포인트", "")
        kp = "\n".join(kp) if isinstance(kp, list) else (str(kp) if kp else "")
        label = f"재개정이유 - {prom}" if prom else f"재개정이유 {i}"
        header = f"**{label}**" + (f"  ·  시행 {enf}" if enf else "")
        content = f"{header}\n\n**개정이유**\n{reason}"
        if kp:
            content += f"\n\n**핵심 취지**\n{kp}"

        pat = re.compile(rf"\[?\s*입법요지\s*{i}\s*(?:참조)?\s*\]?")
        if pat.search(answer):
            answer = pat.sub(label, answer)
            if label not in seen_names:
                seen_names.add(label)
                elements.append(cl.Text(name=label, content=content, display="side"))
        # 부록 형식 "공포번호 개정이유"도 동일 팝업으로 (본문 header의 공포번호와 안 헷갈리게 '개정이유' 필수)
        if prom:
            for m in re.finditer(re.escape(prom) + r"\s*개정이유", answer):
                rn = m.group(0).strip()
                if rn in seen_names:
                    continue
                seen_names.add(rn)
                elements.append(cl.Text(name=rn, content=content, display="side"))

    # 1) 잔존 내부 마커 제거 (LLM이 가끔 무시하고 출력해도 안전망)
    answer = _strip_internal_markers(answer)

    # 2) 자연 산문 인용 패턴 감지 → 사이드 패널 element 생성
    #    "법제처 22-0155" 같은 문구가 답변에 있으면, 그 이름의 cl.Text element를
    #    만들어 두면 Chainlit이 자동으로 클릭 가능한 사이드 패널 링크로 변환한다.

    # doc_code → qa_doc lookup
    qa_lookup = {}
    for d in qa_docs:
        code = d.metadata.get("doc_code", "")
        if code and code not in qa_lookup:
            qa_lookup[code] = d

    for m in _QA_PROSE_PAT.finditer(answer):
        ref_name = m.group(1)   # 답변에 실제 나타난 전체 인용 문자열
        code     = m.group(2)   # doc_code (lookup용)
        if ref_name in seen_names:
            continue
        seen_names.add(ref_name)
        doc = qa_lookup.get(code)
        if doc is None:
            continue
        q   = doc.metadata.get("question", "")
        ans = clean_article_content(_clean_precedent_body(doc.content or "")[:15000])
        date = doc.metadata.get("doc_date", "")
        header = f"**법제처 {code}**" + (f"  ·  {date}" if date else "")
        content = f"{header}\n\n**질문**\n{q}\n\n**답변**\n{ans}"
        elements.append(cl.Text(name=ref_name, content=content, display="side"))

    # 법제처 번호가 없는 부처·지자체 회신형 선례: 검색 때 부착된 공식 인용 표기
    # (cite_label — 예 "국토교통부 2012.07.30. 회신")가 답변에 그대로 나타나면
    # 그 문자열 자체를 element 이름으로 팝업을 건다(리터럴 매칭 — 정규식 불필요).
    # 이전에는 이 유형에 팝업 경로가 아예 없어 '(관련 국토교통부 회신)'처럼
    # 태그 없는 인용으로 뭉개졌다.
    for d in qa_docs:
        label = d.metadata.get("cite_label", "")
        if not label or label in seen_names:
            continue
        # 번호형 법제처 회신(법제처 14-0840)은 위 _QA_PROSE_PAT 경로가 처리.
        # 날짜형(법제처 2006.06.07. 회신)은 번호 정규식에 안 걸리므로 여기서 팝업.
        if re.match(r"법제처\s+\d{2}-\d{3,5}", label):
            continue
        if label not in answer:
            continue
        seen_names.add(label)
        q   = d.metadata.get("question", "")
        ans = clean_article_content(_clean_precedent_body(d.content or "")[:15000])
        ref = d.metadata.get("doc_ref", "")
        header = f"**{label}**" + (f"  ·  {ref}" if ref else "")
        content = f"{header}\n\n**질문**\n{q}\n\n**답변**\n{ans}"
        elements.append(cl.Text(name=label, content=content, display="side"))

    # case_id → case_doc lookup
    case_lookup = {}
    for d in case_docs:
        cid = d.metadata.get("case_id", d.article_no)
        if cid and cid not in case_lookup:
            case_lookup[cid] = d

    for m in _CASE_PROSE_PAT.finditer(answer):
        ref_name = m.group(1)   # 답변에 실제 나타난 전체 인용 문자열
        cid      = m.group(2)   # case_id (lookup용)
        if ref_name in seen_names:
            continue
        seen_names.add(ref_name)
        doc = case_lookup.get(cid)
        if doc is None:
            continue
        court = doc.metadata.get("court", "")
        date  = doc.metadata.get("decision_date", "")
        body  = clean_article_content((doc.content or "")[:15000])
        header_parts = [x for x in [court, cid] if x]
        if date:
            header_parts.append(f"({date} 선고)")
        header = "**" + " ".join(header_parts) + "**"
        content = f"{header}\n\n{body}"
        elements.append(cl.Text(name=ref_name, content=content, display="side"))

    # 3) 법령 조문 자연 인용 — 정규식으로 항·호·목까지 통째로 캡처
    #    축약형 법령명("국토계획법 시행령" 등)도 매칭되어야 하므로 alias 사용.

    # (법령명, 조 번호) → doc 매핑 (중복 제거)
    law_doc_map: dict = {}
    for d in law_docs:
        law = d.law_name
        art = d.article_no
        if law and art and (law, art) not in law_doc_map:
            law_doc_map[(law, art)] = d

    # 조 번호 뒤에 따라붙을 수 있는 항·호·목 패턴 (모두 선택)
    # + 뒤이은 열거("및/·/, 제N호") 까지 한 덩어리로 묶어 마킹 (예: 제3항제3호 및 제4호)
    ART_EXT = (r"(?:\s*제\d+항)?(?:\s*제\d+호)?(?:\s*[가-힣]목)?"
               r"(?:\s*(?:및|·|ㆍ|,)\s*제\d+[항호](?:\s*[가-힣]목)?)*")

    for (law, art), d in law_doc_map.items():
        is_byeolpyo = "별표" in art
        if is_byeolpyo:
            art_pat = re.escape(art)
        else:
            # "제70조" 와 "제70조의2" 가 섞이지 않도록 (?!의) 가드
            art_pat = re.escape(art) + r"(?!의)" + ART_EXT

        # 정식명 + 축약형 모두 매칭 시도
        for alias in _get_law_aliases(law):
            patterns = [
                re.compile(rf"「{re.escape(alias)}」\s*{art_pat}"),
                re.compile(rf"(?<![가-힣·]){re.escape(alias)}\s+{art_pat}"),
            ]
            for pat in patterns:
                for m in pat.finditer(answer):
                    ref_name = m.group(0).strip()
                    if ref_name in seen_names:
                        continue
                    seen_names.add(ref_name)
                    edate = d.metadata.get("enforcement_date", "")
                    header_extra = get_law_header(law, edate)
                    sep = "  ·  " if header_extra else ""
                    body = clean_article_content(d.content)
                    # 사이드 패널 헤더에는 정식 법령명 노출
                    content = f"**{law}  {art}**{sep}{header_extra}\n\n{body}"
                    elements.append(cl.Text(name=ref_name, content=content, display="side"))

    # 3b) 검색되지 않았지만 답변에 인용된 「법령명」 조문도 마킹 (보유 법령 한정).
    #     all_articles 전체 조문에서 조회 — 미보유 법령(예: 경관법)은 자동 스킵.
    idx = _get_article_index()
    for m in re.finditer(r"「([^」]{2,40})」\s*(제\d+조(?:의\d+)?)" + ART_EXT, answer):
        ref_name = m.group(0).strip()
        if ref_name in seen_names:
            continue
        law_raw, art = m.group(1).strip(), m.group(2)
        rec = idx.get((re.sub(r"[\s·ㆍ]+", "", law_raw), art))
        if not rec:
            continue  # 보유하지 않은 법령/조문
        seen_names.add(ref_name)
        ln = rec.get("law_name", law_raw)
        header_extra = get_law_header(ln, rec.get("enforcement_date", ""))
        sep = "  ·  " if header_extra else ""
        body = clean_article_content(rec.get("content", ""))
        content = f"**{ln}  {art}**{sep}{header_extra}\n\n{body}"
        elements.append(cl.Text(name=ref_name, content=content, display="side"))

    # 3-조례) 인용된 조례·업로드 법령 조문 팝업 — 내장 국가법령(3·3b)과 동급 대우.
    #    law_docs가 아니라 내장 지역 팩·업로드 캐시 컬렉션에서 직접 조회하므로,
    #    이번 검색에 안 잡혔어도 보유 중인 조례 인용이면 팝업이 뜬다.
    #    항 청크는 조 단위로, 별표 조각은 통째로 합쳐 원문을 제공한다.
    try:
        _retr = get_generator()._get_retriever()
        _up_key = cl.user_session.get("upload_key", "") or ""
        _ord_names: list[str] = [r["law_name"] for r in _retr.list_region_laws()]
        if _up_key:
            _have = set(_ord_names)
            _ord_names += [r["law_name"] for r in _retr.list_uploaded_docs(_up_key)
                           if r["law_name"] not in _have]
    except Exception:
        _retr, _up_key, _ord_names = None, "", []

    if _retr and _ord_names:
        _ORD_ART_GRP = r"(제\d+조(?:의\d+)?|별표\s?\d+(?:의\d+)?)"
        _answer_norm = re.sub(r"\s+", "", answer)
        for law in _ord_names:
            # 저장 명칭에는 파일명 유래 접미가 붙을 수 있다
            # ('남양주시 건축 조례(경기도 남양주시조례)(제2536호)(20260515)').
            # 인용 대조는 괄호 앞 기본 명칭으로, 원문 조회는 저장 명칭 그대로.
            base = re.split(r"[(\[]", law)[0].strip(" -–—")
            if len(base) < 4:
                base = law
            # 빠른 스킵 — 대부분의 보유 조례는 답변에 안 나온다 (공백 무시 비교)
            if re.sub(r"\s+", "", base) not in _answer_norm:
                continue
            # 명칭 공백 변주 허용 ('도시계획 조례'/'도시계획조례') — 토큰 사이 \s*
            name_pat = r"\s*".join(re.escape(tok) for tok in base.split())
            for pat in (re.compile(rf"「\s*{name_pat}\s*」\s*{_ORD_ART_GRP}" + ART_EXT),
                        re.compile(rf"(?<![가-힣·「]){name_pat}\s+{_ORD_ART_GRP}" + ART_EXT)):
                for m in pat.finditer(answer):
                    ref_name = m.group(0).strip()
                    if ref_name in seen_names:
                        continue
                    art_root = m.group(1).replace(" ", "")
                    try:
                        text = _retr.get_ordinance_article_text(_up_key, law, art_root)
                    except Exception:
                        text = ""
                    if not text:
                        continue
                    seen_names.add(ref_name)
                    # 항 청크의 '[제3조(…)]' 임베딩용 프리픽스는 팝업 표시에선 제거
                    body = re.sub(r"^\[제\d+조[^\]]*\]\s*", "",
                                  clean_article_content(text), flags=re.M)
                    content = f"**{base}  {art_root}**\n\n{body}"
                    elements.append(cl.Text(name=ref_name, content=content, display="side"))

    # 3c) '같은 법/영/규칙 제N조' 대명사 해소 → 앞서 언급된 법령으로 팝업 마킹.
    #     예: "「주차장법 시행령」 …" 다음의 "같은 영 제6조제2항" → 주차장법 시행령 제6조.
    _mentions = [(mm.start(), mm.group(1).strip())
                 for mm in re.finditer(r"「([^」]{2,40})」", answer)]

    def _antecedent(pos: int, kind: str):
        best = None
        for mp, nm in _mentions:
            if mp >= pos:
                break
            is_rule   = nm.endswith("시행규칙") or nm.endswith("규칙")
            is_decree = nm.endswith("시행령")
            is_law    = (nm.endswith("법") or nm.endswith("법률")) and not is_decree and not is_rule
            if kind == "영" and is_decree:
                best = nm
            elif kind == "규칙" and is_rule:
                best = nm
            elif kind == "법" and is_law:
                best = nm
            elif kind in ("법시행령", "법시행규칙") and is_law:
                best = nm + (" 시행령" if kind == "법시행령" else " 시행규칙")
        return best

    _same = re.compile(r"같은\s*(법\s*시행규칙|법\s*시행령|시행규칙|시행령|규칙|영|법)\s*"
                       r"(제\d+조(?:의\d+)?)" + ART_EXT)
    _KIND = {"영": "영", "시행령": "영", "법시행령": "법시행령",
             "규칙": "규칙", "시행규칙": "규칙", "법시행규칙": "법시행규칙", "법": "법"}
    for m in _same.finditer(answer):
        ref_name = m.group(0).strip()
        if ref_name in seen_names:
            continue
        kind = _KIND.get(re.sub(r"\s+", "", m.group(1)))
        if not kind:
            continue
        law = _antecedent(m.start(), kind)
        if not law:
            continue
        art = m.group(2)
        rec = idx.get((re.sub(r"[\s·ㆍ]+", "", law), art))
        if not rec:
            continue
        seen_names.add(ref_name)
        ln = rec.get("law_name", law)
        header_extra = get_law_header(ln, rec.get("enforcement_date", ""))
        sep = "  ·  " if header_extra else ""
        body = clean_article_content(rec.get("content", ""))
        content = f"**{ln}  {art}**{sep}{header_extra}\n\n{body}"
        elements.append(cl.Text(name=ref_name, content=content, display="side"))

    return answer, elements


# ── [출처 요약] 분리 ─────────────────────────────────────────

def split_answer(raw: str) -> tuple[str, str]:
    # LLM이 [출처 요약]을 코드펜스(```) 안에 출력하는 경우도 함께 제거
    m = re.search(r'(?:```[^\n]*\n)?\[출처\s*요약\]', raw)
    if m:
        return raw[: m.start()].rstrip(), raw[m.start():]
    return raw, ""


# ── 입법요지 텍스트 ───────────────────────────────────────────
# 조문·해석례는 답변 본문의 [관련 조문]/[근거 법령 + 인용 선례] 섹션이 조 번호까지
# 포함해 팝업과 함께 더 구체적으로 다루므로 별도 '출처' 메시지에서 제거(중복).
# 입법요지(개정이유)만은 본문 섹션에 목록화되지 않으므로 별도로 유지한다.
# 법률 서치 필요 알림은 _render_blind_spot_notice가 더 상세히 별도 처리하므로 미포함.

def format_amendment_sources(source_info: dict) -> str:
    """입법요지(개정이유) 목록 텍스트. 항목별 한 줄씩(팝업 마킹은 build_citation_elements가 처리)."""
    if not source_info.get("db_amendment"):
        return ""
    items = []
    for m in re.finditer(
        r'([가-힣][가-힣·\s]*?(?:법|령|규칙|규정))\s+\d{4}[-.\s]+\d{1,2}[-.\s]+\d{1,2}'
        r'\s*((?:대통령령|법률|[가-힣]+부령)\s*제\d+호)',
        source_info.get("db_amendment_detail", "")):
        law = re.sub(r'\s+', ' ', m.group(1)).strip()
        prom = re.sub(r'\s+', ' ', m.group(2)).strip()
        line = f"- {law} {prom} 개정이유"
        if line not in items:
            items.append(line)
    if not items:
        return ""
    return "**입법요지**\n" + "\n".join(items)


# ── 섹션 접기/펼치기 ─────────────────────────────────────────

_COLLAPSIBLE = {
    "[관련 조문 확인]",
    "[관련 판례 검토]",
    "[근거 법령 + 인용 선례]",
    "[담당부서 확인 질문]",
    "[해석 분기점]",
}


def make_collapsible_html(body: str) -> str:
    lines = body.split("\n")
    output = []
    in_details = False
    buf = []

    def flush():
        nonlocal in_details, buf
        if in_details:
            output.append("\n".join(buf))
            output.append("</details>\n")
            buf = []
            in_details = False

    for line in lines:
        is_collapse = line.startswith("###") and any(s in line for s in _COLLAPSIBLE)
        if is_collapse:
            flush()
            title = line.lstrip("#").strip()
            output.append(f"<details>\n<summary><strong>{title}</strong></summary>\n")
            in_details = True
        elif in_details:
            buf.append(line)
        else:
            output.append(line)

    flush()
    return "\n".join(output)


# ── 스트리밍 생성 ─────────────────────────────────────────────

async def generate_streaming(gen, query: str, extra_context: str, session_id: str,
                             provider: str = "gemini", model_label: str = "⚡ Gemini",
                             thread_id: str = "", carry_laws: list = None,
                             carry_conclusions: list = None):
    token_q: _queue.Queue = _queue.Queue()
    result_holder: list = [None]
    error_holder:  list = [None]

    def stream_cb(token: str):
        token_q.put(token)

    def worker():
        try:
            result_holder[0] = gen.generate(
                query, False, extra_context, session_id,
                stream_callback=stream_cb,
                provider=provider,
                thread_id=thread_id,
                carry_laws=carry_laws,
                carry_conclusions=carry_conclusions,
            )
        except Exception as e:
            error_holder[0] = e
        finally:
            token_q.put(None)

    thinking_msg = cl.Message(content=f"{model_label} 분석 중…")
    await thinking_msg.send()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    msg = None
    first = True
    while True:
        try:
            token = token_q.get_nowait()
            if token is None:
                break
            if first:
                await thinking_msg.remove()
                msg = cl.Message(content="")
                await msg.send()
                first = False
            await msg.stream_token(token)
        except _queue.Empty:
            await asyncio.sleep(0.01)

    thread.join()

    if error_holder[0]:
        await thinking_msg.remove()
        raise error_holder[0]

    if msg is None:
        await thinking_msg.remove()
        msg = cl.Message(content="답변을 생성하지 못했습니다.")
        await msg.send()
        return msg, None

    await msg.update()
    return msg, result_holder[0]


# ── 내장 법령 목록 ───────────────────────────────────────────

def _collect_law_groups():
    """법령 목록 집계 (마크다운·HTML 공통). 하드코딩 없이 ChromaDB에서 실시간 집계.
    반환: (groups, total). groups=[(그룹명, [(법령명, 시행일str, 공포번호, 개정이력str)…])…]"""
    import os
    import chromadb
    from collections import defaultdict
    path = os.environ.get("CHROMA_DB_PATH", str(BASE_DIR / "data" / "chroma_db"))
    client = chromadb.PersistentClient(path=path)
    metas = client.get_collection("law_articles").get(include=["metadatas"], limit=40000)["metadatas"]

    def _norm(s: str) -> str:
        return re.sub(r"[\s·ㆍ]+", "", s or "")

    amend: dict = defaultdict(list)
    try:
        acol = client.get_collection("law_amendments")
        for am in acol.get(include=["metadatas"], limit=40000)["metadatas"]:
            nm = am.get("law_name", "")
            enf = (am.get("시행일", "") or "").replace(".", "-")
            if nm:
                amend[_norm(nm)].append(enf)
    except Exception:
        pass

    def _amend_cell(nm: str) -> str:
        dates = [d for d in amend.get(_norm(nm), []) if d]
        if not dates:
            return "-"
        def yymm(d):
            p = d.split("-")
            return f"{p[0]}.{p[1]}" if len(p) >= 2 else d
        return f"{yymm(min(dates))} ~ {yymm(max(dates))} ({len(dates)}건)"

    laws: dict = {}
    for m in metas:
        if m.get("is_byeolpyo") == "true":
            continue
        nm = m.get("law_name", "")
        if not nm:
            continue
        enf  = m.get("enforcement_date", "") or ""
        prom = m.get("promulgation_no", "") or ""
        cur = laws.get(nm)
        if cur is None or enf > cur[0]:
            laws[nm] = (enf, prom)

    def _group(nm: str) -> str:
        if nm.startswith("건축법"):
            return "건축법 계열"
        if "국토의 계획" in nm:
            return "국토계획법 계열"
        if nm.startswith("주택법"):
            return "주택법 계열"
        return "기타 내장 법령"

    def _order_key(nm: str):
        # 같은 법령 가족(base)끼리 묶고, 법 → 시행령 → 시행규칙 순으로 정렬.
        base = re.sub(r"\s*(시행령|시행규칙|시행규정|규칙|규정)$", "", nm)
        if "시행규칙" in nm or nm.endswith("규칙"):
            rank = 2
        elif "시행령" in nm or nm.endswith("령") or nm.endswith("규정"):
            rank = 1
        else:
            rank = 0
        return (base, rank, nm)

    grouped: dict = defaultdict(list)
    for nm, (enf, prom) in sorted(laws.items(), key=lambda kv: _order_key(kv[0])):
        grouped[_group(nm)].append((nm, fmt_date(enf) if enf else "-", prom or "-", _amend_cell(nm)))

    order = ["건축법 계열", "국토계획법 계열", "주택법 계열", "기타 내장 법령"]
    return [(g, grouped[g]) for g in order if g in grouped], len(laws)


def build_law_db_info() -> str:
    """내장 법령 목록 마크다운 (채팅 트리거용 폴백)."""
    try:
        groups, total = _collect_law_groups()
    except Exception:
        return "### 📋 내장 법령 데이터베이스\n\n(법령 DB를 불러오지 못했습니다.)"
    lines = ["### 📋 내장 법령 데이터베이스", ""]
    for g, rows in groups:
        lines.append(f"**{g}**")
        lines.append("")
        lines.append("| 법령 | 현행 시행일 | 공포번호 | 개정이력 (시행일 기준) |")
        lines.append("|------|-----------|---------|---------|")
        for nm, enf, prom, am in rows:
            lines.append(f"| {nm} | {enf} | {prom} | {am} |")
        lines.append("")
    lines.append("---")
    lines.append(f"총 **{total}개** 법령 내장. 목록에 없는 법령은 PDF를 첨부하시면 실시간 분석에 활용됩니다.")
    return "\n".join(lines)


def build_law_db_html() -> str:
    """헤더 버튼 모달용 HTML."""
    import html
    try:
        groups, total = _collect_law_groups()
    except Exception:
        return "<p>법령 DB를 불러오지 못했습니다.</p>"
    parts = ['<div class="law-db">', "<h2>📋 내장 법령 데이터베이스</h2>"]
    for g, rows in groups:
        parts.append(f"<h3>{html.escape(g)}</h3>")
        parts.append("<table><thead><tr><th>법령</th><th>현행 시행일</th>"
                     "<th>공포번호</th><th>개정이력 (시행일 기준)</th></tr></thead><tbody>")
        for nm, enf, prom, am in rows:
            parts.append(f"<tr><td>{html.escape(nm)}</td><td>{html.escape(enf)}</td>"
                         f"<td>{html.escape(prom)}</td><td>{html.escape(am)}</td></tr>")
        parts.append("</tbody></table>")
    parts.append(f'<p class="law-db-foot">총 <b>{total}개</b> 법령 내장. '
                 "목록에 없는 법령은 PDF를 첨부하시면 실시간 분석에 활용됩니다.</p>")

    # ── 조례계열 (내장 지역 팩 — ingest/region_packs/*.json) ──
    try:
        packs = _collect_region_packs()
    except Exception:
        packs = []
    if packs:
        parts.append("<h3>조례계열 (지역 팩)</h3>")
        for region, fetched_at, rows in packs:
            parts.append(f"<h3>🏙️ {html.escape(region)}</h3>")
            parts.append("<table><thead><tr><th>자치법규</th><th>조문</th>"
                         "<th>근거(인용 국가법령)</th></tr></thead><tbody>")
            for nm, n_art, cited in rows:
                parts.append(f"<tr><td>{html.escape(nm)}</td><td>{n_art}</td>"
                             f"<td>{html.escape(cited)}</td></tr>")
            parts.append("</tbody></table>")
            parts.append(f'<p class="law-db-foot">{html.escape(region)} 자치법규 {len(rows)}건 내장 '
                         f'· 자치법규 API 패치 기준일 {html.escape(fetched_at)}. '
                         "질문·대화에 이 지역이 언급되면 자동으로 검색에 참여합니다.</p>")

    parts.append("</div>")
    return "\n".join(parts)


def _collect_region_packs() -> list:
    """내장 지역 조례 팩 목록 — [(지역, 패치일, [(법규명, 조문수, 인용법령), ...])]."""
    out = []
    d = BASE_DIR / "ingest" / "region_packs"
    if not d.exists():
        return out
    for pf in sorted(d.glob("*.json")):
        try:
            pack = json.loads(pf.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows = []
        for ln, info in sorted((pack.get("laws") or {}).items()):
            cited = ", ".join((info.get("cited_laws") or [])[:3])
            rows.append((ln, len(info.get("articles") or {}), cited))
        if rows:
            out.append((pack.get("region", ""), pack.get("fetched_at", ""), rows))
    return out

_LAW_LIST_TRIGGER = "📋 내장 법령 목록"


# ── Chainlit 핸들러 ─────────────────────────────────────────

_LAW_LIST_STARTER = cl.Starter(
    label="📋 내장 법령 목록", message=_LAW_LIST_TRIGGER, icon="/public/starter_list.svg"
)

_STARTER_POOL = [
    cl.Starter(label="🏗️ 건축허가·신고", message="건축허가와 건축신고의 대상 기준과 차이를 알려주세요."),
    cl.Starter(label="🗺️ 용도지역 제한", message="용도지역별 건폐율·용적률 기준과 건축 제한을 알려주세요."),
    cl.Starter(label="🔥 피난·방화 기준", message="피난계단 및 방화구획 설치 기준을 알려주세요."),
    cl.Starter(label="👷 감리 대상·절차", message="건축 감리 대상 건축물과 감리 절차를 알려주세요."),
    cl.Starter(label="🚗 주차장 설치기준", message="건축물 용도별 부설주차장 설치 기준을 알려주세요."),
    cl.Starter(label="☀️ 일조권 높이제한", message="전용주거·일반주거지역의 일조권 높이 제한 기준을 알려주세요."),
    cl.Starter(label="🛠️ 대수선 범위", message="대수선의 정의와 범위, 허가·신고 대상을 알려주세요."),
    cl.Starter(label="📐 건폐율·용적률", message="용도지역별 건폐율과 용적률 상한 기준을 알려주세요."),
    cl.Starter(label="🛣️ 접도의무", message="건축물 대지의 접도의무 요건과 예외를 알려주세요."),
    cl.Starter(label="🏢 다중이용 건축물", message="다중이용 건축물의 정의와 강화되는 기준을 알려주세요."),
    cl.Starter(label="🪜 직통계단 설치", message="직통계단 2개소 이상 설치 대상과 보행거리 기준을 알려주세요."),
]


@cl.set_starters
async def set_starters():
    # 내장 법령 목록은 상단 헤더 버튼(custom.js)으로 옮김. 여기선 추천질문만 4개 로테이션.
    return random.sample(_STARTER_POOL, k=min(4, len(_STARTER_POOL)))


def _thread_scope() -> str:
    """조례 등 대화 한정 업로드의 스코프 키. 대화(thread) 단위로 고정 —
    thread_id가 아직 없으면 세션 id로 폴백. 같은 대화 내에선 일관된 값."""
    try:
        tid = getattr(cl.context.session, "thread_id", None)
        return tid or cl.context.session.id
    except Exception:
        return ""


def _init_session():
    cl.user_session.set("pdf_list", [])
    cl.user_session.set("pdf_ready", False)
    cl.user_session.set("history", [])
    cl.user_session.set("session_facts", {})
    cl.user_session.set("used_laws", [])
    cl.user_session.set("session_conclusions", [])

    session_id = cl.context.session.id
    # 업로드 영속 키: 사용자 anon_id 기준 → 재방문 시 이전 업로드 재사용.
    # (인증 사용자 정보가 없으면 대화 세션id로 폴백)
    user = getattr(cl.context.session, "user", None)
    upload_key = getattr(user, "identifier", None) or session_id

    gen = get_generator()
    retriever = gen._get_retriever()
    retriever.create_session_collection(upload_key)
    cl.user_session.set("session_id", session_id)
    cl.user_session.set("upload_key", upload_key)


# ── 연속 질의 맥락 (대화 히스토리 → 생성 컨텍스트) ──────────────────
# 예전에는 직전 3턴을 답변 300자로 잘라 무설명 'Q:/A:' 로만 주입해,
# 후속 질문("각 시설의 필요 면적은?")에서 지시어가 해소되지 않고 직전 답변을
# 되풀이하거나 이전 답변과 모순되는 문제가 있었다(2026-07-09 실사례).

_HISTORY_TURNS = 3        # 주입할 직전 턴 수
_HISTORY_A_CAP = 1200     # 턴당 답변 보존 길이


_CONCLUSIONS_CAP = 20   # 세션 내 결론 누적 상한 (오래된 것부터 밀려남)


def _accumulate_conclusions(prev: list, result: dict) -> list:
    """이번 답변에서 추출된 결론을 세션 누적 리스트에 추가.

    또한 이전과 동일한 법령 ref를 가진 결론은 새 결론으로 교체 (조정된 결론 반영)."""
    new_conclusions = result.get("conclusions") or []
    if not new_conclusions:
        return list(prev or [])

    # 새 결론의 ref 집합
    new_ref_keys: set[str] = set()
    for c in new_conclusions:
        for ref in c.get("refs", []):
            new_ref_keys.add(re.sub(r'\s+', '', ref))

    # 기존 결론 중 새 결론과 겹치는 ref가 있으면 제거 (업데이트)
    kept = []
    for c in (prev or []):
        overlap = any(
            re.sub(r'\s+', '', ref) in new_ref_keys
            for ref in c.get("refs", [])
        )
        if not overlap:
            kept.append(c)

    kept.extend(new_conclusions)
    return kept[-_CONCLUSIONS_CAP:]


_USED_LAWS_CAP = 30   # 누적 법령 세트 상한 (오래된 것부터 밀려남)


def _accumulate_used_laws(prev: list, result: dict) -> list:
    """이번 답변이 활용한 법령을 누적 세트에 더한다(연속 질의에서 계속 붙잡을 대상).

    활용 근거로 삼는 것: 업로드 조례(source=uploaded, 사용자가 올린 핵심 자료)와
    law_hints로 강제 포함된 조문(score_type=exact) + 상위 벡터 조문 소수.
    검색됐으나 인용도 안 된 하위 벡터 노이즈까지 누적하지 않도록 선별한다."""
    used = list(prev or [])
    seen = {(u["law_name"], u["article_no"]) for u in used}

    def _add(law_name, article_no, source):
        if not law_name or not article_no:
            return
        # 항 청크("제5조 ①")는 조 단위로 정규화 — 다음 턴 강제 포함·law_hints가
        # 특정 항에 갇히지 않고 조 전체(모든 항)를 잡도록.
        article_no = re.sub(r'\s*[①-⑳㉑-㉚].*$', '', str(article_no)).strip() or str(article_no)
        k = (law_name, article_no)
        if k in seen:
            return
        seen.add(k)
        used.append({"law_name": law_name, "article_no": article_no, "source": source})

    # 업로드 조례·법령 — 전부 누적 (사용자가 명시적으로 올린 자료)
    for d in result.get("uploaded_docs") or []:
        _add(getattr(d, "law_name", ""), getattr(d, "article_no", ""), "uploaded")
    # DB 조문 — exact(law_hints 강제) 우선, 그 외 상위 몇 개만
    vec_added = 0
    for d in result.get("law_docs") or []:
        st = getattr(d, "score_type", "")
        if st in ("exact", "carry"):
            _add(getattr(d, "law_name", ""), getattr(d, "article_no", ""), "db")
        elif vec_added < 5:
            _add(getattr(d, "law_name", ""), getattr(d, "article_no", ""), "db")
            vec_added += 1
    return used[-_USED_LAWS_CAP:]


def _history_answer(body: str) -> str:
    """히스토리에 저장할 답변 요약: 참조 목록·출처 섹션 앞까지의 본문(결론+이유)만.
    결론 수치·적용 조례 같은 확정 사실이 잘리지 않게 300→1200자로 확대."""
    for marker in ("[관련 조문", "[근거 법령", "[출처 요약", "[담당부서", "[검색 태그"):
        i = body.find(marker)
        if i > 0:
            body = body[:i]
    return body.strip()[:_HISTORY_A_CAP]


def _history_context(history: list, facts: dict | None = None) -> str:
    """직전 턴들 + 세션 사실표를 생성 파이프라인용 맥락 블록으로 조립.
    이 헤더 문자열('[이전 대화 맥락]')은 06_Generator가 pass1 입력 보강의
    게이트로도 사용하므로 바꾸면 함께 바꿔야 한다."""
    if not history:
        return ""
    lines = [
        "=== [이전 대화 맥락] ===",
    ]
    if facts:
        lines.append(
            "[확정 사실표] " + " | ".join(f"{k}={v}" for k, v in facts.items())
            + "  (이 대화에서 확정된 파라미터 — 현재 질문과 무관하면 무시)")
    lines += [
        "아래는 이 세션의 직전 질의응답이다. 현재 질문이 지시어('각 시설', '그럼', "
        "'그 경우')나 생략된 주어를 쓰면 이 맥락의 대상을 가리키는 후속 질문이다. "
        "이전 답변에서 확정된 사실·수치·적용 조례는 그대로 전제로 삼아 이어서 답하고, "
        "같은 내용을 처음부터 반복 설명하지 마라. 단, 이전 답변이 이번 검색 자료와 "
        "모순되면 정정하고 그 사실을 명시하라.",
    ]
    for h in history[-_HISTORY_TURNS:]:
        lines.append(f"\n[이전 질문] {h['q']}")
        lines.append(f"[이전 답변] {h['a']}")
    return "\n".join(lines)


@cl.on_chat_start
async def on_start():
    _init_session()


@cl.on_chat_resume
async def on_resume(thread):
    # 과거 대화를 사이드바에서 클릭해 재개할 때 호출.
    # 화면의 메시지는 Chainlit이 thread에서 자동 복원하고, 여기선 검색용 세션
    # 컬렉션·업로드 상태를 새로 초기화한 뒤 대화맥락(history)을 스텝에서 복원한다.
    # (예전엔 비운 채 시작해 재개 후 첫 후속 질문이 무맥락으로 처리됐음)
    _init_session()
    try:
        aux_authors = {"사각지대 알림", "입법요지"}
        history, pending_q, last_a = [], None, None
        for step in (thread or {}).get("steps", []) or []:
            stype = step.get("type", "")
            out = (step.get("output") or "").strip()
            name = step.get("name", "")
            if stype == "user_message":
                if pending_q and last_a:
                    history.append({"q": pending_q, "a": _history_answer(last_a)})
                pending_q, last_a = out, None
            elif stype == "assistant_message":
                # 보조 메시지(알림·입법요지·피드백 인사 등)는 본답변이 아님 —
                # author 제외 + 짧은 출력 제외. 같은 질문에 답변이 여러 개면
                # (재생성 등) 마지막 것을 채택.
                if name in aux_authors or len(out) < 120:
                    continue
                last_a = out
        if pending_q and last_a:
            history.append({"q": pending_q, "a": _history_answer(last_a)})
        if history:
            cl.user_session.set("history", history[-_HISTORY_TURNS:])
    except Exception:
        pass   # 복원 실패 시 빈 맥락으로 시작(종전 동작)


@cl.action_callback("helpful")
async def on_helpful(action: cl.Action):
    await action.remove()
    await cl.Message(content="피드백 감사합니다! 😊").send()


@cl.action_callback("not_helpful")
async def on_not_helpful(action: cl.Action):
    await action.remove()
    await cl.Message(content="피드백 감사합니다. 더 나은 답변을 위해 참고하겠습니다.").send()


@cl.action_callback("new_chat")
async def on_new_chat(action: cl.Action):
    cl.user_session.set("history", [])
    cl.user_session.set("session_facts", {})
    cl.user_session.set("used_laws", [])
    cl.user_session.set("session_conclusions", [])
    cl.user_session.set("pdf_list", [])
    cl.user_session.set("pdf_ready", False)
    cl.user_session.set("provider", None)   # 모델 선택 초기화 → 새 채팅 첫 질문에 다시 선택
    await cl.Message(content="대화 이력이 초기화되었습니다. 새 질의를 입력해 주세요.").send()


async def _show_upload_cache():
    """업로드 캐시 목록 + 항목별 삭제 버튼."""
    session_id = cl.user_session.get("upload_key", "")
    gen = get_generator()
    retriever = gen._get_retriever()
    docs = await asyncio.to_thread(retriever.list_uploaded_docs, session_id)
    if not docs:
        await cl.Message(content="조례 라이브러리가 비어 있습니다. PDF를 첨부하면 여기에 저장됩니다.").send()
        return
    lines = ["**📂 조례 라이브러리**", ""]
    actions = []
    for d in docs:
        tag = " · 조례(업로드한 대화 한정)" if d["is_ordinance"] else ""
        lines.append(f"- **{d['law_name']}** ({d['chunks']}개 청크){tag}")
        actions.append(cl.Action(
            name="delete_upload",
            label=f"🗑 {d['law_name'][:28]} 삭제",
            payload={"law_name": d["law_name"]},
        ))
    lines.append("")
    lines.append("아래 버튼으로 개별 삭제할 수 있습니다. (미사용 30일 후엔 자동 정리)")
    await cl.Message(content="\n".join(lines), actions=actions).send()


@cl.action_callback("delete_upload")
async def on_delete_upload(action: cl.Action):
    law_name = (action.payload or {}).get("law_name", "")
    session_id = cl.user_session.get("upload_key", "")
    gen = get_generator()
    retriever = gen._get_retriever()
    n = await asyncio.to_thread(retriever.delete_uploaded_doc, session_id, law_name)
    await action.remove()
    # 세션 pdf_list에서도 제거
    pdf_list = [p for p in cl.user_session.get("pdf_list", []) if p != law_name]
    cl.user_session.set("pdf_list", pdf_list)
    if not pdf_list:
        cl.user_session.set("pdf_ready", False)
    await cl.Message(content=f"🗑 **{law_name}** 삭제 완료 ({n}개 청크).").send()


_UPLOAD_CACHE_TRIGGERS = {"업로드 목록", "업로드 캐시", "업로드 관리", "라이브러리", "조례 라이브러리", "/uploads"}


@cl.on_message
async def on_message(message: cl.Message):
    # ── 법령 목록 트리거 ──────────────────────────────────────
    if message.content.strip() == _LAW_LIST_TRIGGER:
        await cl.Message(content=build_law_db_info()).send()
        return

    # ── 업로드 캐시 조회/삭제 트리거 ──────────────────────────
    if message.content.strip() in _UPLOAD_CACHE_TRIGGERS:
        await _show_upload_cache()
        return

    # ── PDF 첨부 처리 ─────────────────────────────────────────
    if message.elements:
        for elem in message.elements:
            if not hasattr(elem, "path") or not elem.path:
                continue
            name = getattr(elem, "name", "업로드 법령")
            if not name.lower().endswith(".pdf"):
                continue

            law_label = name.replace(".pdf", "").replace(".PDF", "")

            parsing_msg = cl.Message(content=f"**{law_label}** 파싱 중…")
            await parsing_msg.send()

            pdf_text = parse_pdf(elem.path)
            chunks = chunk_law_pdf(pdf_text, law_label)

            await parsing_msg.remove()

            indexing_msg = cl.Message(
                content=f"**{law_label}** 임베딩 중… ({len(chunks)}개 청크) 질문을 먼저 입력하셔도 됩니다."
            )
            await indexing_msg.send()

            session_id = cl.user_session.get("upload_key", "")
            thread_scope = _thread_scope()

            async def do_index(chunks=chunks, session_id=session_id, thread_scope=thread_scope,
                               msg=indexing_msg, label=law_label):
                gen = get_generator()
                retriever = gen._get_retriever()
                n = await asyncio.to_thread(retriever.index_uploaded_chunks, session_id, chunks, thread_scope)

                pdf_list = cl.user_session.get("pdf_list", [])
                if label not in pdf_list:
                    pdf_list.append(label)
                    cl.user_session.set("pdf_list", pdf_list)
                cl.user_session.set("pdf_ready", True)

                await msg.remove()
                tags = " · ".join(f"`{p}`" for p in pdf_list)
                await cl.Message(
                    content=f"**{label}** 인덱싱 완료 ({n}개 청크)\n📎 활성 파일: {tags}"
                ).send()

            asyncio.create_task(do_index())

    # ── 텍스트 질의 처리 ─────────────────────────────────────
    query = message.content.strip()
    if not query:
        return

    # ── 비밀 트리거: (gemma) prefix → 로컬 Gemma로 강제 라우팅 ─
    # 트리거는 prefix만 인식. 우연 충돌 방지 + 모델 선택 버튼 우회.
    gemma_forced = False
    if query.lower().startswith("(gemma)"):
        gemma_forced = True
        query = query[len("(gemma)"):].strip()
        if not query:
            await cl.Message(content="(gemma) 트리거 뒤에 질문을 입력해 주세요.").send()
            return

    # ── 모델 선택 ─────────────────────────────────────────────
    gen = get_generator()
    if gemma_forced:
        provider = "gemma"
        model_label = "🟢 Gemma (Local)"
    else:
        saved = cl.user_session.get("provider")
        if saved:
            # 한 번 선택한 모델을 세션 내내 재사용 (후속 질문엔 다시 묻지 않음).
            # 모델을 바꾸려면 새 채팅을 시작하면 된다.
            provider = saved
        else:
            actions = [
                cl.Action(name="gemini", label="⚡ Gemini", payload={"provider": "gemini"}),
            ]
            if gen._claude_client:
                actions.append(
                    cl.Action(name="claude", label="🔷 Claude", payload={"provider": "claude"})
                )

            if len(actions) > 1:
                res = await cl.AskActionMessage(
                    content="어떤 모델로 답변할까요?",
                    actions=actions,
                    timeout=30,
                ).send()
                provider = (res.get("payload") or {}).get("provider", "gemini") if res else "gemini"
            else:
                provider = "gemini"
            cl.user_session.set("provider", provider)   # 첫 선택을 세션에 저장

    # 히스토리 + 세션 사실표에서 연속 질의 맥락 구성
    history = cl.user_session.get("history", [])
    extra_context = _history_context(history, cl.user_session.get("session_facts") or {})

    session_id = cl.user_session.get("upload_key", "")
    # provider별 라벨 — gemma_forced 케이스에서 이미 설정된 model_label은 보존
    model_label = {
        "gemma":  "🟢 Gemma (Local)",
        "claude": "🔷 Claude",
        "gemini": "⚡ Gemini",
    }.get(provider, "⚡ Gemini")

    try:
        msg, result = await generate_streaming(
            gen, query, extra_context, session_id, provider, model_label,
            thread_id=_thread_scope(),
            carry_laws=cl.user_session.get("used_laws") or [],
            carry_conclusions=cl.user_session.get("session_conclusions") or [],
        )
    except Exception as e:
        await cl.Message(content=f"오류가 발생했습니다: {e}").send()
        return

    if result is None:
        return

    raw_answer  = result.get("answer", "")
    source_info = result.get("source_info", {})
    if not isinstance(source_info, dict):
        source_info = {}

    # [출처 요약] 제거 + 인용 마커 처리
    body, _ = split_answer(raw_answer)
    body, cite_elements = build_citation_elements(body, result)

    # 스트리밍된 메시지를 최종 본문으로 업데이트 (출처 요약 제거 + 사이드패널 연결)
    msg.content = body
    if cite_elements:
        msg.elements = cite_elements
    await msg.update()

    # 입법요지(개정이유) 별도 메시지 — 팝업 연결. 조문·해석례는 본문 섹션과 중복이라 제거.
    amendment_text = format_amendment_sources(source_info)
    if amendment_text:
        amendment_text, src_elements = build_citation_elements(amendment_text, result)
        await cl.Message(content=amendment_text, author="입법요지",
                         elements=src_elements or None).send()

    # 사각지대 알림 + 재생성 액션 (DB 미수록 법령이 있을 때만)
    await _render_blind_spot_notice(
        result.get("blind_spots", {}),
        query=query,
        provider=provider,
        model_label=model_label,
    )

    # 히스토리 업데이트 — 결론·수치가 잘리지 않게 본문 요약으로 저장
    history.append({"q": query, "a": _history_answer(body)})
    cl.user_session.set("history", history)
    # 세션 사실표 갱신 — pass1이 매 턴 '현재 유효한 파라미터 전체'를 다시 내놓으므로
    # 병합 없이 최신본으로 교체(주제가 바뀌면 자연히 비워짐)
    cl.user_session.set("session_facts", result.get("session_facts") or {})
    # 누적 법령 세트 갱신 — 이번 답변이 활용한 법령을 계속 붙잡아 다음 질문에 강제 포함
    cl.user_session.set("used_laws",
                        _accumulate_used_laws(cl.user_session.get("used_laws"), result))
    # 누적 결론 세트 갱신 — 이번 답변에서 도출한 결론을 다음 질문에 전제로 전달
    cl.user_session.set("session_conclusions",
                        _accumulate_conclusions(cl.user_session.get("session_conclusions"), result))


# ── 사각지대 알림 + 재생성 ──────────────────────────────────────

async def _render_blind_spot_notice(
    blind_spots: dict,
    query: str,
    provider: str,
    model_label: str,
) -> None:
    """사각지대 알림 카드 + '캐싱 후 재생성' 액션 버튼."""
    if not isinstance(blind_spots, dict):
        return
    fetchable    = blind_spots.get("fetchable", [])
    manual_check = blind_spots.get("manual_check", [])
    if not fetchable and not manual_check:
        return

    lines: list[str] = ["📡 **사각지대 법령 감지**"]
    if fetchable:
        lines.append("\n**API 패치 가능 (현행 법령, DB 미수록):**")
        for f in fetchable:
            art = f.get("article_no", "") or "(법령 전체)"
            lines.append(f"  · 「{f['law_name']}」 {art}")
    if manual_check:
        lines.append("\n**수동 확인 필요:**")
        for m in manual_check:
            reason = m.get("reason", "미상")
            tag = {"별표": "📎 별표", "과거시점": "🕰 과거시점", "미상": "❓ 미상"}.get(reason, reason)
            lines.append(f"  · {m['hint']} — {tag}")

    # 조례도 자치법규 API(ordin)로 캐싱을 시도한다. API에서 못 찾는 자료(미등재
    # 자치법규·옛 자료·별표 등)를 위한 직접 업로드 경로 안내.
    if any("조례" in f.get("law_name", "") for f in fetchable) or manual_check:
        lines.append("\n💡 API로 못 찾는 자료(미등재 자치법규·옛 자료 등)는 아래 **‘PDF 직접 첨부’** "
                     "버튼이나 상단 **‘조례 라이브러리 → ＋PDF 파일 추가’**로 등록하면 답변에 반영됩니다.")

    # 자료 모으기(캐싱·첨부)와 재생성을 분리 — 여러 자료를 캐싱/첨부로 적재한 뒤
    # '답변 다시 생성' 한 번으로 전부 반영한다.
    actions: list = []
    if fetchable:
        # 페이로드에 필요한 정보 전부 담아 콜백에서 그대로 사용
        actions.append(cl.Action(
            name="regenerate_with_fetch",
            label="📡 해당 법령 캐싱",
            payload={
                "query":      query,
                "provider":   provider,
                "model_label": model_label,
                "fetchable":  fetchable,
            },
        ))
    # API 패치 대신(또는 API에 없는 자료를) PDF로 직접 등록하는 선택지 — 항상 노출
    actions.append(cl.Action(
        name="blind_spot_pdf_attach",
        label="📎 PDF 직접 첨부",
        payload={
            "query":      query,
            "provider":   provider,
            "model_label": model_label,
        },
    ))
    actions.append(cl.Action(
        name="blind_spot_regen",
        label="🔄 답변 다시 생성",
        payload={
            "query":      query,
            "provider":   provider,
            "model_label": model_label,
        },
    ))

    await cl.Message(
        content="\n".join(lines),
        actions=actions,
        author="사각지대 알림",
    ).send()


@cl.action_callback("regenerate_with_fetch")
async def on_regenerate_with_fetch(action: cl.Action):
    """'해당 법령 캐싱' 클릭 시 — API 패치만 수행하고 자료를 적재.

    재생성은 별도의 '답변 다시 생성' 버튼이 담당한다(캐싱·첨부를 여러 번
    거친 뒤 한 번에 반영). 콜백 이름은 기존 렌더링된 버튼과의 호환을 위해 유지."""
    payload = action.payload or {}
    fetchable = payload.get("fetchable", [])
    query     = payload.get("query", "")
    provider    = payload.get("provider", "gemini")
    model_label = payload.get("model_label", "⚡ Gemini")

    if not query or not fetchable:
        await action.remove()
        await cl.Message(content="캐싱 정보가 부족합니다.", author="사각지대 알림").send()
        return

    # 버튼 제거 (중복 클릭 방지)
    await action.remove()

    # 패치 진행 메시지
    fetch_msg = cl.Message(
        content=f"📡 법제처 API에서 {len(fetchable)}건 패치 중…",
        author="사각지대 알림",
    )
    await fetch_msg.send()

    # API 패치 (백그라운드 스레드)
    from ingest import law_api_fetcher

    success: list[dict] = []
    failed:  list[dict] = []

    def do_fetch_one(law_name: str, article_no: str):
        # 조문 단위. 같은 법령의 다른 조문은 캐시에서 즉시.
        # (조례는 fetch_article 내부에서 ordin 타겟으로 자동 라우팅)
        if article_no:
            content = law_api_fetcher.fetch_article(law_name, article_no)
            return content
        # article_no 없으면 법령 전체 — 일단 캐시만 채우고 본문은 None 처리
        if law_api_fetcher._is_ordinance(law_name):
            articles = law_api_fetcher.fetch_ordinance(law_name)
            return next(iter(articles.values()), None) if articles else None
        law_id = law_api_fetcher._fetch_law_id(law_name)
        if not law_id:
            return None
        articles = law_api_fetcher._fetch_full_law(law_id)
        if articles:
            law_api_fetcher._save_cache(
                law_name, articles, law_api_fetcher._fetch_delegations(law_id))
            # 대표로 첫 조문 반환
            return next(iter(articles.values()), None)
        return None

    def follow_delegations(law_name: str, article_no: str, cap: int = 3):
        # 캐시에 동봉된 위임 링크('대통령령으로 정하는' → 시행령 제N조)를 따라
        # 대상 조문을 동반 로드. 대상 법령도 fetch_article이 통째 캐싱한다.
        # 위임이 상한을 넘으면(예: 건축기본법 제13조 → 시행령 제5~14조 10건)
        # 질문과 관련도 높은 순으로 본문 주입을 고르고, 나머지는 제목 목록으로
        # 남겨 모델이 위임 지도의 존재를 알 수 있게 한다(조용히 버리지 않음).
        # 관련도는 문자 바이그램 겹침 — 단어 완전일치는 조사('분과위원회는' vs
        # '분과위원회')에 빗나가므로 2글자 조각 단위로 비교한다.
        def _bigrams(s: str) -> set[str]:
            s = re.sub(r"[^가-힣]", "", s)
            return {s[i:i + 2] for i in range(len(s) - 1)}
        q_bi = _bigrams(query)
        scored = []
        for tgt in law_api_fetcher.fetch_delegations(law_name, article_no):
            content = law_api_fetcher.fetch_article(tgt["law"], tgt["art"]) or ""
            sc = len(q_bi & _bigrams(f"{tgt.get('title', '')} {content[:400]}"))
            scored.append((sc, tgt, content))
        scored.sort(key=lambda x: -x[0])
        loaded, rest = [], []
        for _, tgt, content in scored:
            label = f"{tgt['art']}({tgt['title']})" if tgt.get("title") else tgt["art"]
            if content and len(loaded) < cap:
                loaded.append({"law_name": tgt["law"], "article_no": tgt["art"],
                               "content": content,
                               "via": f"「{law_name}」 {article_no}"})
            else:
                rest.append(f"{tgt['law']} {label}")
        return loaded, rest

    for f in fetchable:
        content = await asyncio.to_thread(
            do_fetch_one, f["law_name"], f.get("article_no", "")
        )
        entry = {**f, "content": content or ""}
        if content:
            success.append(entry)
        else:
            failed.append(entry)

    # 위임 조문 동반 로드 (성공 조문의 하위법령 링크 1-hop, 본문 주입 전체 상한 6건)
    delegated: list[dict] = []          # 본문까지 주입
    delegated_rest: list[str] = []      # 상한 초과분 — 제목 목록만 주입
    seen_arts = {(s["law_name"], s.get("article_no", "")) for s in success}
    for s in success:
        if not s.get("article_no"):
            continue
        loaded, rest = await asyncio.to_thread(
            follow_delegations, s["law_name"], s["article_no"]
        )
        for d in loaded:
            dk = (d["law_name"], d["article_no"])
            if dk in seen_arts:
                continue
            if len(delegated) >= 6:
                rest.append(f"{d['law_name']} {d['article_no']}")
                continue
            seen_arts.add(dk)
            delegated.append(d)
        if rest:
            delegated_rest.append(
                f"「{s['law_name']}」 {s['article_no']}의 그 밖의 위임 조문: "
                + ", ".join(rest))

    # 패치 성공한 조례는 업로드 캐시에도 전역 인덱싱 — law_cache(JSON)만으로는
    # 이후 턴의 벡터 검색이 안 되므로, PDF 업로드와 동일하게 검색·조 전체 강제
    # 포함이 동작하게 한다. 이미 등록된 조례는 건너뜀(갱신은 업로드 캐시 창의 재캐싱).
    ordin_indexed: list[tuple[str, int]] = []
    ordin_names = {s["law_name"] for s in success
                   if law_api_fetcher._is_ordinance(s.get("law_name", ""))}
    if ordin_names:
        up_key = cl.user_session.get("upload_key", "")
        retr = get_generator()._get_retriever()

        # 보유 대조는 공백 제거 정규화 — '주거환경 정비조례'/'주거환경정비 조례'
        # 표기 변주로 이미 가진(업로드·내장 팩) 조례를 중복 등록하지 않게.
        def _norm_ln(s: str) -> str:
            return re.sub(r"\s+", "", s or "")

        already: set = set()
        try:
            already |= {_norm_ln(d["law_name"]) for d in retr.list_uploaded_docs(up_key)}
        except Exception:
            pass
        try:
            already |= {_norm_ln(d["law_name"]) for d in retr.list_region_laws()}
        except Exception:
            pass

        def _index_ordin(ln: str) -> int:
            arts = law_api_fetcher.fetch_ordinance(ln) or {}   # 방금 캐싱분 — 즉시
            jo_text = "\n".join(v for k, v in arts.items() if not str(k).startswith("별표"))
            chunks = chunk_law_pdf(jo_text, ln) if jo_text else []
            # 별표는 조문 정규식으로 못 쪼개므로 별도 청크로 (긴 별표는 길이 분할).
            # 별표 유형별 청킹 전략은 별도 설계 예정 — 그때 전용 청커로 교체.
            for k, v in arts.items():
                if not str(k).startswith("별표"):
                    continue
                for j in range(0, len(v), 4000):
                    chunks.append({
                        "law_name": ln,
                        "article_no": k if j == 0 else f"{k}({j // 4000 + 1})",
                        "content": v[j:j + 4000],
                    })
            if not chunks:
                return 0
            retr.create_session_collection(up_key)
            return retr.index_uploaded_chunks(up_key, chunks, "")  # thread_id="" → 전역

        for ln in sorted(ln for ln in ordin_names if _norm_ln(ln) not in already):
            try:
                n = await asyncio.to_thread(_index_ordin, ln)
            except Exception:
                n = 0
            if n:
                ordin_indexed.append((ln, n))

    # 결과 알림
    result_lines = ["📡 **패치 결과**"]
    if success:
        result_lines.append("\n**✓ 캐싱 성공:**")
        for s in success:
            art = s.get("article_no", "") or "(전체)"
            result_lines.append(f"  · 「{s['law_name']}」 {art}")
    if ordin_indexed:
        result_lines.append("\n**↳ 조례 업로드 캐시 전역 등록:**")
        for ln, n in ordin_indexed:
            result_lines.append(f"  · 「{ln}」 ({n}개 청크) — 이후 대화에서도 검색됩니다")
    if delegated:
        result_lines.append("\n**↳ 위임 조문 동반 로드:**")
        for d in delegated:
            result_lines.append(
                f"  · 「{d['law_name']}」 {d['article_no']} ← {d['via']}의 위임")
        if delegated_rest:
            result_lines.append("  · (그 밖의 위임 조문은 목록으로만 제공)")
    if failed:
        result_lines.append("\n**✗ 패치 실패 (API에서 못 찾음):**")
        for fa in failed:
            art = fa.get("article_no", "") or "(전체)"
            result_lines.append(f"  · 「{fa['law_name']}」 {art}")

    await fetch_msg.remove()
    await cl.Message(content="\n".join(result_lines), author="사각지대 알림").send()

    if not success:
        hint = ""
        if any("조례" in fa.get("law_name", "") for fa in failed):
            hint = ("\n\n💡 조례는 지자체명을 포함한 정확한 명칭이어야 자치법규 API에서 "
                    "찾습니다(예: '남양주시 주택 조례'). 그래도 못 찾으면 **‘📎 PDF 직접 "
                    "첨부’** 버튼이나 상단 **‘조례 라이브러리 → ＋PDF 파일 추가’**로 직접 "
                    "등록하시면 답변에 반영됩니다.")
        await cl.Message(
            content="패치 성공 자료가 없습니다." + hint,
            author="사각지대 알림",
        ).send()
        return

    # 패치 원문을 재생성용 자료로 적재 (재생성은 '답변 다시 생성' 버튼에서 일괄)
    blocks = ["[출처: 법제처 API 패치]"]
    for s in success:
        blocks.append(f"[법령원문] 「{s['law_name']}」 {s.get('article_no', '')}")
        blocks.append(s["content"])
    for d in delegated:
        blocks.append(
            f"[위임법령] 「{d['law_name']}」 {d['article_no']} — {d['via']}의 위임 조문")
        blocks.append(d["content"])
    if delegated_rest:
        blocks.append(
            "[위임법령 목록] 아래 조문들도 위임 관계이나 본문은 미주입 — "
            "답변에 필요하면 해당 조문의 존재를 안내하세요.")
        blocks.extend(delegated_rest)
    _stash_regen_material(query, "\n".join(blocks))

    # 재생성 버튼을 이 자리에 다시 노출 — 원래 알림 카드의 버튼은 패치 결과가
    # 길면 화면 위로 밀려 찾기 어렵다.
    await cl.Message(
        content="✅ 캐싱 완료 — 더 캐싱·첨부할 자료가 있으면 계속 등록하시고, "
                "**‘🔄 답변 다시 생성’**을 누르면 적재된 자료가 한 번에 반영됩니다.",
        actions=[cl.Action(
            name="blind_spot_regen",
            label="🔄 답변 다시 생성",
            payload={"query": query, "provider": provider, "model_label": model_label},
        )],
        author="사각지대 알림",
    ).send()


async def _regen_with_material(query: str, provider: str, model_label: str,
                               material: str) -> None:
    """패치/업로드 자료(material)를 주입해 직전 답변을 '완전판'으로 재생성.

    연속 질의 맥락(history+사실표)과 carry(누적 법령·결론)를 함께 넘기고,
    재생성 후 세션 기억을 완전판 기준으로 갱신한다 — API 패치 재생성과
    PDF 직접 첨부 재생성이 공유하는 꼬리."""
    hist_block = _history_context(cl.user_session.get("history", []),
                                  cl.user_session.get("session_facts") or {})
    extra_context = ((hist_block + "\n\n") if hist_block else "") + material

    gen = get_generator()
    session_id = cl.user_session.get("upload_key", "")
    try:
        msg, result = await generate_streaming(
            gen, query, extra_context, session_id, provider, model_label,
            thread_id=_thread_scope(),
            carry_laws=cl.user_session.get("used_laws") or [],
            carry_conclusions=cl.user_session.get("session_conclusions") or [],
        )
    except Exception as e:
        await cl.Message(content=f"재생성 오류: {e}").send()
        return
    if result is None:
        return

    raw_answer  = result.get("answer", "")
    source_info = result.get("source_info", {})
    if not isinstance(source_info, dict):
        source_info = {}

    body, _ = split_answer(raw_answer)
    body, cite_elements = build_citation_elements(body, result)
    msg.content = body
    if cite_elements:
        msg.elements = cite_elements
    await msg.update()

    amendment_text = format_amendment_sources(source_info)
    if amendment_text:
        amendment_text, src_elements = build_citation_elements(amendment_text, result)
        await cl.Message(content=amendment_text, author="입법요지",
                         elements=src_elements or None).send()

    # 재생성 답변은 직전 답변을 대체하는 '완전판' — 세션 기억도 이것으로 갱신.
    # 안 하면 다음 질문의 [이전 대화 맥락]·누적 법령·결론이 불완전판 기준으로 남는다.
    history = cl.user_session.get("history", [])
    if history and history[-1].get("q") == query:
        history[-1]["a"] = _history_answer(body)
    else:
        history.append({"q": query, "a": _history_answer(body)})
    cl.user_session.set("history", history)
    cl.user_session.set("used_laws",
                        _accumulate_used_laws(cl.user_session.get("used_laws"), result))
    cl.user_session.set("session_conclusions",
                        _accumulate_conclusions(cl.user_session.get("session_conclusions"), result))


def _stash_regen_material(query: str, block: str) -> None:
    """캐싱(API 패치)·첨부(PDF)로 확보한 원문을 질문 단위로 적재.

    '답변 다시 생성' 버튼이 같은 질문의 적재분을 모아 한 번에 주입한다."""
    store = cl.user_session.get("regen_material") or {}
    store.setdefault(query, []).append(block)
    cl.user_session.set("regen_material", store)


@cl.action_callback("blind_spot_regen")
async def on_blind_spot_regen(action: cl.Action):
    """'답변 다시 생성' — 캐싱·첨부로 적재된 자료를 모아 한 번에 재생성."""
    payload = action.payload or {}
    query       = payload.get("query", "")
    provider    = payload.get("provider", "gemini")
    model_label = payload.get("model_label", "⚡ Gemini")
    if not query:
        await action.remove()
        await cl.Message(content="재생성 정보가 부족합니다.", author="사각지대 알림").send()
        return

    await action.remove()

    store = cl.user_session.get("regen_material") or {}
    blocks = store.pop(query, [])
    cl.user_session.set("regen_material", store)

    material = ""
    if blocks:
        material = ("=== [캐싱·첨부 자료 — 답변 재생성용] ===\n"
                    "※ 아래는 방금 캐싱(API 패치)·첨부(PDF)로 확보한 사각지대 자료다. "
                    + _REGEN_RULES + "\n\n" + "\n\n".join(blocks))
    else:
        await cl.Message(
            content="적재된 캐싱·첨부 자료가 없어 기존 자료만으로 재생성합니다.",
            author="사각지대 알림",
        ).send()

    await _regen_with_material(query, provider, model_label, material)


# 재생성 공통 '완전판' 지시 — 패치/첨부 자료 주입 헤더에 붙는다
_REGEN_RULES = (
    "이 재생성 답변은 직전 답변을 대체하는 '완전판'이므로 반드시 다음을 지켜라:\n"
    "① 직전 답변에서 다룬 모든 항목(예: 각 시설)을 빠짐없이 포함해 다시 작성한다. "
    "'이미 설명했다'·'중복이다'는 이유로 항목을 생략하거나 답변 범위를 좁히지 마라 "
    "— 직전 대화 맥락의 '반복 금지' 지시는 이 재생성에는 적용되지 않는다.\n"
    "② 아래 자료의 법령은 그것이 적용되는 항목에 본문에서 명시적으로 연결한다 "
    "(예: '어린이집 면적 기준은 「영유아보육법」 제○조의 보육실 면적 기준에 따라 ~').\n"
    "③ 자료에 해당 항목의 기준이 없으면 '해당 법령에서 구체 수치는 확인되지 않음'이라고 밝힌다."
)


@cl.action_callback("blind_spot_pdf_attach")
async def on_blind_spot_pdf_attach(action: cl.Action):
    """사각지대 알림의 'PDF 직접 첨부' — 업로드 캐시에 전역 등록 + 재생성용 적재.

    API 패치의 대안 선택지: API에 없는 자료(지자체 조례 등)나 사용자가 직접
    확보한 원문 PDF를 등록한다. 버튼은 남겨 여러 번 첨부할 수 있고,
    재생성은 '답변 다시 생성' 버튼이 적재분을 모아 한 번에 수행한다."""
    payload = action.payload or {}
    query       = payload.get("query", "")
    provider    = payload.get("provider", "gemini")
    model_label = payload.get("model_label", "⚡ Gemini")

    files = await cl.AskFileMessage(
        content="반영할 법령/자료 PDF를 첨부해주세요 (여러 개 가능).",
        accept=["application/pdf"],
        max_files=5,
        max_size_mb=30,
        timeout=300,
    ).send()
    if not files:
        await cl.Message(content="첨부된 파일이 없습니다.",
                         author="사각지대 알림").send()
        return

    key = cl.user_session.get("upload_key", "")
    gen = get_generator()
    retriever = gen._get_retriever()

    def _index_one(path: str, filename: str):
        law_label = filename.rsplit(".", 1)[0]
        text = parse_pdf(path)
        chunks = chunk_law_pdf(text, law_label)
        retriever.create_session_collection(key)
        n = retriever.index_uploaded_chunks(key, chunks, "")  # thread_id="" → 전역
        return law_label, n, chunks

    registered: list[tuple[str, int, list]] = []
    failed_files: list[str] = []
    for f in files:
        try:
            law_label, n, chunks = await asyncio.to_thread(_index_one, f.path, f.name)
        except Exception:
            n, chunks = 0, []
            law_label = f.name
        if n > 0:
            registered.append((law_label, n, chunks))
        else:
            failed_files.append(f.name)

    result_lines = ["📎 **PDF 등록 결과**"]
    for label, n, _ in registered:
        result_lines.append(f"  · ✓ **{label}** ({n}개 청크, 전역 캐시)")
    for name in failed_files:
        result_lines.append(f"  · ✗ {name} — 텍스트 추출 실패(스캔본 PDF?)")
    regen_actions = []
    if registered and query:
        result_lines.append("\n더 캐싱·첨부할 자료가 있으면 계속 등록하시고, "
                            "**‘🔄 답변 다시 생성’**을 누르면 적재된 자료가 한 번에 반영됩니다.")
        # 재생성 버튼을 이 자리에 노출 — 알림 카드의 버튼은 위로 밀려 찾기 어렵다
        regen_actions.append(cl.Action(
            name="blind_spot_regen",
            label="🔄 답변 다시 생성",
            payload={"query": query, "provider": provider, "model_label": model_label},
        ))
    await cl.Message(content="\n".join(result_lines),
                     actions=regen_actions or None,
                     author="사각지대 알림").send()

    if not registered or not query:
        return

    # 등록 원문을 조 단위로 재생성용 적재 (컨텍스트 상한 내에서)
    blocks = ["[출처: 사용자 직접 첨부 PDF]"]
    budget = 15000
    for label, _, chunks in registered:
        for c in chunks:
            if budget <= 0:
                blocks.append("[이하 생략 — 나머지 조문은 업로드 캐시 검색으로 참조 가능]")
                break
            piece = f"[업로드 원문] 「{c['law_name']}」 {c['article_no']}\n{c['content']}"
            blocks.append(piece)
            budget -= len(piece)
        if budget <= 0:
            break
    _stash_regen_material(query, "\n".join(blocks))


# on_chat_end에서 업로드 컬렉션을 삭제하지 않는다 (영속화):
#   재방문(같은 anon_id) 시 이전 업로드를 재사용하고,
#   30일 이상 미사용분은 startup의 cleanup이 자동 정리한다.
