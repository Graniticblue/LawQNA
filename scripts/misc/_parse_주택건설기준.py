import fitz
import re

pdf_path = "data/raw_laws/주택건설기준 등에 관한 규정(대통령령)(제36220호)(20260324)-1.pdf"
doc = fitz.open(pdf_path)
print(f"총 페이지: {len(doc)}")

# 전체 텍스트 추출
full_text = ""
for i, page in enumerate(doc):
    t = page.get_text("text")
    full_text += t

print(f"총 텍스트 길이: {len(full_text)}")
print("\n=== 첫 3000자 ===")
print(full_text[:3000])
print("\n=== 마지막 1000자 ===")
print(full_text[-1000:])

# 조문 패턴 찾기
articles = re.findall(r'제\d+조(?:의\d+)?', full_text)
unique_arts = list(dict.fromkeys(articles))
print(f"\n발견된 조문: {unique_arts[:50]}")
