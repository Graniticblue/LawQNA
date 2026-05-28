#!/usr/bin/env python3
"""21-0142의 실제 검색 점수 + 22-0155 중복 원인 진단."""
import sys
import warnings
warnings.filterwarnings("ignore")
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import chromadb
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

embed = HuggingFaceEmbedding(model_name="jhgan/ko-sroberta-multitask")
client = chromadb.PersistentClient(
    path=str(Path(__file__).parent.parent / "data" / "chroma_db")
)
col = client.get_collection("qa_precedents")

SEARCH_Q = (
    "건축물이 있는 대지가 너비 25미터 미만인 도로에 20미터 이상 접하고 있고, "
    "그 도로가 해당 대지의 전면도로가 아닌 경우, "
    "해당 대지안의 건축물에 국토계획법 시행령 제85조제7항제1호 또는 제2호가 적용되어 "
    "용적률을 완화 받을 수 있는지? "
    "그 밖에 건축이 금지된 공지 그 밖의 토지 전면도로 도로 "
    "공원 광장 하천 용적률 완화"
)

emb = embed.get_text_embedding(SEARCH_Q)
res = col.query(query_embeddings=[emb], n_results=15, include=["metadatas", "distances"])

print("=== top 15 qa_precedents (용적률 질의 + 보강 검색어) ===")
seen_codes = {}
for i, (meta, dist) in enumerate(zip(res["metadatas"][0], res["distances"][0])):
    score = 1 - dist
    code = meta.get("doc_code", "")
    seen_codes[code] = seen_codes.get(code, 0) + 1
    print(f"{i+1:2d}. [{score:.3f}] {code:10s} | {meta.get('question', '')[:55]}")

print(f"\n중복 분석 (top 15 중 doc_code별 출현 수):")
for code, cnt in sorted(seen_codes.items(), key=lambda x: -x[1]):
    if cnt > 1:
        print(f"  - {code}: {cnt}회")

# 21-0142 위치
codes = [m.get("doc_code", "") for m in res["metadatas"][0]]
if "21-0142" in codes:
    pos = codes.index("21-0142")
    score = 1 - res["distances"][0][pos]
    print(f"\n→ 21-0142: top {pos+1}위, score={score:.3f}")
else:
    print("\n→ 21-0142: top 15 밖")

# 직접 ID로 21-0142 점수 확인
print("\n=== 21-0142 직접 임베딩 ===")
direct = col.get(ids=["qa_법제처_21-0142_0"], include=["documents", "embeddings"])
if direct["ids"]:
    import numpy as np
    doc_emb = direct["embeddings"][0]
    qry_emb = np.array(emb)
    dot = sum(a*b for a, b in zip(doc_emb, qry_emb))
    norm_q = sum(a*a for a in qry_emb) ** 0.5
    norm_d = sum(b*b for b in doc_emb) ** 0.5
    cos = dot / (norm_q * norm_d)
    print(f"21-0142 cosine 유사도: {cos:.3f}")
