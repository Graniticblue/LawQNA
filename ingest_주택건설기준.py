"""
주택건설기준 등에 관한 규정 PDF → law_articles ChromaDB 인덱싱

PDF에서 조문 파싱 후 기존 law_articles 컬렉션에 추가.
"""
import re
import json
import time
from pathlib import Path

import fitz  # PyMuPDF


# ── 설정 ──────────────────────────────────────────────────
PDF_PATH       = "data/raw_laws/주택건설기준 등에 관한 규정(대통령령)(제36220호)(20260324)-1.pdf"
LAW_NAME       = "주택건설기준 등에 관한 규정"
LAW_ID         = "주택건설기준규정"  # 내부 고유 ID (law.go.kr 없으므로 약칭 사용)
LAW_TYPE       = "대통령령"
ENFORCEMENT    = "20260324"
SOURCE_URL     = "https://www.law.go.kr/법령/주택건설기준등에관한규정"
CHROMA_DIR     = Path("data/chroma_db")
COLLECTION     = "law_articles"

# 임베딩 모델 (기존 law_articles와 동일해야 함)
EMBED_MODEL_NAME = "jhgan/ko-sroberta-multitask"


# ── PDF 텍스트 추출 ────────────────────────────────────────
def extract_text(pdf_path: str) -> str:
    doc = fitz.open(pdf_path)
    pages = []
    for page in doc:
        pages.append(page.get_text("text"))
    doc.close()
    return "\n".join(pages)


# ── 헤더/푸터 제거 ─────────────────────────────────────────
def clean_header_footer(text: str) -> str:
    # "법제처                          N                          국가법령정보센터\n주택건설기준 등에 관한 규정\n"
    pattern = r'법제처\s+\d+\s+국가법령정보센터\s*\n주택건설기준 등에 관한 규정\s*\n'
    return re.sub(pattern, '', text)


# ── 조문 파싱 ──────────────────────────────────────────────
# 패턴: "제N조(제목)" 또는 "제N조의M(제목)" 또는 "제N조 삭제"
ARTICLE_PATTERN = re.compile(
    r'^(제\d+조(?:의\d+)?)'  # 조번호
    r'(?:\(([^)]+)\))?'       # (제목) - 선택
    r'[ \t]*',                # 공백
    re.MULTILINE
)

def parse_articles(text: str) -> list[dict]:
    text = clean_header_footer(text)

    # 조번호 위치 찾기
    matches = list(ARTICLE_PATTERN.finditer(text))
    articles = []

    for i, m in enumerate(matches):
        art_no    = m.group(1)
        art_title = m.group(2) or ""

        start = m.start()
        end   = matches[i + 1].start() if i + 1 < len(matches) else len(text)

        content = text[start:end].strip()

        # 삭제 조문 표시
        if re.search(r'삭제\s*<', content[:100]):
            art_title = art_title or "삭제"

        # 법제처 헤더 잔류 제거
        content = re.sub(r'\s*법제처\s+\d+\s+국가법령정보센터.*', '', content)
        content = content.strip()

        articles.append({
            "law_id":           LAW_ID,
            "law_name":         LAW_NAME,
            "law_type":         LAW_TYPE,
            "article_no":       art_no,
            "article_title":    art_title,
            "content":          content,
            "enforcement_date": ENFORCEMENT,
            "source_url":       SOURCE_URL,
        })

    return articles


# ── ChromaDB 직접 추가 ─────────────────────────────────────
def ingest_to_chroma(articles: list[dict]) -> None:
    import chromadb
    from llama_index.core import Document, VectorStoreIndex, StorageContext, Settings
    from llama_index.vector_stores.chroma import ChromaVectorStore
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding

    print(f"\n임베딩 모델 로드: {EMBED_MODEL_NAME}")
    embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
    Settings.llm = None

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    chroma_col    = chroma_client.get_or_create_collection(
        COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )

    # 기존 doc_id 목록 조회 (중복 방지)
    existing = chroma_col.get(limit=100000, include=[])
    existing_ids = set(existing.get("ids", []))
    print(f"기존 law_articles 벡터 수: {len(existing_ids)}")

    # Document 생성
    docs = []
    for rec in articles:
        doc_id = f"art_{rec['law_id']}_{rec['article_no']}"
        if doc_id in existing_ids:
            print(f"  [SKIP] {doc_id} 이미 존재")
            continue

        text = (
            f"[{rec['law_name']}] "
            f"{rec['article_no']} {rec['article_title']}\n"
            f"{rec['content']}"
        ).strip()

        meta = {
            "law_id":           rec["law_id"],
            "law_name":         rec["law_name"],
            "law_type":         rec["law_type"],
            "article_no":       rec["article_no"],
            "article_title":    rec["article_title"][:200],
            "enforcement_date": rec["enforcement_date"],
            "source_url":       rec["source_url"][:300],
            "is_byeolpyo":      "false",
        }

        docs.append(Document(text=text, metadata=meta, id_=doc_id))

    if not docs:
        print("추가할 신규 조문 없음 (전부 중복)")
        return

    print(f"신규 추가 조문: {len(docs)}개")
    vector_store = ChromaVectorStore(chroma_collection=chroma_col)
    storage_ctx  = StorageContext.from_defaults(vector_store=vector_store)

    print(f"임베딩 + 저장 중...")
    t0 = time.time()
    VectorStoreIndex.from_documents(
        docs,
        storage_context=storage_ctx,
        embed_model=embed_model,
        show_progress=True,
    )
    elapsed = time.time() - t0
    print(f"완료! ({elapsed:.1f}s)")
    print(f"최종 law_articles 벡터 수: {chroma_col.count()}")


# ── 메인 ──────────────────────────────────────────────────
def main():
    print(f"PDF 파싱: {PDF_PATH}")
    text = extract_text(PDF_PATH)
    print(f"텍스트 추출 완료: {len(text)}자")

    articles = parse_articles(text)
    print(f"파싱된 조문: {len(articles)}개")

    # 미리보기
    for a in articles[:5]:
        print(f"  {a['article_no']}({a['article_title']}): {a['content'][:60]}...")

    # JSONL 저장 (백업용)
    out_path = Path("data/raw_laws/주택건설기준_articles.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for a in articles:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    print(f"\nJSONL 저장: {out_path}")

    # ChromaDB 인덱싱
    ingest_to_chroma(articles)


if __name__ == "__main__":
    main()
