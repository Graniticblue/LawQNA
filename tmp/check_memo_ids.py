import sys, json
sys.stdout.reconfigure(encoding='utf-8')
with open('data/memos.jsonl', encoding='utf-8') as f:
    ids = [json.loads(l)['memo_id'] for l in f if l.strip()]
print('현재 메모:', ids)
print('다음 ID: memo_{:03d}'.format(int(ids[-1].split('_')[1])+1))
