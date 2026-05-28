import fitz, sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

already_done = {"2006", "2017두73693", "2001두10400", "2021두38932", "99두592", "2003두6382"}
pdf_dir = Path("data/raw_laws/판례소스")
for pdf in sorted(pdf_dir.glob("*.pdf")):
    if any(d in pdf.name for d in already_done):
        continue
    print(f"=== {pdf.name} ===")
    doc = fitz.open(str(pdf))
    text = "\n".join(p.get_text("text") for p in doc)
    doc.close()
    print(text)
