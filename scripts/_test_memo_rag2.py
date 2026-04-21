import sys
sys.stdout.reconfigure(encoding='utf-8')

import importlib.util

spec = importlib.util.spec_from_file_location('ret', '05_Retriever.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

r = mod.Retriever()

# threshold 없이 raw score 확인
q = "공공공지 이격거리 제86조"
emb = r._searcher._embed_text(q)
col = r._searcher._memo_col
res = col.query(query_embeddings=[emb], n_results=5, include=["metadatas", "distances"])
print(f"Query: {q}")
for meta, dist in zip(res["metadatas"][0], res["distances"][0]):
    score = max(0.0, 1.0 - dist)
    print(f"  [{meta['memo_id']}] score={score:.4f} — {meta['title'][:50]}")
