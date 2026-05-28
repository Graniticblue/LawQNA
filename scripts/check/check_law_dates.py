import json
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).parent.parent

# 1. 개정이력 파일
records = []
with open(BASE / "data/law_amendments/amendments.jsonl", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            records.append(json.loads(line))

law_amend = defaultdict(list)
for r in records:
    law = r.get("법령명", "")
    date = r.get("공포일", "") or ""
    sdate = r.get("시행일", "") or ""
    law_amend[law].append({
        "공포일": date,
        "시행일": sdate,
        "법령호": r.get("법령호", ""),
    })

print("=== 개정이력 (amendments.jsonl) ===")
for law in sorted(law_amend.keys()):
    items = law_amend[law]
    dates = sorted([x["공포일"] for x in items if x["공포일"]])
    sdates = sorted([x["시행일"] for x in items if x["시행일"]])
    oldest = dates[0] if dates else "?"
    newest = dates[-1] if dates else "?"
    print(f"  {law}: {oldest} ~ {newest}  ({len(items)}건)")

# 2. 법령 조문 DB (JSONL)
print("\n=== 조문 DB ===")
law_articles = defaultdict(list)
jsonl_path = BASE / "data" / "law_articles.jsonl"
if not jsonl_path.exists():
    # 다른 경로 시도
    for p in BASE.glob("data/**/*.jsonl"):
        if "article" in p.name.lower() or "law" in p.name.lower():
            print(f"  후보 파일: {p}")
else:
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            law_name = obj.get("law_name", obj.get("법령명", ""))
            pub = obj.get("공포일", obj.get("promulgation_date", ""))
            eff = obj.get("시행일", obj.get("effective_date", ""))
            law_articles[law_name].append({"공포일": pub, "시행일": eff})

for law in sorted(law_articles.keys()):
    items = law_articles[law]
    pubs = sorted(set(x["공포일"] for x in items if x["공포일"]))
    effs = sorted(set(x["시행일"] for x in items if x["시행일"]))
    print(f"  {law}")
    print(f"    공포일: {pubs}")
    print(f"    시행일: {effs}")
    print(f"    조문수: {len(items)}")
