#!/usr/bin/env python3
"""
ingest_memos.py -- data/memos.jsonl → ChromaDB "memos" 컬렉션 인덱싱

기존 컬렉션이 있으면 삭제 후 재생성 (전량 재인덱싱).
"""
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import chromadb
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

BASE_DIR   = Path(__file__).parent
DATA_DIR   = BASE_DIR / "data"
CHROMA_DIR = DATA_DIR / "chroma_db"
MEMOS_PATH = DATA_DIR / "memos.jsonl"

EMBED_MODEL_NAME = "jhgan/ko-sroberta-multitask"
COLLECTION_NAME  = "memos"


def main():
    if not MEMOS_PATH.exists():
        print(f"오류: {MEMOS_PATH} 없음")
        sys.exit(1)

    # ── 임베딩 모델 로드 ──────────────────────────────────────
    print(f"임베딩 모델 로드: {EMBED_MODEL_NAME}")
    embed = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)

    # ── ChromaDB 클라이언트 ───────────────────────────────────
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    # 기존 컬렉션 삭제 후 재생성
    try:
        client.delete_collection(COLLECTION_NAME)
        print(f"기존 '{COLLECTION_NAME}' 컬렉션 삭제")
    except Exception:
        pass

    col = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    print(f"컬렉션 '{COLLECTION_NAME}' 생성")

    # ── memos.jsonl 읽기 ──────────────────────────────────────
    memos = []
    with open(MEMOS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            memos.append(json.loads(line))

    print(f"메모 {len(memos)}개 로드")

    # ── 인덱싱 ────────────────────────────────────────────────
    ids, embeddings, documents, metadatas = [], [], [], []

    for memo in memos:
        mid     = memo.get("memo_id", "")
        title   = memo.get("title", "")
        content = memo.get("content", "")
        tags    = memo.get("tags", [])
        linked  = memo.get("linked_to", [])
        created = memo.get("created", "")

        # 인덱싱 텍스트: 제목 + 내용 전문
        text = f"【{title}】\n{content}"

        emb = embed.get_text_embedding(text)

        ids.append(mid)
        embeddings.append(emb)
        documents.append(text)
        metadatas.append({
            "memo_id":   mid,
            "title":     title,
            "tags":      ",".join(tags),
            "linked_to": ",".join(linked),
            "created":   created,
        })

        print(f"  인덱싱: {mid} — {title[:40]}")

    col.add(
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=metadatas,
    )

    print(f"\n완료: '{COLLECTION_NAME}' 컬렉션에 {len(ids)}개 인덱싱")
    print(f"전체 doc 수: {col.count()}")


if __name__ == "__main__":
    main()
