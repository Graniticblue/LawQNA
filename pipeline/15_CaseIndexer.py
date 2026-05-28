#!/usr/bin/env python3
"""
15_CaseIndexer.py -- labeled.jsonl → Chroma court_cases 컬렉션 인덱싱

labeled.jsonl (법제처 질의회신 + 관계 유형 라벨)을 court_cases 컬렉션에
인덱싱하여 판례 검색 파이프라인에 활용.

case_id: QA_{행번호:04d}
court:   법제처 질의회신
"""

import json
import re
import sys
from pathlib import Path

# Windows 콘솔 UTF-8
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import chromadb
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / "data"
CHROMA_DIR  = DATA_DIR / "chroma_db"
INPUT_FILE  = DATA_DIR / "labeled.jsonl"

EMBED_MODEL_NAME = "jhgan/ko-sroberta-multitask"
COLLECTION_NAME  = "court_cases"
BATCH_SIZE       = 50


# ============================================================
# 법령명 추출
# ============================================================

def extract_cited_laws(answer_text: str) -> str:
    """
    답변의 [근거 법령] 섹션에서 「법령명」 패턴 추출.
    반환: "건축법,건축법 시행령" 형태의 콤마 구분 문자열
    """
    # [근거 법령] 섹션만 뽑기
    section_match = re.search(
        r'###\s*\[근거 법령\](.*?)(?=###|\Z)', answer_text, re.DOTALL
    )
    target = section_match.group(1) if section_match else answer_text

    # 「법령명」 패턴에서 법령명 추출
    law_names = re.findall(r'「([^」]+)」', target)

    # 중복 제거, 순서 유지
    seen = set()
    unique = []
    for name in law_names:
        name = name.strip()
        if name and name not in seen:
            seen.add(name)
            unique.append(name)

    return ",".join(unique)


def extract_question(record: dict) -> str:
    """contents[0].role=user 에서 질문 텍스트 추출"""
    try:
        return record["contents"][0]["parts"][0]["text"]
    except (KeyError, IndexError):
        return ""


def extract_answer(record: dict) -> str:
    """contents[1].role=model 에서 답변 텍스트 추출"""
    try:
        return record["contents"][1]["parts"][0]["text"]
    except (KeyError, IndexError):
        return ""


# ============================================================
# 레코드 → court_cases 문서 변환
# ============================================================

def to_case_doc(record: dict, row_idx: int) -> dict | None:
    """
    labeled.jsonl 레코드 → court_cases 인덱싱용 문서.
    반환: {"id", "text", "metadata"} 또는 None (건너뜀)
    """
    question       = extract_question(record).strip()
    answer_text    = extract_answer(record).strip()
    label_summary  = record.get("label_summary", "").strip()
    relation_type  = record.get("relation_type", "").strip()
    relation_name  = record.get("relation_name", "").strip()

    if not question or not label_summary:
        return None

    case_id       = f"QA_{row_idx:04d}"
    cited_laws    = extract_cited_laws(answer_text)

    # 임베딩 텍스트: 질문 + 요약 (검색 품질 최적화)
    embed_text = f"[질문]\n{question}\n\n[요지]\n{label_summary}"

    metadata = {
        "case_id":          case_id,
        "court":            "법제처 질의회신",
        "decision_date":    "",
        "case_type":        question[:100],      # 질문을 사건 요지로
        "result":           label_summary[:200],
        "chunk_type":       "질의회신",
        "chunk_seq":        1,
        "cited_laws_str":   cited_laws,
        "relation_types":   relation_type,
        "relation_summary": label_summary[:300],
        "confidence_min":   1.0,
        "source_file":      "labeled.jsonl",
        "orig_idx":         row_idx,
    }

    return {
        "id":       case_id,
        "text":     embed_text,
        "metadata": metadata,
    }


# ============================================================
# 인덱싱
# ============================================================

def build_index():
    print("=" * 60)
    print("15_CaseIndexer: labeled.jsonl → court_cases")
    print("=" * 60)

    # 레코드 로드
    records = []
    with open(INPUT_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    print(f"입력: {len(records)}건 로드")

    # 문서 변환
    docs = []
    skipped = 0
    for row_idx, record in enumerate(records):
        doc = to_case_doc(record, row_idx)
        if doc:
            docs.append(doc)
        else:
            skipped += 1

    print(f"변환: {len(docs)}건 (건너뜀 {skipped}건)")

    # 임베딩 모델 + Chroma 초기화
    print("\n임베딩 모델 로드 중...")
    embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)

    print("Chroma DB 연결 중...")
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    # 기존 컬렉션 삭제 후 재생성 (재실행 안전)
    try:
        client.delete_collection(COLLECTION_NAME)
        print(f"기존 '{COLLECTION_NAME}' 컬렉션 삭제")
    except Exception:
        pass

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    print(f"'{COLLECTION_NAME}' 컬렉션 생성")

    # 배치 인덱싱
    print(f"\n인덱싱 시작 (배치 크기: {BATCH_SIZE})...")
    total = len(docs)
    for batch_start in range(0, total, BATCH_SIZE):
        batch = docs[batch_start:batch_start + BATCH_SIZE]

        ids        = [d["id"]   for d in batch]
        texts      = [d["text"] for d in batch]
        metadatas  = [d["metadata"] for d in batch]
        embeddings = [embed_model.get_text_embedding(t) for t in texts]

        collection.add(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas,
        )

        end = min(batch_start + BATCH_SIZE, total)
        print(f"  [{end}/{total}] 완료")

    print(f"\n인덱싱 완료: court_cases {collection.count()}건")

    # 유형별 통계
    print("\n[관계 유형별 분포]")
    type_counts: dict[str, int] = {}
    for doc in docs:
        rt = doc["metadata"]["relation_types"]
        type_counts[rt] = type_counts.get(rt, 0) + 1
    for rt, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {rt:12s}: {cnt}건")


if __name__ == "__main__":
    build_index()
