import fitz, sys
sys.stdout.reconfigure(encoding='utf-8')

pdf_path = "판례/대법원 2017두48956 - CaseNote.pdf"
doc = fitz.open(pdf_path)

# 방법 1: blocks 방식
print('=== blocks 방식 ===')
for i, page in enumerate(doc):
    blocks = page.get_text("blocks")
    for b in blocks:
        text = b[4].strip()
        if text and text not in ['㎡', '①', '②', '③', '④', '⑤']:
            print(f'[p{i+1}] {text[:200]}')

doc.close()
