import json
with open('data/qa_precedents/updates/법제처_15-0688.jsonl', 'r', encoding='utf-8') as f:
    content = f.read().strip()
try:
    obj = json.loads(content)
    print("OK")
    print("doc_code:", obj['doc_code'])
    print("relation_type:", obj['relation_type'])
    print("logic_steps:", len(obj['logic_steps']))
except Exception as e:
    print("ERROR:", e)
