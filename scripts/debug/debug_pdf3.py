import fitz, sys, re
sys.stdout.reconfigure(encoding="utf-8")
doc = fitz.open("add/processed/법제처_25-0877.pdf")
text = ""
for page in doc:
    text += page.get_text("text")
doc.close()
# 전체 텍스트에서 날짜 패턴
dates = re.findall(r'\d{4}[.\-]\s*\d{1,2}[.\-]\s*\d{1,2}', text)
print("날짜 후보:", dates[:10])
# 마지막 500자 확인
print("---마지막500자---")
print(text[-500:])
