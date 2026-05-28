#!/usr/bin/env python3
"""24-0241이 DB·manifest에 어떻게 들어가 있는지 확인."""
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import chromadb

REPO = Path(__file__).parent.parent

# 1. manifest 확인
m = json.load(open(REPO / "data/qa_precedents/manifest.json", encoding="utf-8"))
print("=== manifest 24-0241 항목 ===")
for x in m["indexed"]:
    if "24-0241" in x["file"]:
        print(f"  {x}")

# 2. ChromaDB에서 doc_code=24-0241 검색
client = chromadb.PersistentClient(path=str(REPO / "data/chroma_db"))
for col_name in ["qa_precedents", "precedents_2026_april"]:
    try:
        col = client.get_collection(col_name)
    except Exception:
        continue
    res = col.get(where={"doc_code": "24-0241"}, include=["metadatas"], limit=10)
    print(f"\n=== {col_name} doc_code=24-0241 ===")
    for i, meta in zip(res.get("ids", []), res.get("metadatas", [])):
        print(f"  id={i}")
        print(f"    question: {meta.get('question', '')[:80]}")
        print(f"    source_file: {meta.get('source_file', '')}")
