"""
[별표 6] PDF 텍스트 추출 및 구조 확인
"""
import fitz

pdf_path = "data/raw_laws/[별표 6] 바닥충격음차단성능인정기관 및 바닥충격음성능검사기관의 인력 및 장비 기준(제60조의2제2항 및 제60조의9제1항제2호 관련)(주택건설기준 등에 관한 규정).pdf"
doc = fitz.open(pdf_path)

full_text = ""
for page in doc:
    full_text += page.get_text("text")

with open("_byeolpyo6_raw.txt", "w", encoding="utf-8") as f:
    f.write(f"총 페이지: {len(doc)}\n")
    f.write(f"총 텍스트 길이: {len(full_text)}\n\n")
    f.write(full_text)

print(f"Done. 페이지: {len(doc)}, 길이: {len(full_text)}")
print("Check _byeolpyo6_raw.txt")
