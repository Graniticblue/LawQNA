import fitz, sys
sys.stdout.reconfigure(encoding="utf-8")
doc = fitz.open("add/processed/법제처_25-0877.pdf")
text = ""
for page in doc:
    text += page.get_text("text")
doc.close()
print(repr(text[:500]))
print("---")
print(text[:2000])
