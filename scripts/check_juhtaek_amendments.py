#!/usr/bin/env python3
"""주택법 개정연혁이 amendments.jsonl + ChromaDB에 들어가 있는지 확인."""
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import chromadb

REPO = Path(__file__).parent.parent

# 1. amendments.jsonl 확인
path = REPO / "data/law_amendments/amendments.jsonl"
if path.exists():
    recs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"=== amendments.jsonl 총 {len(recs)}건 ===")
    laws = {}
    for r in recs:
        ln = r.get("law_name", "")
        laws[ln] = laws.get(ln, 0) + 1
    for ln, cnt in sorted(laws.items(), key=lambda x: -x[1]):
        print(f"  {cnt:3d}건  {ln}")
    print()
    juhtaek = [r for r in recs if "주택" in r.get("law_name", "")]
    print(f"주택법 관련 레코드: {len(juhtaek)}건")
else:
    print("amendments.jsonl 없음")

# 2. ChromaDB
client = chromadb.PersistentClient(path=str(REPO / "data/chroma_db"))
try:
    col = client.get_collection("law_amendments")
    print(f"\n=== ChromaDB law_amendments 총 {col.count()}건 ===")
    # 주택법 검색
    res = col.get(include=["metadatas"], limit=200)
    juhtaek_chr = [m for m in res.get("metadatas", []) if "주택" in str(m.get("law_name", ""))]
    print(f"주택법 관련: {len(juhtaek_chr)}건")
    for m in juhtaek_chr[:5]:
        print(f"  - {m.get('law_name')} {m.get('시행일', '')} {m.get('공포번호', '')}")
except Exception as e:
    print(f"law_amendments 컬렉션 조회 오류: {e}")
