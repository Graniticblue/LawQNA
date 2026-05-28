import json, sys, re, fitz
sys.stdout.reconfigure(encoding="utf-8")
# PDF에서 날짜 탐색
doc = fitz.open("add/processed/법제처_25-0853.pdf")
text = "".join(p.get_text("text") for p in doc)
doc.close()
dates = re.findall(r'\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.', text[:800])
print("날짜 후보:", dates[:5])
# JSONL 확인
with open("data/qa_precedents/updates/법제처_25-0853.jsonl", encoding="utf-8") as f:
    r = json.loads(f.readline())
print("doc_ref:", r.get("doc_ref"))
print("doc_date:", r.get("doc_date"))
print("질의 앞80자:", r["contents"][0]["parts"][0]["text"][:80])
