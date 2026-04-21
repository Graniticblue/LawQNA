import chromadb, json

client = chromadb.PersistentClient(path='data/chroma_db')
cols = client.list_collections()
out = []
for col in cols:
    out.append(f"\n[컬렉션] {col.name} — {col.count()}건")
    # metadata 샘플로 법령명 추출
    try:
        res = col.get(limit=5, include=['metadatas'])
        for m in res['metadatas']:
            law = m.get('law_name') or m.get('source') or m.get('법령명') or str(list(m.keys())[:3])
            out.append(f"  샘플: {law}")
    except Exception as e:
        out.append(f"  오류: {e}")

with open('_law_list_out2.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))
print("done")
