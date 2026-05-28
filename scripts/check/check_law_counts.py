import sys, chromadb
sys.stdout.reconfigure(encoding='utf-8')
from collections import Counter

client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('law_articles')

results = col.get(include=['metadatas'], limit=100000)
total = len(results['ids'])

counts = Counter(m.get('law_name', '알수없음') for m in results['metadatas'])

print(f"총 벡터(청크) 수: {total}\n")
print("법령별 청크 수:")
for law, cnt in sorted(counts.items(), key=lambda x: -x[1]):
    print(f"  {cnt:5d}  {law}")
