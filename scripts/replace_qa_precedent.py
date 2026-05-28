#!/usr/bin/env python3
"""
qa_precedents 컬렉션에서 특정 doc_code 항목을 삭제하고 manifest에서도 제거.
이후 02_Indexer_BASE.py --collection qa 실행으로 새 enrichment JSONL이 인덱싱됨.

사용: python scripts/replace_qa_precedent.py 24-0241 [21-0142 ...]
"""
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import chromadb

REPO = Path(__file__).parent.parent

if len(sys.argv) < 2:
    print("사용: python scripts/replace_qa_precedent.py <doc_code> [<doc_code> ...]")
    sys.exit(1)

codes = sys.argv[1:]
print(f"교체 대상: {codes}\n")

# 1. ChromaDB에서 해당 doc_code 삭제
client = chromadb.PersistentClient(path=str(REPO / "data/chroma_db"))
for col_name in ["qa_precedents", "precedents_2026_april"]:
    try:
        col = client.get_collection(col_name)
    except Exception:
        continue
    for code in codes:
        res = col.get(where={"doc_code": code}, include=[], limit=100)
        ids = res.get("ids", [])
        if ids:
            col.delete(ids=ids)
            print(f"[{col_name}] doc_code={code}: {len(ids)}건 삭제")

# 2. manifest에서 해당 파일 제거
mp = REPO / "data/qa_precedents/manifest.json"
m = json.load(open(mp, encoding="utf-8"))
before = len(m["indexed"])
m["indexed"] = [
    x for x in m["indexed"]
    if not any(f"법제처_{code}.jsonl" == x["file"] for code in codes)
]
removed = before - len(m["indexed"])
json.dump(m, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\nmanifest: {removed}개 항목 제거")

print("\n→ 다음 명령으로 새 JSONL 인덱싱:")
print("   python pipeline/02_Indexer_BASE.py --collection qa")
