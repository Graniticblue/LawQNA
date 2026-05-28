import json, sys
sys.stdout.reconfigure(encoding="utf-8")
path = "data/qa_precedents/updates/법제처_22-0411.jsonl"
with open(path, encoding="utf-8") as f:
    rec = json.loads(f.readline())
rec["doc_date"] = "2022-03-10"
rec["doc_ref"]  = "[법제처 2022. 3. 10. 회신 22-0411]"
with open(path, "w", encoding="utf-8") as f:
    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
print("저장 완료:", rec["doc_ref"])
