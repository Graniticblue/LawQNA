#!/usr/bin/env python3
"""
ingest_principles.py -- data/principles.jsonl → ChromaDB "principles" 컬렉션 인덱싱

인덱싱 텍스트: 제목 + 트리거 + 내용 전문
트리거 필드가 검색의 핵심 — 질의와 원칙 발동 조건 사이의 유사도를 잡아냄.
"""
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import chromadb
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

BASE_DIR        = Path(__file__).parent.parent
DATA_DIR        = BASE_DIR / "data"
CHROMA_DIR      = DATA_DIR / "chroma_db"
PRINCIPLES_PATH = DATA_DIR / "principles.jsonl"

EMBED_MODEL_NAME = "jhgan/ko-sroberta-multitask"
COLLECTION_NAME  = "principles"


def main():
    if not PRINCIPLES_PATH.exists():
        print(f"오류: {PRINCIPLES_PATH} 없음")
        sys.exit(1)

    print(f"임베딩 모델 로드: {EMBED_MODEL_NAME}")
    embed = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

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

    principles = []
    with open(PRINCIPLES_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            principles.append(json.loads(line))

    print(f"원칙 {len(principles)}개 로드")

    ids, embeddings, documents, metadatas = [], [], [], []

    for p in principles:
        pid   = p.get("principle_id", "")
        title = p.get("title", "")

        # 트리거 + 제목 + 내용을 합쳐 인덱싱 — 트리거가 검색의 핵심
        text = f"【{title}】\n트리거: {p.get('trigger', '')}\n{p.get('content', '')}"

        emb = embed.get_text_embedding(text)

        ids.append(pid)
        embeddings.append(emb)
        documents.append(text)
        metadatas.append({
            "principle_id":       pid,
            "title":              title,
            "trigger":            p.get("trigger", ""),
            "exception":          p.get("exception", ""),
            "source_cases":       ",".join(p.get("source_cases", [])),
            "source_precedents":  ",".join(p.get("source_precedents", [])),
            "tags":               ",".join(p.get("tags", [])),
        })

        print(f"  인덱싱: {pid} — {title}")

    col.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)

    print(f"\n완료: '{COLLECTION_NAME}' 컬렉션에 {len(ids)}개 인덱싱")
    print(f"전체 doc 수: {col.count()}")


if __name__ == "__main__":
    main()
