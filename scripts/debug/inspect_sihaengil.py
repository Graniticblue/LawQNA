import json, sys, re
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(__file__).parent.parent

amend_path = BASE / "data/law_amendments/amendments.jsonl"
records = [json.loads(l) for l in amend_path.read_text(encoding="utf-8").splitlines() if l.strip()]

by_law = defaultdict(list)
for r in records:
    aid = r.get("amendment_id", "")
    prefix = re.match(r"^([^_]+)", aid)
    law_key = prefix.group(1) if prefix else "기타"
    sdate = r.get("시행일", "") or r.get("공포일", "")
    by_law[law_key].append(sdate)

print("=== 시행일 기준 ===")
for law in sorted(by_law.keys()):
    dates = sorted(d for d in by_law[law] if d)
    print(f"  {law}: {dates[0]} ~ {dates[-1]}  ({len(dates)}건)")
