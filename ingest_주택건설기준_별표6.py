"""
주택건설기준 등에 관한 규정 [별표 6] → law_articles 추가
"""
import time
import json
from pathlib import Path

import fitz

PDF_PATH = "data/raw_laws/[별표 6] 바닥충격음차단성능인정기관 및 바닥충격음성능검사기관의 인력 및 장비 기준(제60조의2제2항 및 제60조의9제1항제2호 관련)(주택건설기준 등에 관한 규정).pdf"
CHROMA_DIR  = Path("data/chroma_db")
COLLECTION  = "law_articles"
EMBED_MODEL = "jhgan/ko-sroberta-multitask"

doc = fitz.open(PDF_PATH)
full_text = "".join(page.get_text("text") for page in doc)
doc.close()

content = full_text.strip()
doc_id  = "byp_주택건설기준규정_별표6"

import chromadb
from llama_index.core import Document, VectorStoreIndex, StorageContext, Settings
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

print(f"임베딩 모델 로드: {EMBED_MODEL}")
embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL)
Settings.llm = None

chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
chroma_col    = chroma_client.get_or_create_collection(
    COLLECTION, metadata={"hnsw:space": "cosine"}
)

existing_ids = set(chroma_col.get(limit=100000, include=[])["ids"])
if doc_id in existing_ids:
    print(f"[SKIP] {doc_id} 이미 존재")
else:
    text = (
        "[주택건설기준 등에 관한 규정] [별표 6] "
        "바닥충격음차단성능인정기관 및 바닥충격음성능검사기관의 인력 및 장비 기준 "
        "(제60조의2제2항 및 제60조의9제1항제2호 관련)\n"
        + content
    )
    meta = {
        "law_id":           "주택건설기준규정",
        "law_name":         "주택건설기준 등에 관한 규정",
        "law_type":         "대통령령",
        "article_no":       "[별표 6]",
        "article_title":    "바닥충격음차단성능인정기관 및 바닥충격음성능검사기관의 인력 및 장비 기준",
        "enforcement_date": "20240709",
        "source_url":       "https://www.law.go.kr/법령/주택건설기준등에관한규정",
        "is_byeolpyo":      "true",
        "related_article":  "제60조의2, 제60조의9",
        "byeolpyo_no":      "별표6",
        "section_title":    "인력 및 장비 기준",
    }

    doc_obj = Document(text=text, metadata=meta, id_=doc_id)
    vector_store = ChromaVectorStore(chroma_collection=chroma_col)
    storage_ctx  = StorageContext.from_defaults(vector_store=vector_store)

    print("임베딩 + 저장 중...")
    t0 = time.time()
    VectorStoreIndex.from_documents(
        [doc_obj],
        storage_context=storage_ctx,
        embed_model=embed_model,
        show_progress=True,
    )
    print(f"완료! ({time.time()-t0:.1f}s)")
    print(f"최종 law_articles 벡터 수: {chroma_col.count()}")
