import json, sys
sys.stdout.reconfigure(encoding="utf-8")
with open("data/qa_precedents/updates/법제처_25-0877.jsonl", encoding="utf-8") as f:
    rec = json.loads(f.readline())
print("doc_ref:", rec.get("doc_ref"))
print("doc_date:", rec.get("doc_date"))
print("fields:", [k for k in rec.keys() if k != "contents"])
q = rec["contents"][0]["parts"][0]["text"]
print("질의 앞부분:", q[:150])
