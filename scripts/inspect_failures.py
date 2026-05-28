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
    if not r["pass"]:
        print(f"=== #{r['id']} ===")
        print(f"query: {r['query'][:80]}")
        print(f"failures: {r['failures']}")
        parsed = r['parsed']
        print(f"parsed.question_type: {parsed.get('question_type')}")
        print(f"parsed.relation_types: {[(rt.get('type'), rt.get('weight')) for rt in parsed.get('relation_types', [])]}")
        print(f"parsed.definition_terms: {parsed.get('definition_terms')}")
        print()
