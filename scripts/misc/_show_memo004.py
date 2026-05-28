import sys, json
sys.stdout.reconfigure(encoding='utf-8')

with open('data/memos.jsonl', encoding='utf-8') as f:
    for line in f:
        rec = json.loads(line)
        if rec.get('memo_id') == 'memo_004':
            print(f"title: {rec['title']}\n")
            print(rec['content'])
