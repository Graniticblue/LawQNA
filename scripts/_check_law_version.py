import sys
sys.stdout.reconfigure(encoding='utf-8')
import chromadb

client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('law_articles')

# 건축법 시행령 별표1 메타데이터 확인
res = col.get(
    limit=5,
    include=['metadatas'],
    where={"$and": [
        {"law_name": {"$eq": "건축법 시행령"}},
        {"is_byeolpyo": {"$eq": "true"}},
    ]}
)

print('=== 건축법 시행령 별표 메타데이터 ===')
for meta in res['metadatas'][:3]:
    for k, v in meta.items():
        print(f'  {k}: {v}')
    print()

# 건축법 시행령 일반 조문 메타데이터
res2 = col.get(
    limit=3,
    include=['metadatas'],
    where={"law_name": {"$eq": "건축법 시행령"}},
)
print('=== 건축법 시행령 일반 조문 메타데이터 ===')
for meta in res2['metadatas'][:2]:
    for k, v in meta.items():
        print(f'  {k}: {v}')
    print()
