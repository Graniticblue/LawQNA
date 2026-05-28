#!/usr/bin/env python3
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

path = Path(__file__).parent.parent / "tests" / "pass1_results_2026-05-28.json"
with open(path, encoding="utf-8") as f:
    data = json.load(f)

for r in data["results"]:
    if r["id"] in (6, 7):
        rels = r["parsed"].get("relation_types", [])
        top = max(rels, key=lambda x: x.get("weight", 0)) if rels else {}
        print(f"[{r['id']}] {r['query'][:60]}")
        print(f"  top relation: {top.get('type')} (weight={top.get('weight')})")
        print(f"  reason: {top.get('reason', '')[:140]}")
        print(f"  law_hints: {r['parsed'].get('law_hints', [])}")
        print()
