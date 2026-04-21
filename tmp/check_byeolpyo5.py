import sys
sys.stdout.reconfigure(encoding='utf-8')
import chromadb

client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('law_articles')

r = col.get(where_document={"$contains": "상수원보호구역"}, include=["documents", "metadatas"])
for doc, meta in zip(r['documents'], r['metadatas']):
    print(f"법령: {meta.get('law_name')} | 조문: {meta.get('article_no')} | is_byeolpyo={meta.get('is_byeolpyo')}")
    print(f"내용: {doc[:400]}")
    print()
