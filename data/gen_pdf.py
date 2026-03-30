import json
import os
import re
import subprocess
import time

input_file = r"d:\## Workspace(model4, 0318)\data\extracted_qa.jsonl"
html_file = r"d:\## Workspace(model4, 0318)\data\qa_report.html"
pdf_file = r"d:\## Workspace(model4, 0318)\data\qa_report.pdf"

html_content = [
    "<!DOCTYPE html>",
    "<html>",
    "<head>",
    "<meta charset='utf-8'>",
    "<style>",
    "body { font-family: 'Batang', serif; font-size: 13pt; line-height: 1.8; color: #333; margin: 0; }",
    ".page { page-break-after: always; padding: 15mm 20mm; }",
    ".header-box { background-color: #e9ecef; border-bottom: 2px solid #888; padding: 10px 15px; font-size: 16pt; font-family: 'Malgun Gothic', 'Noto Sans KR', sans-serif; font-weight: bold; margin-bottom: 10px; color: #333; }",
    ".meta-info { text-align: right; font-size: 10pt; color: #666; margin-bottom: 30px; font-family: 'Malgun Gothic', 'Noto Sans KR', sans-serif; }",
    ".section-title { font-size: 15pt; font-weight: bold; border-bottom: 1px solid #333; display: inline-block; padding-bottom: 4px; margin-top: 30px; margin-bottom: 15px; font-family: 'Malgun Gothic', 'Noto Sans KR', sans-serif; }",
    "p { margin: 0 0 10px 0; text-align: justify; word-break: keep-all; }",
    "/* Custom margins for PDF print */",
    "@page { size: A4 portrait; margin: 0mm; }",
    "</style>",
    "</head>",
    "<body>"
]

def extract_title(q):
    # Just try to grab something relevant for the title, fallback to "건축 질의 분석"
    # To mimic the screenshot, maybe we just use a generic title or short suffix if available
    # Actually, scanning for " ~ 여부" or similar ending.
    q = q.strip()
    if q.endswith("여부") or q.endswith("여부.") or q.endswith("여부?"):
        idx = q.rfind("여부")
        start = max(0, idx - 25)
        # try to find first space to avoid partial words
        cand = q[start:idx].strip()
        space_idx = cand.find(" ")
        if space_idx != -1 and start > 0:
            cand = cand[space_idx+1:]
        
        if len(cand) > 3:
            return cand + " 여부"

    # Default fallback
    return "건축 질의에 대한 판단 여부"

with open(input_file, 'r', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line.strip())
        question = data.get("question", "")
        final_answer = data.get("final_answer", "")
        
        title = extract_title(question)
                
        html_content.append("<div class='page'>")
        html_content.append(f"<div class='header-box'>{title}</div>")
        html_content.append("<div class='meta-info'>[국토교통부 질의회신]</div>")
        
        html_content.append("<div class='section-title'>질의</div>")
        html_content.append(f"<p>{question}</p>")
        
        html_content.append("<div class='section-title'>회신</div>")
        for p_ans in final_answer.split('\n'):
            if p_ans.strip():
                # Add bullet check if text contains numbers but no bullets?
                # Just print as paragraphs
                html_content.append(f"<p>{p_ans.strip()}</p>")
                
        html_content.append("</div>")

html_content.append("</body></html>")

with open(html_file, 'w', encoding='utf-8') as f:
    f.write('\n'.join(html_content))

import platform
if platform.system() == 'Windows':
    msedge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    ]
    msedge_exe = None
    for p in msedge_paths:
         if os.path.exists(p):
              msedge_exe = p
              break
    
    if msedge_exe:
        print(f"Found Browser at {msedge_exe}, exporting to PDF...")
        cmd = [
            msedge_exe,
            "--headless",
            "--disable-gpu",
            "--print-to-pdf-no-header",
            f"--print-to-pdf={pdf_file}",
            f"file:///{html_file.replace(chr(92), '/')}"
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proc.wait()
        
        if os.path.exists(pdf_file) and os.path.getsize(pdf_file) > 0:
             print("PDF generated successfully.")
        else:
             print("PDF generation failed or file is empty.")
    else:
        print("Edge/Chrome not found.")
