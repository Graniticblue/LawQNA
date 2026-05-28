import sys, re, fitz
sys.stdout.reconfigure(encoding="utf-8")
doc = fitz.open("add/processed/법제처_25-0853.pdf")
text = "".join(p.get_text("text") for p in doc)
doc.close()
dates = re.findall(r'\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.', text)
print("전체 날짜 후보:", dates[:10])
print("--- 마지막 300자 ---")
print(text[-300:])
