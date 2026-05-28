import json, sys
sys.stdout.reconfigure(encoding='utf-8')
records = [json.loads(l) for l in open('data/law_amendments/amendments.jsonl', encoding='utf-8').read().splitlines() if l.strip()]
for r in records:
    aid = r.get('amendment_id','')
    if '국토' in aid or '주택' in aid:
        print(f"{aid} | 공포:{r.get('공포일','')} | 시행:{r.get('시행일','')}")
