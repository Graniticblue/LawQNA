import sys, json
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

path = Path('data/law_amendments/amendments.jsonl')
records = [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]

for r in records:
    if r['amendment_id'] != '국토계획법시행령_20250701_35628호':
        continue
    for jm in r['조문_변경']:
        if jm['조문'] == '별표21 제1호가목':
            jm['개정전'] = '<신구대조표 미수록 — 연혁 조회 필요>'
            jm['비고'] = '농림지역 단독주택 — 농어업인 요건 폐지, 부지면적 1,000㎡ 미만으로 대체. 누구나 건축 가능. 개정전 원문은 신구대조표 미수록.'
        if jm['조문'] == '별표22 제1호가목':
            jm['개정전'] = '<신구대조표 미수록 — 연혁 조회 필요>'
    break

with open(path, 'w', encoding='utf-8') as f:
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')

print('완료')
