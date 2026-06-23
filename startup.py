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


if __name__ == "__main__":
    ensure_chat_history_schema()
    # FORCE_REINDEX=1 이면 기존 DB가 있어도 삭제 후 재빌드한다.
    # (임베딩 방식 변경 등으로 영구 볼륨의 DB를 갱신해야 할 때 사용.
    #  재빌드 후에는 이 변수를 제거해야 재시작마다 재빌드되지 않는다.)
    force = os.environ.get("FORCE_REINDEX", "").strip().lower() in ("1", "true", "yes")

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
    else:
        print(f"[startup] ChromaDB 존재 확인 ({CHROMA_DIR}) — 빌드 스킵")
