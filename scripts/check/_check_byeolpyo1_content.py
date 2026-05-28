import sys
sys.stdout.reconfigure(encoding='utf-8')
import chromadb

client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('law_articles')

res = col.get(limit=200000, include=['metadatas', 'documents'], where={'is_byeolpyo': 'true'})
found = 0
for i, meta in enumerate(res['metadatas']):
    if meta.get('law_name', '') == '건축법 시행령' and '별표1' in meta.get('article_no', ''):
        doc = res['documents'][i]
        if any(kw in doc for kw in ['다중주택', '다가구', '필로티']):
            print(f'=== {res["ids"][i]} ===')
            print(doc[:800])
            print('...\n')
            found += 1

print(f'\n총 {found}개 청크에 관련 내용 포함')
