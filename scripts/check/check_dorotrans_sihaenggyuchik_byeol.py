import fitz, sys, re
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

pdf = Path("data/raw_laws/법령소스/도로교통법 시행규칙 별표 (행정안전부령)(제00615호)(20260402).pdf")
doc = fitz.open(str(pdf))
text = "\n".join(p.get_text("text") for p in doc)
doc.close()

print("=== 앞부분 800자 ===")
print(text[:800])
print("\n=== '별표' 포함 줄 ===")
for line in text.splitlines():
    if re.search(r'■.*별표|^\[별표', line.strip()):
        print(repr(line.strip()[:100]))
