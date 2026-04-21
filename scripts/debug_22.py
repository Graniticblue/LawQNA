import fitz, sys
sys.stdout.reconfigure(encoding="utf-8")
doc = fitz.open("add/processed/법제처_22-0411.pdf")
text = ""
for page in doc:
    text += page.get_text("text")
doc.close()
print(text[:800])
