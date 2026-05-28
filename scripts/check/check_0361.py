import json, sys
sys.stdout.reconfigure(encoding="utf-8")
with open("data/qa_precedents/updates/법제처_22-0361.jsonl", encoding="utf-8") as f:
    r = json.loads(f.readline())
print("doc_ref:", r.get("doc_ref"))
print("doc_date:", r.get("doc_date"))
print("질의 앞200자:", r["contents"][0]["parts"][0]["text"][:200])
print("---회답---")
print(r["contents"][1]["parts"][0]["text"][:200])
print("doc_analysis:", bool(r.get("doc_analysis")))
