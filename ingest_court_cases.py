#!/usr/bin/env python3
"""
ingest_court_cases.py -- data/court_cases/*.jsonl → ChromaDB "court_cases" 컬렉션

사용법:
  python ingest_court_cases.py            # 전량 재인덱싱
  python ingest_court_cases.py --update   # 미등록 건만 추가 (증분)

레코드 스키마 (JSONL 1줄 = 판례 1건):
  case_id         : 사건번호 (예: "2017두48956")
  court           : 법원 (예: "대법원")
  decision_date   : 선고일 YYYY-MM-DD
  case_name       : 사건명
  cited_laws_str  : 인용 법령 콤마 구분 문자열 (검색 필터용)
  cited_articles  : 인용 조문 배열
  relation_types  : 관계 유형 코드 (예: "PROC_DISC")
  relation_name   : 관계 유형 한글명
  label_summary   : 핵심 결론 1~2문장
  holding         : 판시사항 (검색 텍스트 포함)
  facts           : 사실관계 요약
  reasoning_summary: 이유 요약
  related_cases   : 인용 판례 번호 배열
  search_tags     : 검색 태그 문자열
  tag             : 분류 태그 (예: "대법원판례")
"""
import argparse
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import chromadb
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

BASE_DIR        = Path(__file__).parent
DATA_DIR        = BASE_DIR / "data"
CHROMA_DIR      = DATA_DIR / "chroma_db"
CASES_DIR       = DATA_DIR / "court_cases"

EMBED_MODEL_NAME = "jhgan/ko-sroberta-multitask"
COLLECTION_NAME  = "court_cases"


def load_cases() -> list[dict]:
    cases = []
    for path in sorted(CASES_DIR.glob("*.jsonl")):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                cases.append(json.loads(line))
    return cases


def build_index_text(rec: dict) -> str:
    """인덱싱용 텍스트: 검색에 걸려야 할 모든 내용."""
    parts = []
    if rec.get("case_name"):
        parts.append(f"[{rec['court']} {rec['case_id']}] {rec['case_name']}")
    if rec.get("label_summary"):
        parts.append(rec["label_summary"])
    if rec.get("holding"):
        parts.append(rec["holding"])
    if rec.get("facts"):
        parts.append(rec["facts"])
    if rec.get("reasoning_summary"):
        parts.append(rec["reasoning_summary"])
    if rec.get("search_tags"):
        parts.append(rec["search_tags"])
    return "\n\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description="판례 court_cases 인덱서")
    parser.add_argument("--update", action="store_true",
                        help="증분 추가 (미등록 건만)")
    args = parser.parse_args()

    if not CASES_DIR.exists():
        print(f"오류: {CASES_DIR} 폴더 없음")
        sys.exit(1)

    cases = load_cases()
    if not cases:
        print("인덱싱할 판례 없음.")
        return
    print(f"판례 {len(cases)}건 로드")

    # ── 임베딩 모델 ──────────────────────────────────────────────
    print(f"임베딩 모델 로드: {EMBED_MODEL_NAME}")
    embed = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)

    # ── ChromaDB ─────────────────────────────────────────────────
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    if args.update:
        try:
            col = client.get_collection(COLLECTION_NAME)
        except Exception:
            col = client.create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
        existing = set(col.get(limit=200_000, include=[])["ids"])
        print(f"기존 {len(existing)}건 — 증분 추가 모드")
    else:
        try:
            client.delete_collection(COLLECTION_NAME)
            print(f"기존 '{COLLECTION_NAME}' 삭제")
        except Exception:
            pass
        col = client.create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        existing = set()

    # ── 인덱싱 ───────────────────────────────────────────────────
    ids, embeddings, documents, metadatas = [], [], [], []

    for rec in cases:
        cid = rec.get("case_id", "")
        if cid in existing:
            print(f"  [SKIP] {cid} (이미 존재)")
            continue

        text = build_index_text(rec)
        emb  = embed.get_text_embedding(text)

        ids.append(cid)
        embeddings.append(emb)
        documents.append(text)
        metadatas.append({
            "case_id":        cid,
            "court":          rec.get("court", ""),
            "decision_date":  rec.get("decision_date", ""),
            "case_name":      rec.get("case_name", ""),
            "cited_laws_str": rec.get("cited_laws_str", ""),
            "relation_types": rec.get("relation_types", ""),
            "relation_name":  rec.get("relation_name", ""),
            "label_summary":  rec.get("label_summary", "")[:300],
            "search_tags":    rec.get("search_tags", ""),
            "tag":            rec.get("tag", "대법원판례"),
        })
        print(f"  인덱싱: {cid} — {rec.get('case_name', '')[:40]}")

    if ids:
        BATCH = 50
        for i in range(0, len(ids), BATCH):
            col.add(
                ids=ids[i:i+BATCH],
                embeddings=embeddings[i:i+BATCH],
                documents=documents[i:i+BATCH],
                metadatas=metadatas[i:i+BATCH],
            )
        print(f"\n완료: {len(ids)}건 인덱싱 → '{COLLECTION_NAME}' 컬렉션")
    else:
        print("추가할 신규 판례 없음.")

    print(f"전체 doc 수: {col.count()}")


if __name__ == "__main__":
    main()
