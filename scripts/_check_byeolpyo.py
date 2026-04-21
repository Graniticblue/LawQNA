import sys
sys.stdout.reconfigure(encoding='utf-8')
import chromadb

client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('law_articles')

# 별표 법령명 목록만
res = col.get(limit=200000, include=['metadatas'], where={'is_byeolpyo': 'true'})
print(f'별표 청크 총 {len(res["ids"])}개')

# 법령별 별표 목록
from collections import defaultdict
law_byeolpyo = defaultdict(set)
for meta in res['metadatas']:
    law_byeolpyo[meta.get('law_name','')].add(meta.get('article_no',''))

for law, arts in sorted(law_byeolpyo.items()):
    print(f'\n  [{law}]')
    for a in sorted(arts):
        print(f'    {a}')

# 건축법 시행령 별표 1 있는지
print('\n\n=== 건축법 시행령 별표 1 검색 ===')
for i, meta in enumerate(res['metadatas']):
    if '건축법' in meta.get('law_name','') and '별표1' in meta.get('article_no','').replace(' ','').replace('　',''):
        print(f'  {res["ids"][i]}: {meta.get("law_name")} | {meta.get("article_no")} | {meta.get("article_title","")[:60]}')
