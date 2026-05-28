import fitz, sys, re
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

pdf = Path("data/raw_laws/법령소스/도시 및 주거환경정비법 시행령 별표 (대통령령)(제36220호)(20260324)-2.pdf")
doc = fitz.open(str(pdf))
text = "\n".join(p.get_text("text") for p in doc)
doc.close()

# 별표 구분자 패턴 후보 탐색
print("=== 별표/■ 포함 줄 ===")
for i, line in enumerate(text.splitlines()):
    if '별표' in line or '■' in line:
        print(f"[{i:4d}] {repr(line)}")

print(f"\n총 글자수: {len(text)}")
