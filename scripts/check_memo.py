import json
with open('data/memos.jsonl', 'r', encoding='utf-8') as f:
    memos = [json.loads(l) for l in f if l.strip()]
last = memos[-1]
print('memo_id:', last['memo_id'])
print('title:', last['title'])

