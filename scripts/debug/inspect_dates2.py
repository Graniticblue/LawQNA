import json, sys
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(__file__).parent.parent

# ── all_articles.jsonl: 법령별 enforcement_date 확인 ──
aa = BASE / "data/raw_laws/all_articles.jsonl"
by_law = defaultdict(lambda: {"enforcement_dates": set(), "count": 0})

for line in aa.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    obj = json.loads(line)
    name = obj.get("law_name", "")
    edate = obj.get("enforcement_date", "")
    by_law[name]["count"] += 1
    if edate:
        by_law[name]["enforcement_dates"].add(edate)

print("=== 조문 DB (all_articles.jsonl) ===")
for law in sorted(by_law.keys()):
    info = by_law[law]
    dates = sorted(info["enforcement_dates"])
    print(f"  {law}: 조문 {info['count']}개 | 시행일: {dates}")

# ── amendments.jsonl: amendment_id 패턴으로 법령 유추 ──
amend_path = BASE / "data/law_amendments/amendments.jsonl"
records = [json.loads(l) for l in amend_path.read_text(encoding="utf-8").splitlines() if l.strip()]

print(f"\n=== amendments.jsonl: amendment_id 샘플 ===")
for r in records[:10]:
    aid = r.get("amendment_id", "")
    pub = r.get("공포일", "")
    sdate = r.get("시행일", "")
    ct = r.get("조문_변경", [])
    laws = list(set(c.get("법령명", "") for c in ct if isinstance(c, dict)))
    print(f"  {aid} | 공포:{pub} | 시행:{sdate} | 법령:{laws[:2]}")
