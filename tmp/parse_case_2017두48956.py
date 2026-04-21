import fitz, sys
sys.stdout.reconfigure(encoding='utf-8')

pdf_path = "판례/대법원 2017두48956 - CaseNote.pdf"
doc = fitz.open(pdf_path)
print(f'총 {doc.page_count}페이지\n')
for i, page in enumerate(doc):
    t = page.get_text()
    print(f'=== {i+1}페이지 ===')
    print(t[:3000])
    print()
doc.close()
