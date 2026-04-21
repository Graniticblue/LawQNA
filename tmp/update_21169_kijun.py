import sys, json
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

path = Path('data/law_amendments/amendments.jsonl')
records = [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]
for r in records:
    if r['amendment_id'] == '국토계획법_20260603_21169호':
        r['개정전_기준법령'] = '국토의 계획 및 이용에 관한 법률 [시행 2025. 10. 1] [법률 제21065호, 2025. 10. 1, 타법개정]'
        break
with open(path, 'w', encoding='utf-8') as f:
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')
print('완료')
