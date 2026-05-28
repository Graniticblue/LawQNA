import fitz, sys, re
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

pdf = Path("data/raw_laws/법령소스/공공주택 특별법 시행령 별표 (대통령령)(제36258호)(20260414).pdf")
doc = fitz.open(str(pdf))
text = "\n".join(p.get_text("text") for p in doc)
doc.close()
print(text[:300])
print("\n=== 별표 패턴 ===")
for line in text.splitlines():
    if re.search(r'■.*별표', line.strip()):
        print(repr(line.strip()[:100]))
