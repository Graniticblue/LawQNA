import fitz, sys, re
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

pdf = Path("data/raw_laws/법령소스/공공주택 특별법 시행규칙 별표 (국토교통부령)(제01552호)(20251229).pdf")
doc = fitz.open(str(pdf))
text = "\n".join(p.get_text("text") for p in doc)
doc.close()
print(text[:300])
print("\n=== 별표 패턴 ===")
for line in text.splitlines():
    if re.search(r'■.*별표', line.strip()):
        print(repr(line.strip()[:100]))
