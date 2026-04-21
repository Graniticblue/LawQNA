import fitz, sys, re
sys.stdout.reconfigure(encoding="utf-8")
doc = fitz.open("add/processed/법제처_25-0877.pdf")
text = ""
for page in doc:
    text += page.get_text("text")
doc.close()
# 날짜 패턴 검색
dates = re.findall(r'\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.', text[:500])
print("날짜 후보:", dates)
# 코드/날짜 패턴
codes = re.findall(r'\[[\d\-]+,\s*[\d\.\s]+,\s*[^\]]+\]', text[:1000])
print("메타 블록:", codes)
print("---앞200자---")
print(text[:200])
