import sys, json
sys.stdout.reconfigure(encoding='utf-8')

targets = {'memo_005', 'memo_011', 'memo_012'}
with open('data/memos.jsonl', encoding='utf-8') as f:
    for line in f:
        rec = json.loads(line)
        if rec.get('memo_id') in targets:
            print(f"=== {rec['memo_id']} — {rec['title']} ===")
            print(rec['content'])
            print()
