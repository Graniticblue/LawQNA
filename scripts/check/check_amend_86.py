import json, sys
sys.stdout.reconfigure(encoding='utf-8')

with open('data/law_amendments/amendments.jsonl', encoding='utf-8') as f:
    amends = [json.loads(l) for l in f if l.strip()]

print(f"전체 개정이력: {len(amends)}건\n")

# 건축법 시행령 개정이력 전체
hits = [a for a in amends if '건축법 시행령' in a.get('law_name', '')]
print(f"건축법 시행령 개정이력: {len(hits)}건")
for h in hits:
    print(f"  [{h.get('amendment_id')}] {h.get('공포번호')} 시행일:{h.get('시행일')} — {str(h.get('주요내용',''))[:80]}")
