import sys, json
sys.stdout.reconfigure(encoding='utf-8')

import chromadb
from pathlib import Path
from collections import Counter

client = chromadb.PersistentClient(path=str(Path('data/chroma_db')))

# ── 1. law_articles: 법령명별 조문 수 ────────────────────────
col = client.get_collection('law_articles')
total = col.count()
res = col.get(include=['metadatas'], limit=total)

law_counter = Counter()
for meta in res['metadatas']:
    law_counter[meta.get('law_name', '(unknown)')] += 1

print(f"=== law_articles ({total}개 조문) ===")
for law, cnt in sorted(law_counter.items(), key=lambda x: -x[1]):
    print(f"  {cnt:4d}건  {law}")

# ── 2. qa_precedents ──────────────────────────────────────────
try:
    col2 = client.get_collection('qa_precedents')
    total2 = col2.count()
    res2 = col2.get(include=['metadatas'], limit=total2)
    ref_counter = Counter()
    for meta in res2['metadatas']:
        ref = meta.get('doc_ref') or meta.get('doc_code') or meta.get('doc_agency') or '(unknown)'
        ref_counter[ref] += 1
    print(f"\n=== qa_precedents ({total2}개 청크) ===")
    for ref, cnt in sorted(ref_counter.items()):
        print(f"  {cnt:3d}건  {ref}")
except Exception as e:
    print(f"\nqa_precedents: {e}")

# ── 3. precedents_2026_april ──────────────────────────────────
try:
    col3 = client.get_collection('precedents_2026_april')
    total3 = col3.count()
    res3 = col3.get(include=['metadatas'], limit=total3)
    ref_counter3 = Counter()
    for meta in res3['metadatas']:
        ref = meta.get('doc_ref') or meta.get('doc_code') or meta.get('doc_agency') or '(unknown)'
        ref_counter3[ref] += 1
    print(f"\n=== precedents_2026_april ({total3}개 청크) ===")
    for ref, cnt in sorted(ref_counter3.items()):
        print(f"  {cnt:3d}건  {ref}")
except Exception as e:
    print(f"\nprecedents_2026_april: {e}")

# ── 4. memos ──────────────────────────────────────────────────
try:
    col4 = client.get_collection('memos')
    total4 = col4.count()
    res4 = col4.get(include=['metadatas'], limit=total4)
    print(f"\n=== memos ({total4}개) ===")
    for meta in sorted(res4['metadatas'], key=lambda x: x.get('memo_id','')):
        print(f"  [{meta['memo_id']}] {meta['title'][:60]}")
except Exception as e:
    print(f"\nmemos: {e}")
