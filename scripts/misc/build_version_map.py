"""
amendments.jsonl에서 (law_key, 시행일/공포일) 매핑 추출
→ 어떤 키가 all_articles enforcement_date와 일치하는지 확인
"""
import json, sys, re
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
BASE = Path(__file__).parent.parent

# all_articles enforcement_dates
articles_path = BASE / "data/raw_laws/all_articles.jsonl"
law_dates = {}
for line in articles_path.read_text(encoding='utf-8').splitlines():
    if not line.strip(): continue
    obj = json.loads(line)
    key = obj['law_name'].replace(' ', '')
    law_dates[key] = obj.get('enforcement_date', '')

print("=== all_articles 법령별 enforcement_date ===")
for k, v in sorted(law_dates.items()):
    print(f"  {k}: {v}")

# amendments lookup
amend_path = BASE / "data/law_amendments/amendments.jsonl"
records = [json.loads(l) for l in amend_path.read_text(encoding='utf-8').splitlines() if l.strip()]

print("\n=== amendments 매핑 (시행일 키) ===")
amend_map = {}
for r in records:
    aid = r.get("amendment_id", "")
    m = re.match(r'^([^_]+)_(\d{8})_(.+)$', aid)
    if not m: continue
    law_key, enf_date, law_no = m.group(1), m.group(2), m.group(3)
    pub_date = r.get("공포일", "").replace("-", "")
    amend_map[(law_key, enf_date)] = (law_no, pub_date)
    # 공포일도 키로
    if pub_date and pub_date != enf_date:
        amend_map.setdefault((law_key, pub_date), (law_no, pub_date))

print("\n=== all_articles 날짜로 amendments 조회 결과 ===")
for law_name_key, enf in sorted(law_dates.items()):
    info = amend_map.get((law_name_key, enf))
    match = "✓" if info else "✗"
    print(f"  {match} {law_name_key} {enf} → {info}")
