import fitz, sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

pdf = Path("data/raw_laws/법령소스/도시 및 주거환경정비법 시행규칙 별표 (국토교통부령)(제01561호)(20260211)-1.pdf")
doc = fitz.open(str(pdf))
text = "\n".join(p.get_text("text") for p in doc)
doc.close()
print(text[:2000])
