import fitz, sys, re
sys.stdout.reconfigure(encoding="utf-8")
doc = fitz.open("add/processed/법제처_22-0411.pdf")
text = ""
for page in doc:
    text += page.get_text("text")
doc.close()
# 섹션 마커 후보 탐색
for pat in ["질의요지", "회답", "이유", "관계 법령", "관계법령"]:
    idx = text.find(pat)
    if idx != -1:
        print(f"[{pat}] 위치={idx}, 앞10자: {repr(text[max(0,idx-10):idx+len(pat)+5])}")
# 날짜 탐색
dates = re.findall(r'\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.', text)
print("날짜 후보:", dates[:5])
