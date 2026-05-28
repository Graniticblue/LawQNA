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
    if r["id"] == 11:
        print("=== #11 Pass 1 원문 ===")
        print(r["pass1_text"])
