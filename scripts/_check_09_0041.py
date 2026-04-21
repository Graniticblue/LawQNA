import chromadb
client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('qa_precedents')
res = col.get(limit=10000, include=['metadatas'])
found = [m for m in res['metadatas'] if '09-0041' in str(m)]
print(f"09-0041 검색 결과: {len(found)}건")
