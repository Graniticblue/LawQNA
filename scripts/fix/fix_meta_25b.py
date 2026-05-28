import json, sys
sys.stdout.reconfigure(encoding="utf-8")
path = "data/qa_precedents/updates/법제처_25-0853.jsonl"
with open(path, encoding="utf-8") as f:
    rec = json.loads(f.readline())
rec["doc_date"] = "2025-12-17"
rec["doc_ref"]  = "[법제처 2025. 12. 17. 회신 25-0853]"
with open(path, "w", encoding="utf-8") as f:
    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
print("저장 완료:", rec["doc_ref"])
