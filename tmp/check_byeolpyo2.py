import sys
sys.stdout.reconfigure(encoding='utf-8')
import chromadb

client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('law_articles')

# 별표 1의2 검색
r1 = col.get(where_document={"$contains": "별표 1의2"}, include=["documents", "metadatas"])
print(f"별표 1의2 포함 청크: {len(r1['documents'])}개")
for doc, meta in zip(r1['documents'], r1['metadatas']):
    print(f"  출처: {meta}")
    print(f"  내용: {doc[:300]}")
    print()

# 별표 2 제8호 검색
r2 = col.get(where_document={"$contains": "별표 2"}, include=["documents", "metadatas"])
print(f"\n별표 2 포함 청크: {len(r2['documents'])}개")
for doc, meta in zip(r2['documents'][:5], r2['metadatas'][:5]):
    print(f"  출처: {meta}")
    print(f"  내용: {doc[:300]}")
    print()
