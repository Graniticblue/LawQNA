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
    return sqlite.stat().st_size < 65536  # 64KB 미만이면 빈 DB

if __name__ == "__main__":
    if chroma_is_empty():
        print(f"[startup] ChromaDB 비어있음 ({CHROMA_DIR}) — 인덱스 빌드 시작...")
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [sys.executable, str(BASE_DIR / "02_Indexer_BASE.py"), "--collection", "all"],
            check=False,
        )
        if result.returncode != 0:
            print("[startup] 경고: 인덱스 빌드 중 오류 발생 (앱은 계속 시작)")
        else:
            print("[startup] 인덱스 빌드 완료")
    else:
        print(f"[startup] ChromaDB 존재 확인 ({CHROMA_DIR}) — 빌드 스킵")
