import json
from pathlib import Path

for f in Path('data/qa_precedents').rglob('*.jsonl'):
    for line in f.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        idx = d.get('_orig_idx')
        if idx in [41, 42]:
            ref = str(d.get('doc_ref', '없음'))[:80]
            tag = str(d.get('tag', ''))[:30]
            print(f.name, 'idx='+str(idx), 'doc_ref='+ref, 'tag='+tag)

print("--- label_summary 검색 ---")
for f in Path('data/qa_precedents').rglob('*.jsonl'):
    for line in f.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        ls = str(d.get('label_summary',''))
        if '지하층' in ls and '지표면' in ls:
            idx = d.get('_orig_idx','?')
            ref = str(d.get('doc_ref','없음'))[:80]
            print(f.name, 'idx='+str(idx), ref)
