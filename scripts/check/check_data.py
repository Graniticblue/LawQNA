import json
with open('data/labeled_with_doc.jsonl', encoding='utf-8') as f:
    for i, line in enumerate(f):
        d = json.loads(line)
        print({k: v for k, v in d.items() if k \!= 'contents'})
        if i >= 2: break
