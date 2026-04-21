import sys, json
sys.stdout.reconfigure(encoding='utf-8')
import chromadb

client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('law_articles')

res = col.get(where={'law_name': {'$eq': '건축법 시행규칙'}}, include=['metadatas'], limit=500)
metas = res.get('metadatas', [])
articles = sorted(set(m.get('article_no','') for m in metas))

print(f'건축법 시행규칙: {len(metas)}개 청크')
print(f'조문 목록: {articles}')

if metas:
    print(f'\n메타데이터 키: {list(metas[0].keys())}')
    print(f'샘플: {json.dumps(metas[0], ensure_ascii=False)}')

# 전체 법령명 목록도 확인
res2 = col.get(include=['metadatas'], limit=5000)
law_names = sorted(set(m.get('law_name','') for m in res2.get('metadatas', [])))
print(f'\n전체 법령 목록:')
for ln in law_names:
    print(f'  {ln}')
