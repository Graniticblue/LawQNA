#!/usr/bin/env python3
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

target_ids = {"memo_004", "memo_005", "memo_011", "memo_012", "memo_014", "memo_023"}
path = Path(__file__).parent.parent / "data" / "memos.jsonl"
with open(path, encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        rec = json.loads(line)
        mid = rec.get("memo_id")
        if mid in target_ids:
            print(f'line {i}: {mid} -- {rec.get("title", "")[:60]}')
