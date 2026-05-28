import fitz, sys, re
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

pdf = Path("data/raw_laws/법령소스/도로교통법 시행령 별표 (대통령령)(제35387호)(20260319).pdf")
doc = fitz.open(str(pdf))
text = "\n".join(p.get_text("text") for p in doc)
doc.close()

# 앞부분 + 별표 패턴 찾기
print("=== 텍스트 샘플 (1000자) ===")
print(text[500:1500])
print("\n=== '별표' 포함 줄 ===")
for line in text.splitlines():
    if re.search(r'별표|別表|\[별표', line):
        print(repr(line[:100]))
