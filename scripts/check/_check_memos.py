import json
memos = []
with open('data/memos.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if line:
            memos.append(json.loads(line))
print('총', len(memos), '개')
print('마지막 id:', memos[-1].get('id'))
