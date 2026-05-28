import fitz, sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

pdf = Path("data/raw_laws/판례소스/[대법원 2009. 4. 23. 선고 2006다81035 판결].pdf")
doc = fitz.open(str(pdf))
text = "\n".join(p.get_text("text") for p in doc)
doc.close()
print(text)
