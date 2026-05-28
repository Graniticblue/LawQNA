import sys, json, time, re
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
import fitz

from ingest_도로교통법시행령 import (
    extract_text, clean_text, parse_byeolpyo,
    ingest_to_chroma, save_jsonl,
    BASE_DIR, PDF_BYEOL
)

text = extract_text(PDF_BYEOL)
byeol = parse_byeolpyo(text)
print(f"별표 {len(byeol)}개 파싱됨")
for a in byeol[:5]:
    print(f"  {a['article_no']}({a['article_title'][:30]}): {a['content'][:50]}...")

if byeol:
    # JSONL에 추가
    out = BASE_DIR / "data/raw_laws/도로교통법시행령_articles.jsonl"
    existing = [json.loads(l) for l in out.read_text(encoding='utf-8').splitlines() if l.strip()]
    all_arts = existing + byeol
    save_jsonl(all_arts, out)
    ingest_to_chroma(byeol)

    # all_articles.jsonl에 추가
    src = "\n".join(json.dumps(a, ensure_ascii=False) for a in byeol) + "\n"
    with open(BASE_DIR / "data/raw_laws/all_articles.jsonl", "a", encoding="utf-8") as f:
        f.write(src)
    total = sum(1 for l in open(BASE_DIR / "data/raw_laws/all_articles.jsonl", encoding="utf-8") if l.strip())
    print(f"all_articles.jsonl 총 레코드: {total}")
