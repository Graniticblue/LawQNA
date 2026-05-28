import chromadb, json
client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('qa_precedents')

# labeled_with_doc.jsonl 샘플 확인
res = col.get(limit=10000, include=['metadatas'])
samples = []
for m in res['metadatas']:
    if m.get('source_file') == 'labeled_with_doc.jsonl':
        samples.append(m)
        if len(samples) >= 5:
            break

print("labeled_with_doc.jsonl 샘플 메타데이터:")
for s in samples:
    print(json.dumps(s, ensure_ascii=False, indent=2))
    print("---")

# doc_id 패턴 확인
doc_ids = set()
for m in res['metadatas']:
    if m.get('source_file') == 'labeled_with_doc.jsonl':
        did = m.get('doc_id') or m.get('doc_code') or ''
        doc_ids.add(did)
print(f"\n고유 doc_id 수: {len(doc_ids)}")
print("샘플:", list(doc_ids)[:10])
