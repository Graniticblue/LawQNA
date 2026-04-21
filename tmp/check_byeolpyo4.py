import sys
sys.stdout.reconfigure(encoding='utf-8')
import chromadb

client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('law_articles')

# 시행규칙 별표 청크 (is_byeolpyo=true)
r = col.get(where={"$and": [{"law_name": {"$eq": "국토의 계획 및 이용에 관한 법률 시행규칙"}}, {"is_byeolpyo": {"$eq": "true"}}]},
            include=["documents", "metadatas"])
print(f"시행규칙 별표 청크(is_byeolpyo=true): {len(r['documents'])}개")
for doc, meta in zip(r['documents'], r['metadatas']):
    print(f"  조문: {meta.get('article_no')} | {meta.get('article_title')}")
    print(f"  내용: {doc[:300]}")
    print()

# 별표 1의2 본문 청크 직접 검색
print("--- 별표1의2 본문 내용 검색 ---")
r2 = col.get(where_document={"$contains": "상수원보호구역"}, include=["documents", "metadatas"])
print(f"상수원보호구역 포함 청크: {len(r2['documents'])}개")
for doc, meta in zip(r2['documents'], r2['metadatas']):
    if '시행규칙' in meta.get('law_name', '') or '별표' in meta.get('article_no', ''):
        print(f"  {meta.get('law_name')} | {meta.get('article_no')}: {doc[:300]}")
        print()
