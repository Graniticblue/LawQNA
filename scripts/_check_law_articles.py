import chromadb
client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('law_articles')
res = col.get(limit=3, include=['metadatas', 'documents'])
for i, (m, d) in enumerate(zip(res['metadatas'], res['documents'])):
    with open('_law_sample.txt', 'w', encoding='utf-8') as f:
        f.write(f"=== Sample {i+1} ===\n")
        f.write(f"Metadata: {m}\n\n")
        f.write(f"Document (first 500): {d[:500]}\n\n")
    break

with open('_law_sample.txt', 'w', encoding='utf-8') as f:
    for i, (m, d) in enumerate(zip(res['metadatas'], res['documents'])):
        f.write(f"=== Sample {i+1} ===\n")
        f.write(f"Metadata: {m}\n\n")
        f.write(f"Document: {d[:300]}\n\n")
print(f"Total: {col.count()}")
print("Saved to _law_sample.txt")
