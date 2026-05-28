#!/usr/bin/env python3
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).parent.parent
codes = ["24-0241", "14-0171", "13-0246", "20-0156", "20-0535"]
for c in codes:
    p = REPO / f"data/qa_precedents/updates/법제처_{c}.jsonl"
    if not p.exists():
        print(f"{c}: 파일 없음")
        continue
    rec = json.loads(p.read_text(encoding="utf-8").strip())
    q = rec["contents"][0]["parts"][0]["text"]
    rel = rec.get("relation_type", "")
    tags = rec.get("search_tags", "")
    label = rec.get("label_summary", "")
    print(f"\n=== {c} ({rel}) ===")
    print(f"Q: {q[:200].strip()}")
    print(f"tags: {tags[:150]}")
    print(f"label: {label[:200]}")
