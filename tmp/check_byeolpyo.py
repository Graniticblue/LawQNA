import sys
sys.stdout.reconfigure(encoding='utf-8')
import chromadb

client = chromadb.PersistentClient(path='data/law_cache')
cols = client.list_collections()
print("컬렉션 목록:")
for c in cols:
    print(f"  {c.name}: {c.count()}개")

# 별표 1의2, 별표 2 관련 청크 검색
for c in cols:
    col = client.get_collection(c.name)
    results = col.get(where_document={"$contains": "별표 1의2"}, include=["documents", "metadatas"])
    if results['documents']:
        print(f"\n[{c.name}] 별표 1의2 포함 청크 {len(results['documents'])}개:")
        for doc, meta in zip(results['documents'], results['metadatas']):
            print(f"  출처: {meta.get('source','?')} | {doc[:200]}")
            print()
