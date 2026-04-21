import sys
sys.stdout.reconfigure(encoding='utf-8')
import chromadb

client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('law_articles')

r = col.get(
    where={"$and": [
        {"law_name": {"$eq": "국토의 계획 및 이용에 관한 법률 시행규칙"}},
        {"is_byeolpyo": {"$eq": "true"}}
    ]},
    include=["documents", "metadatas"]
)
print(f"시행규칙 별표 청크: {len(r['documents'])}개")
for doc, meta in zip(r['documents'], r['metadatas']):
    print(f"\n  조문: {meta.get('article_no')} | {meta.get('article_title')}")
    print(f"  내용: {doc[:500]}")
