import sys, chromadb
sys.stdout.reconfigure(encoding='utf-8')

client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('law_articles')

# 도시정비법시행령 별표 항목만 삭제
results = col.get(include=['metadatas'], limit=100000)
del_ids = [
    doc_id for doc_id, meta in zip(results['ids'], results['metadatas'])
    if meta.get('law_id') == '도시정비법시행령' and meta.get('is_byeolpyo') == 'true'
]
print(f"삭제 대상: {len(del_ids)}개")
if del_ids:
    col.delete(ids=del_ids)
    print(f"삭제 완료. 현재 총 벡터 수: {col.count()}")
