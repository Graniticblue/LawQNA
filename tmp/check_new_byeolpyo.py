import sys
sys.stdout.reconfigure(encoding='utf-8')
import chromadb

client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('law_articles')
print(f"law_articles 총 청크: {col.count()}")

# 국토 시행규칙 전체
r = col.get(
    where={"law_name": {"$eq": "국토의 계획 및 이용에 관한 법률 시행규칙"}},
    include=["documents", "metadatas"]
)
print(f"시행규칙 청크: {len(r['documents'])}개")
for doc, meta in zip(r['documents'], r['metadatas']):
    bp = meta.get('is_byeolpyo', 'false')
    print(f"  [{bp}] {meta.get('article_no')} | {meta.get('article_title', '')[:40]}")
