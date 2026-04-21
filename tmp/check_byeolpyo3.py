import sys
sys.stdout.reconfigure(encoding='utf-8')
import chromadb

client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('law_articles')

# 국토계획법 시행규칙 관련 별표 검색
r = col.get(include=["documents", "metadatas"])
docs = r['documents']
metas = r['metadatas']

# 국토계획법 시행규칙 청크만 필터
규칙_chunks = [(d, m) for d, m in zip(docs, metas)
               if '시행규칙' in m.get('law_name', '') and '국토' in m.get('law_name', '')]
print(f"국토계획법 시행규칙 청크: {len(규칙_chunks)}개")
for doc, meta in 규칙_chunks:
    print(f"  조문: {meta.get('article_no')} | {meta.get('article_title')} | is_byeolpyo={meta.get('is_byeolpyo')}")

# 별표1의2, 별표2 명시 검색 (시행규칙 전체 포함)
print("\n--- '별표 1의2' 단어 포함 (시행규칙 한정) ---")
for doc, meta in 규칙_chunks:
    if '별표 1의2' in doc or '별표1의2' in doc:
        print(f"  {meta.get('article_no')}: {doc[:400]}")
        print()

print("\n--- '별표 2' 단어 포함 (시행규칙 한정) ---")
for doc, meta in 규칙_chunks:
    if '별표 2' in doc or '별표2' in doc:
        print(f"  {meta.get('article_no')}: {doc[:400]}")
        print()
