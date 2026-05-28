"""
도시 및 주거환경정비법 시행규칙 PDF → law_articles ChromaDB 인덱싱

두 PDF 처리:
  1. 본칙 (시행규칙 조문)
  2. 별표 (시행규칙 별표)
"""
import re
import json
import time
from pathlib import Path

import fitz  # PyMuPDF

# ── 설정 ──────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent

PDF_MAIN   = BASE_DIR / "data/raw_laws/법령소스/도시 및 주거환경정비법 시행규칙(국토교통부령)(제01561호)(20260211).pdf"
PDF_BYEOL  = BASE_DIR / "data/raw_laws/법령소스/도시 및 주거환경정비법 시행규칙 별표 (국토교통부령)(제01561호)(20260211)-1.pdf"

LAW_NAME    = "도시 및 주거환경정비법 시행규칙"
LAW_ID      = "도시정비법시행규칙"
LAW_TYPE    = "국토교통부령"
ENFORCEMENT = "20260211"
SOURCE_URL  = "https://www.law.go.kr/법령/도시및주거환경정비법시행규칙"

CHROMA_DIR  = BASE_DIR / "data/chroma_db"
COLLECTION  = "law_articles"
EMBED_MODEL = "jhgan/ko-sroberta-multitask"


# ── PDF 텍스트 추출 ────────────────────────────────────────
def extract_text(pdf_path: Path) -> str:
    doc = fitz.open(str(pdf_path))
    pages = [page.get_text("text") for page in doc]
    doc.close()
    return "\n".join(pages)


# ── 헤더/푸터 제거 ─────────────────────────────────────────
def clean_text(text: str) -> str:
    # 법제처 페이지 헤더 제거
    text = re.sub(r'법제처\s+\d+\s+국가법령정보센터\s*\n[^\n]*\n', '', text)
    text = re.sub(r'법제처\s+\d+\s+국가법령정보센터', '', text)
    return text


# ── 본칙 조문 파싱 ─────────────────────────────────────────
ARTICLE_PATTERN = re.compile(
    r'^(제\d+조(?:의\d+)?)(?:\(([^)]+)\))?[ \t]*',
    re.MULTILINE
)

def parse_articles(text: str) -> list[dict]:
    text = clean_text(text)
    matches = list(ARTICLE_PATTERN.finditer(text))
    articles = []

    for i, m in enumerate(matches):
        art_no    = m.group(1)
        art_title = m.group(2) or ""
        start     = m.start()
        end       = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content   = text[start:end].strip()

        if re.search(r'^제\d+조\s+삭제', content[:30]):
            art_title = art_title or "삭제"

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


# ── 별표 파싱 ──────────────────────────────────────────────
# 별지 서식 패턴: ■ 도시 및 주거환경정비법 시행규칙[별지 제N호서식]
BYEOL_PATTERN = re.compile(
    r'■\s*도시 및 주거환경정비법 시행규칙\s*\[별지\s*(제\d+호서식(?:의\d+)?)\](?:\s*<[^>]+>)?[ \t]*([^\n]*)?',
)

def parse_byeolpyo(text: str) -> list[dict]:
    text = clean_text(text)
    matches = list(BYEOL_PATTERN.finditer(text))
    articles = []

    for i, m in enumerate(matches):
        art_no    = m.group(1).strip()   # "제1호서식"
        art_title = (m.group(2) or "").strip()
        start     = m.start()
        end       = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content   = text[start:end].strip()

        articles.append({
            "law_id":           LAW_ID,
            "law_name":         LAW_NAME,
            "law_type":         LAW_TYPE,
            "article_no":       art_no,
            "article_title":    art_title,
            "content":          content[:3000],
            "enforcement_date": ENFORCEMENT,
            "source_url":       SOURCE_URL,
            "is_byeolpyo":      True,
        })

    return articles


# ── ChromaDB 인덱싱 ────────────────────────────────────────
def ingest_to_chroma(articles: list[dict]) -> None:
    import chromadb
    from llama_index.core import Document, VectorStoreIndex, StorageContext, Settings
    from llama_index.vector_stores.chroma import ChromaVectorStore
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding

    print(f"\n임베딩 모델 로드: {EMBED_MODEL}")
    embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL)
    Settings.llm = None

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    chroma_col    = chroma_client.get_or_create_collection(
        COLLECTION, metadata={"hnsw:space": "cosine"}
    )

    existing_ids = set(chroma_col.get(limit=100000, include=[]).get("ids", []))
    print(f"기존 law_articles 벡터 수: {len(existing_ids)}")

    docs = []
    for rec in articles:
        doc_id = f"art_{rec['law_id']}_{rec['article_no']}"
        if doc_id in existing_ids:
            print(f"  [SKIP] {doc_id}")
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
            "is_byeolpyo":      "true" if rec.get("is_byeolpyo") else "false",
        }

        docs.append(Document(text=text, metadata=meta, id_=doc_id))

    if not docs:
        print("추가할 신규 조문 없음 (전부 중복)")
        return

    print(f"신규 추가: {len(docs)}개")
    vector_store = ChromaVectorStore(chroma_collection=chroma_col)
    storage_ctx  = StorageContext.from_defaults(vector_store=vector_store)

    t0 = time.time()
    VectorStoreIndex.from_documents(
        docs, storage_context=storage_ctx,
        embed_model=embed_model, show_progress=True,
    )
    print(f"완료! ({time.time() - t0:.1f}s)  총 벡터 수: {chroma_col.count()}")


# ── JSONL 저장 ─────────────────────────────────────────────
def save_jsonl(articles: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for a in articles:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    print(f"JSONL 저장: {path} ({len(articles)}건)")


# ── 메인 ──────────────────────────────────────────────────
def main():
    all_articles = []

    # 1. 본칙
    print(f"[1] 본칙 파싱: {PDF_MAIN.name}")
    text_main = extract_text(PDF_MAIN)
    arts_main = parse_articles(text_main)
    print(f"    조문 {len(arts_main)}개 파싱됨")
    for a in arts_main[:3]:
        print(f"    {a['article_no']}({a['article_title']}): {a['content'][:50]}...")
    all_articles.extend(arts_main)

    # 2. 별표
    print(f"\n[2] 별표 파싱: {PDF_BYEOL.name}")
    text_byeol = extract_text(PDF_BYEOL)
    arts_byeol = parse_byeolpyo(text_byeol)
    print(f"    별표 {len(arts_byeol)}개 파싱됨")
    for a in arts_byeol[:3]:
        print(f"    {a['article_no']}({a['article_title']}): {a['content'][:50]}...")
    all_articles.extend(arts_byeol)

    print(f"\n총 {len(all_articles)}개 항목")

    # JSONL 백업
    save_jsonl(all_articles, BASE_DIR / "data/raw_laws/도시정비법시행규칙_articles.jsonl")

    # ChromaDB 인덱싱
    ingest_to_chroma(all_articles)


if __name__ == "__main__":
    main()
