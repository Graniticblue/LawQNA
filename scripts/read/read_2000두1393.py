import fitz, sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

pdf_dir = Path("data/raw_laws/판례소스")
for pdf in sorted(pdf_dir.glob("*2000두1393*")):
    print(f"=== {pdf.name} ===")
    doc = fitz.open(str(pdf))
    text = "\n".join(p.get_text("text") for p in doc)
    doc.close()
    print(text)
