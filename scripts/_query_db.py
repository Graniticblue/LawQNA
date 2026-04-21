"""
질의 관련 DB 조회
"""
import chromadb
from llama_index.core import VectorStoreIndex, StorageContext, Settings
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

EMBED_MODEL = "jhgan/ko-sroberta-multitask"
CHROMA_DIR  = "data/chroma_db"

embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL)
Settings.llm = None

client = chromadb.PersistentClient(path=CHROMA_DIR)

queries = [
    "복리시설 용도변경 신고 어린이집 도서관",
    "입주자 공유 복리시설 용도변경 허가",
    "주택건설기준 제5조 복리시설",
]

results_out = []

for coll_name in ["law_articles", "qa_precedents", "precedents_2026_april"]:
    coll = client.get_collection(coll_name)
    for q in queries:
        res = coll.query(
            query_texts=[q],
            n_results=3,
            include=["metadatas", "documents", "distances"],
        )
        for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
            results_out.append({
                "coll": coll_name,
                "query": q,
                "dist": round(dist, 4),
                "meta_key": meta.get("law_name") or meta.get("doc_ref") or meta.get("doc_code") or "",
                "article": meta.get("article_no",""),
                "title":   meta.get("article_title","")[:40],
                "text_preview": doc[:200],
            })

results_out.sort(key=lambda x: x["dist"])

with open("_query_results.txt", "w", encoding="utf-8") as f:
    for r in results_out[:20]:
        f.write(f"[{r['coll']}] dist={r['dist']} | {r['meta_key']} {r['article']} {r['title']}\n")
        f.write(f"  Query: {r['query']}\n")
        f.write(f"  Text: {r['text_preview']}\n\n")

print("Done. Check _query_results.txt")
