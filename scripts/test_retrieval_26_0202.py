#!/usr/bin/env python3
import sys
import warnings
warnings.filterwarnings("ignore")
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import chromadb
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

embed = HuggingFaceEmbedding(model_name="jhgan/ko-sroberta-multitask")
client = chromadb.PersistentClient(path=str(Path(__file__).parent.parent / "data" / "chroma_db"))
col = client.get_collection("qa_precedents")

queries = [
    "토지등소유자 1인 재개발사업 타당성검증 요청 의무",
    "도시정비법 제78조제3항 타당성검증 1인 사업",
]

for query in queries:
    print(f"\n쿼리: {query}")
    emb = embed.get_text_embedding(query)
    res = col.query(query_embeddings=[emb], n_results=5, include=["metadatas", "distances"])
    for i, (meta, dist) in enumerate(zip(res["metadatas"][0], res["distances"][0])):
        score = 1 - dist
        code = meta.get("doc_code", "")
        q = meta.get("question", "")[:50]
        print(f"  {i+1}. [{score:.3f}] {code} | {q}")

# 26-0202 직접 조회
print("\n--- 26-0202 직접 ID 조회 ---")
try:
    r = col.get(ids=["qa_법제처_26-0202_0"], include=["metadatas"])
    if r["ids"]:
        print(f"Found: {r['ids'][0]}")
        print(f"  doc_code: {r['metadatas'][0].get('doc_code', '')}")
    else:
        print("Not found by ID qa_법제처_26-0202_0")
except Exception as e:
    print(f"Error: {e}")
