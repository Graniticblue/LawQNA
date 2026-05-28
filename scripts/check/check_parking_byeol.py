import fitz, sys, re
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

pdf = Path("data/raw_laws/법령소스/주차장법 시행령 별표 (대통령령)(제35708호)(20250817).pdf")
doc = fitz.open(str(pdf))
text = "\n".join(p.get_text("text") for p in doc)
doc.close()

print("=== 앞부분 500자 ===")
print(text[:500])
print("\n=== '별표' 포함 줄 ===")
for line in text.splitlines():
    if re.search(r'■.*별표', line.strip()):
        print(repr(line.strip()[:100]))
