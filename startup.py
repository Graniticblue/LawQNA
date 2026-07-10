#!/usr/bin/env python3
"""
startup.py -- Railway 첫 배포 시 ChromaDB 자동 빌드

CHROMA_DB_PATH 환경변수가 가리키는 디렉토리가 비어있으면
02_Indexer_BASE.py의 전체 빌드 로직을 실행한다.
이미 데이터가 있으면 즉시 종료 (재시작 시 불필요한 재인덱싱 방지).
"""
import os
import sys
import subprocess
from pathlib import Path

BASE_DIR   = Path(__file__).parent
CHROMA_DIR = Path(os.environ.get("CHROMA_DB_PATH", str(BASE_DIR / "data" / "chroma_db")))

def chroma_is_empty() -> bool:
    sqlite = CHROMA_DIR / "chroma.sqlite3"
    if not sqlite.exists():
        return True
    if sqlite.stat().st_size < 65536:
        return True
    # 파일이 있어도 law_articles 컬렉션이 실제로 비어있으면 재인덱싱
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        col = client.get_or_create_collection("law_articles")
        return col.count() == 0
    except Exception:
        return True

_CHAT_HISTORY_DDL = """
CREATE TABLE IF NOT EXISTS users (
    "id" UUID PRIMARY KEY,
    "identifier" TEXT NOT NULL UNIQUE,
    "metadata" JSONB NOT NULL,
    "createdAt" TEXT
);
CREATE TABLE IF NOT EXISTS threads (
    "id" UUID PRIMARY KEY,
    "createdAt" TEXT,
    "name" TEXT,
    "userId" UUID,
    "userIdentifier" TEXT,
    "tags" TEXT[],
    "metadata" JSONB,
    FOREIGN KEY ("userId") REFERENCES users("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS steps (
    "id" UUID PRIMARY KEY,
    "name" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "threadId" UUID NOT NULL,
    "parentId" UUID,
    "streaming" BOOLEAN NOT NULL,
    "waitForAnswer" BOOLEAN,
    "isError" BOOLEAN,
    "metadata" JSONB,
    "tags" TEXT[],
    "input" TEXT,
    "output" TEXT,
    "createdAt" TEXT,
    "command" TEXT,
    "start" TEXT,
    "end" TEXT,
    "generation" JSONB,
    "showInput" TEXT,
    "language" TEXT,
    "indent" INT,
    "defaultOpen" BOOLEAN,
    "modes" JSONB,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS elements (
    "id" UUID PRIMARY KEY,
    "threadId" UUID,
    "type" TEXT,
    "url" TEXT,
    "chainlitKey" TEXT,
    "name" TEXT NOT NULL,
    "display" TEXT,
    "objectKey" TEXT,
    "size" TEXT,
    "page" INT,
    "language" TEXT,
    "forId" UUID,
    "mime" TEXT,
    "props" JSONB,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS feedbacks (
    "id" UUID PRIMARY KEY,
    "forId" UUID NOT NULL,
    "threadId" UUID NOT NULL,
    "value" INT NOT NULL,
    "comment" TEXT,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);
"""


def ensure_chat_history_schema():
    """Chainlit 대화 영속성용 5개 테이블을 생성(이미 있으면 무시).
    DATABASE_URL이 없으면(로컬 등) 조용히 생략한다."""
    url = (os.environ.get("DATABASE_URL", "") or "").strip()
    if not url:
        print("[startup] DATABASE_URL 없음 — chat history 스키마 생략")
        return
    # asyncpg.connect는 순수 postgres(ql):// 만 받음
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://"):]
    try:
        import asyncio
        import asyncpg
    except ImportError:
        print("[startup] asyncpg 미설치 — chat history 스키마 생략")
        return

    async def _run():
        conn = await asyncpg.connect(url)
        try:
            await conn.execute(_CHAT_HISTORY_DDL)
        finally:
            await conn.close()

    try:
        asyncio.run(_run())
        print("[startup] chat history 스키마 확인/생성 완료")
    except Exception as e:
        print(f"[startup] chat history 스키마 생성 실패(앱은 계속): {e}")


def cleanup_uploads(days: int = 30):
    """업로드 PDF 컬렉션 정리: N일 이상 미사용 upload_* + 레거시 session_* 삭제.
    영속화로 on_chat_end 삭제를 없앤 대신, 기동 시 1회 orphan/만료분을 정리한다."""
    from datetime import datetime, timedelta
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        cutoff = datetime.now() - timedelta(days=days)
        n = 0
        for c in client.list_collections():
            nm = c.name
            if nm.startswith("session_"):          # 영속화 이전 레거시
                client.delete_collection(nm); n += 1
            elif nm.startswith("upload_"):
                lu = (c.metadata or {}).get("last_used", "")
                try:
                    if lu and datetime.fromisoformat(lu) < cutoff:
                        client.delete_collection(nm); n += 1
                except Exception:
                    pass
        print(f"[startup] 업로드 컬렉션 정리: {n}개 삭제 (미사용 {days}일 초과/레거시)")
    except Exception as e:
        print(f"[startup] 업로드 정리 생략(앱 계속): {e}")


def _split_article_hangs(article_no: str, content: str) -> list:
    """조 텍스트를 항 단위로 분할 — chainlit chunk_law_pdf와 동일 규칙.
    다항 조문이 한 청크로 임베딩되면 max_seq_length에 뒷항이 잘려 검색 누락되므로."""
    import re
    HANG = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚"
    positions = [(m.start(), m.group()) for m in re.finditer(f"[{HANG}]", content)]
    if len(positions) < 2:
        return [(article_no, content)]
    out = []
    for i, (pos, marker) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(content)
        htext = content[pos:end].strip()
        if len(htext) > 3:
            out.append((f"{article_no} {marker}", htext))
    return out


def index_region_packs():
    """내장 지역 조례 팩(ingest/region_packs/*.json) → region_ordinances 컬렉션.

    팩의 (지역, 법규명 집합)이 컬렉션과 일치하면 스킵 — 평시 부팅은 메타 확인만.
    구성이 바뀌면 컬렉션 전체를 재적재한다(지역별 증분 add는 HNSW search_ef
    recall 함정이 있어 전량 재빌드가 안전). 임베딩은 검색과 동일 모델."""
    packs_dir = BASE_DIR / "ingest" / "region_packs"
    if not packs_dir.exists():
        return
    import json
    packs = []
    for pf in sorted(packs_dir.glob("*.json")):
        try:
            p = json.loads(pf.read_text(encoding="utf-8"))
            if p.get("region") and p.get("laws"):
                packs.append(p)
        except Exception as e:
            print(f"[startup] 지역 팩 파싱 실패({pf.name}): {e}")
    if not packs:
        return
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        col = client.get_or_create_collection(
            "region_ordinances", metadata={"hnsw:space": "cosine"})
        state: dict = {}
        if col.count():
            for m in col.get(include=["metadatas"], limit=200000)["metadatas"]:
                state.setdefault(m.get("region", ""), set()).add(m.get("law_name", ""))
        expected = {p["region"]: set(p["laws"].keys()) for p in packs}
        if {r: s for r, s in state.items() if s} == expected:
            total = sum(len(s) for s in expected.values())
            print(f"[startup] 지역 조례 팩 최신 — 스킵 ({len(expected)}개 지역, {total}건)")
            return

        print(f"[startup] 지역 조례 팩 인덱싱 시작 ({len(packs)}개 지역)…")
        try:
            client.delete_collection("region_ordinances")
        except Exception:
            pass
        col = client.get_or_create_collection(
            "region_ordinances", metadata={"hnsw:space": "cosine"})

        from llama_index.embeddings.huggingface import HuggingFaceEmbedding
        embed = HuggingFaceEmbedding(model_name="jhgan/ko-sroberta-multitask")

        for p in packs:
            region = p["region"]
            ids, texts, metas = [], [], []
            i = 0
            for ln, info in p["laws"].items():
                for art_no, content in (info.get("articles") or {}).items():
                    for a_no, text in _split_article_hangs(art_no, str(content)):
                        ids.append(f"region::{region}::{i}")
                        i += 1
                        texts.append(text[:6000])
                        metas.append({
                            "law_name": ln,
                            "article_no": a_no,
                            "source": "region",
                            "region": region,
                            "is_ordinance": "true",
                        })
            B = 64
            for s in range(0, len(ids), B):
                embs = [embed.get_text_embedding(t) for t in texts[s:s + B]]
                col.add(ids=ids[s:s + B], embeddings=embs,
                        documents=texts[s:s + B], metadatas=metas[s:s + B])
            print(f"[startup] 지역 조례 팩 '{region}': 법규 {len(p['laws'])}건, 청크 {len(ids)}개 인덱싱 완료")
    except Exception as e:
        print(f"[startup] 지역 팩 인덱싱 생략(앱 계속): {e}")


if __name__ == "__main__":
    ensure_chat_history_schema()
    cleanup_uploads()
    # FORCE_REINDEX=1 이면 기존 DB가 있어도 삭제 후 재빌드한다.
    # (임베딩 방식 변경 등으로 영구 볼륨의 DB를 갱신해야 할 때 사용.
    #  재빌드 후에는 이 변수를 제거해야 재시작마다 재빌드되지 않는다.)
    force = os.environ.get("FORCE_REINDEX", "").strip().lower() in ("1", "true", "yes")
    # REINDEX_AUX=1 이면 law_articles(수분 소요)는 그대로 두고 개정이력·메모·원칙만
    # 재인덱싱한다. 개정이력(amendments)만 바뀐 경우 전체 재빌드(15분+, 헬스체크 타임아웃
    # 위험) 대신 이걸 쓴다. 완료 후 변수 제거.
    aux_only = os.environ.get("REINDEX_AUX", "").strip().lower() in ("1", "true", "yes")
    # REINDEX_QA=1 이면 qa_precedents(해석례·질의회신)만 전량 재빌드한다.
    # law_articles(13분+)는 그대로 둬 헬스체크 타임아웃을 피하고, 증분 add 대신
    # --reset 전량 재빌드라 HNSW search_ef 누락 함정도 없다.
    # updates/ 폴더에 새 질의회신 jsonl을 추가했을 때 사용. 완료 후 변수 제거.
    qa_only = os.environ.get("REINDEX_QA", "").strip().lower() in ("1", "true", "yes")

    def _index_aux():
        # 02_Indexer는 law_articles·qa_precedents만 만든다. 개정이력·메모·원칙은 별도 스크립트.
        for label, script in [
            ("개정이력(law_amendments)", BASE_DIR / "scripts" / "misc" / "index_amendments_chroma.py"),
            ("메모(memos)",             BASE_DIR / "ingest" / "ingest_memos.py"),
            ("원칙(principles)",        BASE_DIR / "ingest" / "ingest_principles.py"),
        ]:
            if not script.exists():
                print(f"[startup] {label}: 스크립트 없음 — 건너뜀")
                continue
            r = subprocess.run([sys.executable, str(script)], check=False)
            print(f"[startup] {label} 인덱싱 {'완료' if r.returncode == 0 else '실패(앱은 계속)'}")

    if force or chroma_is_empty():
        if force:
            import shutil
            if CHROMA_DIR.exists():
                print(f"[startup] FORCE_REINDEX 설정됨 — 기존 ChromaDB 삭제: {CHROMA_DIR}")
                shutil.rmtree(CHROMA_DIR, ignore_errors=True)
            # manifest 삭제: 없으면 02_Indexer가 SKIP 없이 해석례를 전체 재인덱싱한다.
            # (chroma_db만 지우고 manifest를 남기면 qa_precedents가 전부 SKIP되어 빈 채로 남음)
            for _mf in (BASE_DIR / "data" / "qa_precedents" / "manifest.json",
                        BASE_DIR / "data" / "qa_precedents" / "manifest_법제처.json"):
                if _mf.exists():
                    _mf.unlink()
                    print(f"[startup] manifest 삭제: {_mf.name}")
        print(f"[startup] ChromaDB 인덱스 빌드 시작 ({CHROMA_DIR})...")
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [sys.executable, str(BASE_DIR / "pipeline" / "02_Indexer_BASE.py"), "--collection", "all"],
            check=False,
        )
        if result.returncode != 0:
            print("[startup] 경고: 인덱스 빌드 중 오류 발생 (앱은 계속 시작)")
        else:
            print("[startup] 인덱스 빌드 완료")

        # FORCE_REINDEX로 chroma를 비웠으면 개정이력·메모·원칙도 함께 재인덱싱(안 하면 누락).
        _index_aux()
    elif aux_only:
        print("[startup] REINDEX_AUX 설정됨 — law_articles 유지, 개정이력·메모·원칙만 재인덱싱")
        _index_aux()
    elif qa_only:
        print("[startup] REINDEX_QA 설정됨 — law_articles 유지, qa_precedents만 전량 재빌드")
        r = subprocess.run(
            [sys.executable, str(BASE_DIR / "pipeline" / "02_Indexer_BASE.py"),
             "--collection", "qa", "--reset"],
            check=False,
        )
        print(f"[startup] qa_precedents 재빌드 {'완료' if r.returncode == 0 else '실패(앱은 계속)'}")
    else:
        print(f"[startup] ChromaDB 존재 확인 ({CHROMA_DIR}) — 빌드 스킵")

    # 내장 지역 조례 팩 — 본 빌드 뒤에 실행 (FORCE_REINDEX로 지워져도 여기서 복구)
    index_region_packs()
