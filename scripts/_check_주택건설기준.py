import chromadb
client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('law_articles')
res = col.get(limit=5000, include=['metadatas'])
laws = set(m.get('law_name','') for m in res['metadatas'])
hits = [l for l in laws if '주택건설기준' in l]
print("DB 검색 결과:", hits if hits else "없음")
