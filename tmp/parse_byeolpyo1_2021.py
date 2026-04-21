import fitz, sys
sys.stdout.reconfigure(encoding='utf-8')
pdf_path = r'C:\Users\605\.claude\projects\d-----Workspace-model4--April-\027ae9ca-0d8f-4573-afea-2c5a28211e1f\tool-results\webfetch-1776235851938-dewbpu.pdf'
pdf = fitz.open(pdf_path)
for page in pdf:
    t = page.get_text()
    if '다중주택' in t or '나목' in t:
        print(t[:4000])
        break
pdf.close()
