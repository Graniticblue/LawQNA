import sys, chromadb
sys.stdout.reconfigure(encoding='utf-8')

client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('law_articles')

results = col.get(include=['metadatas'], limit=100000)

# 법령별 카운트
from collections import Counter
counts = Counter(m.get('law_id','') for m in results['metadatas'])
for law_id, cnt in sorted(counts.items()):
    if '정비' in law_id or '도시' in law_id.lower():
        print(f"  {law_id}: {cnt}건")

# 별표 확인
byeol = [(m.get('law_id',''), m.get('article_no',''))
         for m in results['metadatas']
         if m.get('law_id') == '도시정비법시행령' and m.get('is_byeolpyo') == 'true']
print(f"\n도시정비법시행령 별표: {len(byeol)}개")
for b in sorted(byeol):
    print(f"  {b}")

# 제50조의2 직접 확인
art50 = [(m.get('law_id',''), m.get('article_no',''))
         for m in results['metadatas']
         if m.get('law_id') == '도시정비법' and '50' in m.get('article_no','')]
print(f"\n도시정비법 제50조 계열: {len(art50)}개")
for a in sorted(art50):
    print(f"  {a}")
