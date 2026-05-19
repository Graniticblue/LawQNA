#!/usr/bin/env python3
"""
chainlit_app.py -- 건축법규 AI 자문 시스템 (Chainlit 인터페이스)
"""

import asyncio
import importlib.util
import json
import queue as _queue
import re
import sys
import threading
from pathlib import Path

import chainlit as cl

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))


# ── Generator 싱글턴 ────────────────────────────────────────

_generator_instance = None


def get_generator():
    global _generator_instance
    if _generator_instance is None:
        spec = importlib.util.spec_from_file_location(
            "generator_mod", BASE_DIR / "06_Generator.py"
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

def chunk_law_pdf(text: str, law_name: str) -> list[dict]:
    pattern = r'(?=제\d+조(?:의\d+)?[\s(（])'
    parts = re.split(pattern, text)
    chunks = []
    for part in parts:
        part = part.strip()
        if not part or len(part) < 20:
            continue
        m = re.match(r'(제\d+조(?:의\d+)?)', part)
        article_no = m.group(1) if m else f"chunk_{len(chunks)}"
        chunks.append({
            "law_name": law_name,
            "article_no": article_no,
            "content": part[:2000],
        })
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
        law_key  = m.group(1)           # "건축법시행령"
        enf_date = m.group(2)           # "20260227"
        law_no   = m.group(3)           # "35717호"
        pub_date = rec.get("공포일", "").replace("-", ".")
        lookup[(law_key, enf_date)] = (law_no, pub_date)
    _amendment_lookup = lookup
    return lookup


def get_law_header(law_name: str, enforcement_date: str) -> str:
    """법령명 + 시행일 → '제35717호 · 공포 2025.08.26 · 시행 2025.08.26' 문자열"""
    lookup = get_amendment_lookup()
    law_key = law_name.replace(" ", "")  # "건축법 시행령" → "건축법시행령"
    info = lookup.get((law_key, enforcement_date))
    edate_str = fmt_date(enforcement_date)
    if info:
        law_no, pub_date = info
        return f"제{law_no} · 공포 {pub_date} · 시행 {edate_str}"
    elif edate_str:
        return f"시행 {edate_str}"
    return ""


# ── content 중복 번호 제거 ────────────────────────────────────

def clean_article_content(text: str) -> str:
    """① ①, 1. 1., 가. 가. 형태 중복 제거"""
    text = re.sub(r'([①-⑳])\s+\1', r'\1', text)
    text = re.sub(r'(\d+\.)\s+\1\s*', r'\1 ', text)
    text = re.sub(r'([가-힣]\.)\s+\1\s*', r'\1 ', text)
    return text


# ── 인라인 인용 마커 파싱 ───────────────────────────────────

def build_citation_elements(answer: str, result: dict) -> tuple[str, list]:
    law_docs  = result.get("law_docs",  [])
    qa_docs   = result.get("qa_docs",   [])
    case_docs = result.get("case_docs", [])

    elements: list = []
    seen: set[str] = set()

    for m in re.finditer(r'\[(법령|해석례|판례)(\d+)\]', answer):
        kind = m.group(1)
        idx  = int(m.group(2)) - 1
        name = f"{kind}{m.group(2)}"

        if name in seen:
            continue
        seen.add(name)

        doc = None
        if kind == "법령"   and 0 <= idx < len(law_docs):
            doc = law_docs[idx]
        elif kind == "해석례" and 0 <= idx < len(qa_docs):
            doc = qa_docs[idx]
        elif kind == "판례"  and 0 <= idx < len(case_docs):
            doc = case_docs[idx]

        if doc is None:
            continue

        edate = doc.metadata.get("enforcement_date", "")
        header_extra = get_law_header(doc.law_name, edate)
        sep = "  ·  " if header_extra else ""
        body = clean_article_content(doc.content)
        content = f"**{doc.law_name}  {doc.article_no}**{sep}{header_extra}\n\n{body}"
        elements.append(cl.Text(name=name, content=content, display="side"))

    return answer, elements


# ── [출처 요약] 분리 ─────────────────────────────────────────

def split_answer(raw: str) -> tuple[str, str]:
    # LLM이 [출처 요약]을 코드펜스(```) 안에 출력하는 경우도 함께 제거
    m = re.search(r'(?:```[^\n]*\n)?\[출처\s*요약\]', raw)
    if m:
        return raw[: m.start()].rstrip(), raw[m.start():]
    return raw, ""


# ── 출처 텍스트 ─────────────────────────────────────────────

def format_sources(source_info: dict) -> str:
    badges = []
    if source_info.get("db_law"):
        badges.append(f"📋 **조문** {source_info['db_law_detail']}")
    if source_info.get("db_qa"):
        badges.append(f"📌 **해석례** {source_info['db_qa_detail']}")
    if source_info.get("db_amendment"):
        badges.append(f"📖 **입법요지** {source_info['db_amendment_detail']}")
    if source_info.get("internal"):
        badges.append(f"💡 **내장지식** {source_info['internal_detail']}")
    return "\n".join(badges)


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

async def generate_streaming(gen, query: str, extra_context: str, session_id: str):
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
            )
        except Exception as e:
            error_holder[0] = e
        finally:
            token_q.put(None)

    thinking_msg = cl.Message(content="분석 중…")
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

    # 스트리밍 완료 확정 (content 교체는 하지 않음)
    await msg.update()
    return msg, result_holder[0], True  # True = streamed


# ── 내장 법령 목록 ───────────────────────────────────────────

LAW_DB_INFO = """\
### 📋 내장 법령 데이터베이스

**건축법 계열** — DB 반영일 2026.04.21 · 개정이력 2018.06 ~ 2026.02 (61건, 시행일 기준)

| 법령 | 현행 시행일 | 개정이력 (시행일 기준) |
|------|-----------|-------------------|
| 건축법 | 2026.02.27 | 2019.01 ~ 2026.02 (18건) |
| 건축법 시행령 | 2025.08.26 | 2018.06 ~ 2026.02 (26건) |
| 건축법 시행규칙 | 2026.02.27 | 2018.06 ~ 2026.02 (17건) |

**국토계획법 계열** — DB 반영일 2026.04.21 · 개정이력 2023.07 ~ 2026.06 (9건, 시행일 기준)

| 법령 | 현행 시행일 | 개정이력 (시행일 기준) |
|------|-----------|-------------------|
| 국토의 계획 및 이용에 관한 법률 | 2025.10.01 | 2024.08 ~ 2026.06 (2건) |
| 국토의 계획 및 이용에 관한 법률 시행령 | 2025.07.01 | 2023.07 ~ 2025.07 (6건) |
| 국토의 계획 및 이용에 관한 법률 시행규칙 | 2025.12.26 | 2024.05 (1건) |

**주택법 계열** — DB 반영일 2026.04.21 · 개정이력 미구축

| 법령 | 현행 시행일 |
|------|-----------|
| 주택법 | 2026.08.04 |
| 주택법 시행령 | 2025.12.30 |
| 주택법 시행규칙 | 2024.08.02 |

**기타 내장 법령** — DB 반영일 2026.04.21 · 개정이력 미구축

건설산업기본법 · 건축물관리법 · 건축물의 피난·방화구조 등의 기준에 관한 규칙 · 건축물의 설비기준 등에 관한 규칙 · 소방시설 설치 및 관리에 관한 법률 · 소방시설 설치 및 관리에 관한 법률 시행령 · 장애인·노인·임산부 등의 편의증진 보장에 관한 법률 · 주택건설기준 등에 관한 규정

---
📌 내장 DB에 없는 법령은 PDF를 첨부하시면 실시간으로 분석에 활용됩니다.\
"""

_LAW_LIST_TRIGGER = "📋 내장 법령 목록"


# ── Chainlit 핸들러 ─────────────────────────────────────────

@cl.set_starters
async def set_starters():
    return [
        cl.Starter(
            label="📋 내장 법령 목록",
            message=_LAW_LIST_TRIGGER,
            icon="/public/starter_list.svg",
        ),
        cl.Starter(
            label="🏗️ 건축허가·신고",
            message="건축허가와 건축신고의 대상 기준과 차이를 알려주세요.",
        ),
        cl.Starter(
            label="🗺️ 용도지역 제한",
            message="용도지역별 건폐율·용적률 기준과 건축 제한을 알려주세요.",
        ),
        cl.Starter(
            label="🔥 피난·방화 기준",
            message="피난계단 및 방화구획 설치 기준을 알려주세요.",
        ),
        cl.Starter(
            label="👷 감리 대상·절차",
            message="건축 감리 대상 건축물과 감리 절차를 알려주세요.",
        ),
    ]


@cl.on_chat_start
async def on_start():
    cl.user_session.set("pdf_list", [])
    cl.user_session.set("pdf_ready", False)
    cl.user_session.set("history", [])

    session_id = cl.context.session.id
    gen = get_generator()
    retriever = gen._get_retriever()
    retriever.create_session_collection(session_id)
    cl.user_session.set("session_id", session_id)


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
    cl.user_session.set("pdf_list", [])
    cl.user_session.set("pdf_ready", False)
    await cl.Message(content="대화 이력이 초기화되었습니다. 새 질의를 입력해 주세요.").send()


@cl.on_message
async def on_message(message: cl.Message):
    # ── 법령 목록 트리거 ──────────────────────────────────────
    if message.content.strip() == _LAW_LIST_TRIGGER:
        await cl.Message(content=LAW_DB_INFO).send()
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

            session_id = cl.user_session.get("session_id", "")

            async def do_index(chunks=chunks, session_id=session_id, msg=indexing_msg, label=law_label):
                gen = get_generator()
                retriever = gen._get_retriever()
                n = await asyncio.to_thread(retriever.index_uploaded_chunks, session_id, chunks)

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

    # 히스토리에서 extra_context 구성
    history = cl.user_session.get("history", [])
    extra_context = ""
    if history:
        lines = []
        for h in history[-3:]:
            lines.append(f"Q: {h['q']}")
            lines.append(f"A: {h['a'][:300]}...")
        extra_context = "\n".join(lines)

    session_id = cl.user_session.get("session_id", "")

    thinking_msg = cl.Message(content="분석 중…")
    await thinking_msg.send()

    try:
        gen = get_generator()
        result = await asyncio.to_thread(
            gen.generate, query, False, extra_context, session_id
        )
    except Exception as e:
        await thinking_msg.remove()
        await cl.Message(content=f"오류가 발생했습니다: {e}").send()
        return

    await thinking_msg.remove()

    raw_answer  = result.get("answer", "")
    source_info = result.get("source_info", {})
    if not isinstance(source_info, dict):
        source_info = {}

    # [출처 요약] 블록 분리
    body, _ = split_answer(raw_answer)

    # 인라인 인용 마커 → cl.Text 요소
    body, cite_elements = build_citation_elements(body, result)

    await cl.Message(content=body, elements=cite_elements).send()

    # 출처 요약 별도 메시지
    sources_text = format_sources(source_info)
    if sources_text:
        await cl.Message(content=f"**출처**\n{sources_text}", author="출처").send()

    # 히스토리 업데이트
    history.append({"q": query, "a": body[:500]})
    cl.user_session.set("history", history)


@cl.on_chat_end
async def on_end():
    session_id = cl.user_session.get("session_id", "")
    if session_id:
        gen = get_generator()
        retriever = gen._get_retriever()
        retriever.delete_session_collection(session_id)
