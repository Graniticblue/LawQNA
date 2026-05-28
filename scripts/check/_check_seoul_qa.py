import chromadb
client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('qa_precedents')
res = col.get(limit=10000, include=['metadatas'])
sources = {}
for m in res['metadatas']:
    sf = m.get('source_file', '') or ''
    sources[sf] = sources.get(sf, 0) + 1
for k, v in sorted(sources.items(), key=lambda x: -x[1]):
    print(f'{v:5d}  {k}')
print(f'\n총 {col.count()}건')
