import sys, json
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
path = Path('data/law_amendments/amendments.jsonl')
records = [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]
for r in records:
    if r['amendment_id'] == '건축법_20240627_20424호':
        r['개정전_기준법령'] = '건축법 [시행 2024. 5. 17] [법률 제20194호, 2024. 2. 6, 타법개정]'
        break
with open(path, 'w', encoding='utf-8') as f:
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')
print('완료')
