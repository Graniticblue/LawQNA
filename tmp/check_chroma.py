import sys
sys.stdout.reconfigure(encoding='utf-8')
import chromadb

client = chromadb.PersistentClient(path='data/chroma_db')
cols = client.list_collections()
print(f"컬렉션 수: {len(cols)}")
for c in cols:
    print(f"  {c.name}: {c.count()}개")
