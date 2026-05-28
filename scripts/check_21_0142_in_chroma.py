#!/usr/bin/env python3
"""법제처 21-0142가 ChromaDB qa_precedents에 인덱싱되어 있는지 확인."""
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import chromadb

client = chromadb.PersistentClient(
    path=str(Path(__file__).parent.parent / "data" / "chroma_db")
)

for col_name in ["qa_precedents", "precedents_2026_april"]:
    try:
        col = client.get_collection(col_name)
    except Exception:
        continue
    # 메타데이터로 직접 조회
    try:
        res = col.get(
            where={"doc_code": "21-0142"},
            include=["metadatas"],
            limit=5,
        )
        ids = res.get("ids", [])
        print(f"[{col_name}] doc_code=21-0142 매칭: {len(ids)}건")
        for i, meta in zip(ids, res.get("metadatas", [])):
            print(f"  - id={i}, doc_ref={meta.get('doc_ref')}, question={meta.get('question','')[:70]}")
    except Exception as e:
        print(f"[{col_name}] 조회 오류: {e}")
