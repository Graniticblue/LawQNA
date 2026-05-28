import sys, json
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from collections import defaultdict
import chromadb

BASE = Path(__file__).parent.parent
CHROMA_DIR = BASE / "data/chroma_db"

client = chromadb.PersistentClient(path=str(CHROMA_DIR))
col = client.get_collection("law_articles")

# 전체 통계
total = col.count()
print(f"=== ChromaDB law_articles 총 벡터 수: {total} ===\n")

# 법령별 조문 수
result = col.get(limit=total, include=["metadatas"])
law_counts = defaultdict(int)
for meta in result["metadatas"]:
    law_counts[meta.get("law_name", "?")] += 1

for law, cnt in sorted(law_counts.items(), key=lambda x: -x[1]):
    print(f"  {law}: {cnt}개")

print(f"\n총 {len(law_counts)}개 법령")

# 신규 추가 법령 샘플 검색 테스트
print("\n=== 검색 테스트 ===")
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
embed_model = HuggingFaceEmbedding(model_name="jhgan/ko-sroberta-multitask")

queries = [
    ("주차장 부설 설치기준", "주차장법 시행령"),
    ("도로 신호기 종류", "도로교통법 시행규칙"),
    ("건설기술인 업무정지", "건설기술 진흥법 시행규칙"),
    ("정비사업 시행인가", "도시 및 주거환경정비법 시행규칙"),
]

for query, expected_law in queries:
    vec = embed_model.get_text_embedding(query)
    res = col.query(query_embeddings=[vec], n_results=1, include=["metadatas","distances"])
    m = res["metadatas"][0][0]
    score = round(1 - res["distances"][0][0], 3)
    hit = "✓" if expected_law in m.get("law_name","") else "✗"
    print(f"  {hit} '{query}'")
    print(f"     → {m['law_name']} {m['article_no']} (score={score})")
