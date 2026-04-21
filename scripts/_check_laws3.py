import chromadb

client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('law_articles')

# law_name 전체 목록
res = col.get(limit=3000, include=['metadatas'])
law_names = set()
for m in res['metadatas']:
    n = m.get('law_name')
    if n:
        law_names.add(n)

out = []
for n in sorted(law_names):
    out.append(n)

with open('_law_list_out3.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))
print(f"총 {len(law_names)}개 법령")
