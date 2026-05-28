"""DB 안에 실제로 들어있는 법령 데이터 예시 출력"""
import chromadb
from pathlib import Path

client = chromadb.PersistentClient(path='data/chroma_db')

# ── 컬렉션 크기 확인 ──────────────────────────────────────
for name in ['law_articles', 'qa_precedents', 'precedents_2026_april']:
    try:
        col = client.get_collection(name)
        print(f'{name}: {col.count():,}개')
    except Exception as e:
        print(f'{name}: 없음 ({e})')

print()

# ── 1) law_articles: 조문 예시 ────────────────────────────
print("=" * 70)
print("[1] law_articles -- 조문 예시 (is_byeolpyo=false)")
print("=" * 70)
try:
    col = client.get_collection('law_articles')
    res = col.get(limit=3, include=['documents', 'metadatas'],
                  where={"is_byeolpyo": "false"})
    for i, (doc, meta) in enumerate(zip(res['documents'], res['metadatas'])):
        print(f"\n--- 조문 #{i+1} ---")
        print(f"  doc_id       : {res['ids'][i]}")
        print(f"  law_name     : {meta.get('law_name')}")
        print(f"  article_no   : {meta.get('article_no')}")
        print(f"  article_title: {meta.get('article_title')}")
        print(f"  law_type     : {meta.get('law_type')}")
        print(f"  enf_date     : {meta.get('enforcement_date')}")
        print(f"  embed_text   :")
        print("    " + doc[:300].replace('\n', '\n    '))
except Exception as e:
    print(f"오류: {e}")

# ── 2) precedents_2026_april: 청크 A/B/C 예시 ────────────
print()
print("=" * 70)
print("[2] precedents_2026_april -- 청크 A (QA_CORE) 예시")
print("=" * 70)
try:
    col = client.get_collection('precedents_2026_april')
    res = col.get(limit=2, include=['documents', 'metadatas'],
                  where={"chunk_type": "QA_CORE"})
    for i, (doc, meta) in enumerate(zip(res['documents'], res['metadatas'])):
        print(f"\n--- QA_CORE #{i+1} ---")
        print(f"  doc_id       : {res['ids'][i]}")
        print(f"  doc_ref      : {meta.get('doc_ref')}")
        print(f"  doc_date     : {meta.get('doc_date')}")
        print(f"  relation_type: {meta.get('relation_type')}")
        print(f"  relation_name: {meta.get('relation_name')}")
        print(f"  search_tags  : {meta.get('search_tags', '')[:80]}")
        print(f"  embed_text   :")
        print("    " + doc[:400].replace('\n', '\n    '))
except Exception as e:
    print(f"오류: {e}")

print()
print("=" * 70)
print("[3] precedents_2026_april -- 청크 B (REASONING_STEP) 예시")
print("=" * 70)
try:
    col = client.get_collection('precedents_2026_april')
    res = col.get(limit=2, include=['documents', 'metadatas'],
                  where={"chunk_type": "REASONING_STEP"})
    for i, (doc, meta) in enumerate(zip(res['documents'], res['metadatas'])):
        print(f"\n--- REASONING_STEP #{i+1} ---")
        print(f"  doc_id    : {res['ids'][i]}")
        print(f"  doc_ref   : {meta.get('doc_ref')}")
        print(f"  step_role : {meta.get('step_role')}")
        print(f"  step_seq  : {meta.get('step_seq')}")
        print(f"  embed_text:")
        print("    " + doc[:400].replace('\n', '\n    '))
except Exception as e:
    print(f"오류: {e}")

print()
print("=" * 70)
print("[4] precedents_2026_april -- 청크 C (CONCLUSION) 예시")
print("=" * 70)
try:
    col = client.get_collection('precedents_2026_april')
    res = col.get(limit=2, include=['documents', 'metadatas'],
                  where={"chunk_type": "CONCLUSION"})
    for i, (doc, meta) in enumerate(zip(res['documents'], res['metadatas'])):
        print(f"\n--- CONCLUSION #{i+1} ---")
        print(f"  doc_id       : {res['ids'][i]}")
        print(f"  doc_ref      : {meta.get('doc_ref')}")
        print(f"  relation_name: {meta.get('relation_name')}")
        print(f"  label_summary: {meta.get('label_summary', '')[:200]}")
        print(f"  embed_text   :")
        print("    " + doc[:300].replace('\n', '\n    '))
except Exception as e:
    print(f"오류: {e}")
