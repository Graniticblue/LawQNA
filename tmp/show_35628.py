import sys, json
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
records = [json.loads(l) for l in Path('data/law_amendments/amendments.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
r = [x for x in records if x['amendment_id'] == '국토계획법시행령_20250701_35628호'][0]
out = Path('tmp/out_35628.json')
out.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding='utf-8')
print('저장 완료:', out)
