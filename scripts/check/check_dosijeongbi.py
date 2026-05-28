import sys
sys.stdout.reconfigure(encoding='utf-8')
import chromadb

client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('law_articles')

# 전체 법령명 목록에서 도시정비 관련 확인
results = col.get(include=['metadatas'], limit=10000)
law_names = set(m.get('law_name', '') for m in results['metadatas'])

dosijeongbi = [n for n in law_names if '정비' in n or '도시 및 주거' in n]
print(f"'정비' 포함 법령명:")
for n in sorted(dosijeongbi):
    print(f"  {n}")

# 제50조의2 직접 검색
results2 = col.get(include=['metadatas', 'documents'], limit=10000)
hits = [(m.get('law_name',''), m.get('article_no',''))
        for m, d in zip(results2['metadatas'], results2['documents'])
        if '50조의2' in d or '제50조의2' in m.get('article_no','')]
if hits:
    print(f"\n제50조의2 hits: {len(hits)}")
    for h in hits[:5]:
        print(f"  {h}")
else:
    print("\n제50조의2: 없음")
