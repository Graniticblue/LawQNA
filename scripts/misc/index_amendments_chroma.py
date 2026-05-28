#!/usr/bin/env python3
"""
scripts/index_amendments_chroma.py
-- amendments.jsonl → ChromaDB 'law_amendments' 컬렉션 인덱싱

사용:
  python scripts/index_amendments_chroma.py
"""

import json
import os
import sys
from pathlib import Path

# ── 경로 설정 ──────────────────────────────────────────────────
BASE_DIR        = Path(__file__).parent.parent
DATA_DIR        = BASE_DIR / "data"
CHROMA_DIR      = Path(os.environ.get("CHROMA_DB_PATH", str(DATA_DIR / "chroma_db")))
AMENDMENTS_PATH = DATA_DIR / "law_amendments" / "amendments.jsonl"

EMBED_MODEL_NAME = "jhgan/ko-sroberta-multitask"
COLLECTION_NAME  = "law_amendments"


def build_doc_text(rec: dict) -> str:
    """각 레코드를 임베딩할 텍스트로 변환."""
    kp = rec.get("목적론적_키포인트", "")
    if isinstance(kp, list):
        kp_lines = "\n".join(kp)
    else:
        kp_lines = str(kp) if kp else ""

    doc_text = (
        f"{rec['law_name']} {rec.get('공포번호', '')} {rec.get('시행일', '')}\n"
        f"{rec.get('개정이유', '')}\n"
        f"{rec.get('주요내용', '')}\n"
        f"{kp_lines}"
    )
    return doc_text.strip()


def load_amendments() -> list[dict]:
    if not AMENDMENTS_PATH.exists():
        print(f"[ERROR] amendments.jsonl 없음: {AMENDMENTS_PATH}")
        sys.exit(1)
    records = []
    with open(AMENDMENTS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[WARN] JSON 파싱 실패: {e}")
    return records


def main():
    print(f"amendments.jsonl 로드 중: {AMENDMENTS_PATH}")
    records = load_amendments()
    print(f"  → {len(records)}건 로드 완료")

    print(f"\n임베딩 모델 로드 중: {EMBED_MODEL_NAME}")
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding
    embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
    print("  → 임베딩 모델 로드 완료")

    print(f"\nChromaDB 연결 중: {CHROMA_DIR}")
    import chromadb
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    # 기존 컬렉션 삭제 후 재생성
    try:
        chroma_client.delete_collection(COLLECTION_NAME)
        print(f"  → 기존 '{COLLECTION_NAME}' 컬렉션 삭제")
    except Exception:
        pass

    collection = chroma_client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    print(f"  → '{COLLECTION_NAME}' 컬렉션 생성 완료")

    # 임베딩 및 upsert
    print(f"\n임베딩 + 인덱싱 시작 ({len(records)}건)...")
    ids       = []
    documents = []
    embeddings = []
    metadatas  = []

    for i, rec in enumerate(records, 1):
        aid = rec.get("amendment_id", f"amendment_{i}")
        doc_text = build_doc_text(rec)

        emb = embed_model.get_text_embedding(doc_text)

        ids.append(aid)
        documents.append(doc_text)
        embeddings.append(emb)
        metadatas.append({
            "amendment_id": aid,
            "law_name":     rec.get("law_name", ""),
            "공포번호":      rec.get("공포번호", ""),
            "시행일":        rec.get("시행일", ""),
        })

        if i % 10 == 0 or i == len(records):
            print(f"  [{i}/{len(records)}] {aid}")

    collection.add(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    print(f"\n인덱싱 완료: '{COLLECTION_NAME}' 컬렉션에 {collection.count()}건 저장됨")


if __name__ == "__main__":
    main()
