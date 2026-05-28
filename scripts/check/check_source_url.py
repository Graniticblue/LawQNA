import json, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

BASE = Path(__file__).parent.parent
path = BASE / "data/raw_laws/all_articles.jsonl"

seen = set()
for line in path.read_text(encoding='utf-8').splitlines():
    if not line.strip(): continue
    obj = json.loads(line)
    key = obj.get('law_name','') + obj.get('enforcement_date','')
    if key in seen: continue
    seen.add(key)
    print(f"{obj['law_name']} | {obj.get('enforcement_date','')} | {obj.get('source_url','')[:120]}")
