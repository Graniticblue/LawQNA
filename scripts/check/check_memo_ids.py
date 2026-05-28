import json, sys
sys.stdout.reconfigure(encoding='utf-8')
recs = [json.loads(l) for l in open('data/memos.jsonl', encoding='utf-8') if l.strip()]
ids = sorted(r['memo_id'] for r in recs)
print('현재 메모:', ids)
next_n = max(int(i.split('_')[1]) for i in ids) + 1
print(f'다음 ID: memo_{next_n:03d}')
