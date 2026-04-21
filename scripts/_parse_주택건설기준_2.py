import fitz
import re
import json
import os

pdf_path = "data/raw_laws/주택건설기준 등에 관한 규정(대통령령)(제36220호)(20260324)-1.pdf"
doc = fitz.open(pdf_path)

# 전체 텍스트 추출
full_text = ""
for page in doc:
    full_text += page.get_text("text")

# 텍스트를 파일로 저장
with open("_주택건설기준_raw.txt", "w", encoding="utf-8") as f:
    f.write(full_text)

with open("_result.txt", "w", encoding="utf-8") as f:
    f.write(f"총 페이지: {len(doc)}\n")
    f.write(f"총 텍스트 길이: {len(full_text)}\n\n")

    # 조문 패턴 찾기
    articles = re.findall(r'제\d+조(?:의\d+)?', full_text)
    unique_arts = list(dict.fromkeys(articles))
    f.write(f"발견된 조문 수: {len(unique_arts)}\n")
    f.write(f"조문 목록: {unique_arts}\n\n")

    # 앞부분
    f.write("=== 첫 2000자 ===\n")
    f.write(full_text[:2000])

print("Done. Check _result.txt")
