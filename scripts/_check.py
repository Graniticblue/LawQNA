import json, sys
sys.stdout.reconfigure(encoding="utf-8")
path = "data/qa_precedents/updates/법제처_14-0840.jsonl"
with open(path, encoding="utf-8") as f:
    rec = json.loads(f.readline())
fields = [k for k in rec.keys() if k != "contents"]
print("저장된 필드:", fields)
print("doc_analysis 있음:", "doc_analysis" in rec)
print("relation_type:", rec.get("relation_type", "없음"))
print("logic_steps 수:", len(rec.get("logic_steps", [])))
