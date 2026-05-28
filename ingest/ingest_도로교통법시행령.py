"""
도로교통법 시행령 PDF → law_articles ChromaDB 인덱싱

두 PDF 처리:
  1. 본칙 (시행령 조문)
  2. 별표
"""
import re, json, time, sys
from pathlib import Path
import fitz
sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).parent

PDF_MAIN  = BASE_DIR / "data/raw_laws/법령소스/도로교통법 시행령(대통령령)(제35387호)(20260319).pdf"
PDF_BYEOL = BASE_DIR / "data/raw_laws/법령소스/도로교통법 시행령 별표 (대통령령)(제35387호)(20260319).pdf"

LAW_NAME    = "도로교통법 시행령"
LAW_ID      = "도로교통법시행령"
LAW_TYPE    = "대통령령"
ENFORCEMENT = "20260319"
SOURCE_URL  = "https://www.law.go.kr/법령/도로교통법시행령"

CHROMA_DIR  = BASE_DIR / "data/chroma_db"
COLLECTION  = "law_articles"
EMBED_MODEL = "jhgan/ko-sroberta-multitask"


def extract_text(pdf_path: Path) -> str:
    doc = fitz.open(str(pdf_path))
    text = "\n".join(p.get_text("text") for p in doc)
    doc.close()
    return text


def clean_text(text: str) -> str:
    text = re.sub(r'법제처\s+\d+\s+국가법령정보센터\s*\n[^\n]*\n', '', text)
    text = re.sub(r'법제처\s+\d+\s+국가법령정보센터', '', text)
    return text


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
        end       = matches[i+1].start() if i+1 < len(matches) else len(text)
        content   = text[start:end].strip()
        articles.append({
            "law_id": LAW_ID, "law_name": LAW_NAME, "law_type": LAW_TYPE,
            "article_no": art_no, "article_title": art_title,
            "content": content, "enforcement_date": ENFORCEMENT,
            "source_url": SOURCE_URL,
        })
    return articles


# ■ 도로교통법 시행령 [별표 N] 또는 ■도로교통법시행령[별표N]
BYEOL_PATTERN = re.compile(
    r'■\s*도로교통법\s*시행령\s*\[별표\s*(\d+(?:의\d+)?)\](?:\s*삭제[^\n]*)?\s*(?:<[^>]+>)?[ \t]*([^\n]*)?'
)

def parse_byeolpyo(text: str) -> list[dict]:
    text = clean_text(text)
    matches = list(BYEOL_PATTERN.finditer(text))
    articles = []
    for i, m in enumerate(matches):
        art_no    = f"별표{m.group(1)}"
        art_title = (m.group(2) or "").strip()
        start     = m.start()
        end       = matches[i+1].start() if i+1 < len(matches) else len(text)
        content   = text[start:end].strip()
        articles.append({
            "law_id": LAW_ID, "law_name": LAW_NAME, "law_type": LAW_TYPE,
            "article_no": art_no, "article_title": art_title,
            "content": content[:3000], "enforcement_date": ENFORCEMENT,
            "source_url": SOURCE_URL, "is_byeolpyo": True,
        })
    return articles


def ingest_to_chroma(articles: list[dict]) -> None:
    import chromadb
    from llama_index.core import Document, VectorStoreIndex, StorageContext, Settings
    from llama_index.vector_stores.chroma import ChromaVectorStore
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding

    embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL)
    Settings.llm = None
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    chroma_col    = chroma_client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})
    existing_ids  = set(chroma_col.get(limit=100000, include=[]).get("ids", []))
    print(f"기존 벡터 수: {len(existing_ids)}")

    docs = []
    for rec in articles:
        doc_id = f"art_{rec['law_id']}_{rec['article_no']}"
        if doc_id in existing_ids:
            continue
        text = f"[{rec['law_name']}] {rec['article_no']} {rec['article_title']}\n{rec['content']}".strip()
        meta = {
            "law_id": rec["law_id"], "law_name": rec["law_name"],
            "law_type": rec["law_type"], "article_no": rec["article_no"],
            "article_title": rec["article_title"][:200],
            "enforcement_date": rec["enforcement_date"],
            "source_url": rec["source_url"][:300],
            "is_byeolpyo": "true" if rec.get("is_byeolpyo") else "false",
        }
        docs.append(Document(text=text, metadata=meta, id_=doc_id))

    if not docs:
        print("추가할 신규 항목 없음")
        return
    print(f"신규 추가: {len(docs)}개")
    vector_store = ChromaVectorStore(chroma_collection=chroma_col)
    storage_ctx  = StorageContext.from_defaults(vector_store=vector_store)
    t0 = time.time()
    VectorStoreIndex.from_documents(docs, storage_context=storage_ctx, embed_model=embed_model, show_progress=True)
    print(f"완료! ({time.time()-t0:.1f}s)  총 벡터 수: {chroma_col.count()}")


def save_jsonl(articles, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for a in articles:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    print(f"JSONL 저장: {path} ({len(articles)}건)")


def main():
    all_articles = []

    print(f"[1] 본칙 파싱: {PDF_MAIN.name}")
    arts = parse_articles(extract_text(PDF_MAIN))
    print(f"    조문 {len(arts)}개")
    for a in arts[:3]:
        print(f"    {a['article_no']}({a['article_title']}): {a['content'][:50]}...")
    all_articles.extend(arts)

    print(f"\n[2] 별표 파싱: {PDF_BYEOL.name}")
    byeol = parse_byeolpyo(extract_text(PDF_BYEOL))
    if not byeol:
        # 별지 서식 패턴 시도
        text = extract_text(PDF_BYEOL)
        m = re.search(r'■.*?\[별지', text)
        print(f"    별표 0개 — 별지서식 형태 감지: {bool(m)}")
        print(f"    텍스트 앞부분:\n{clean_text(text)[:300]}")
    else:
        print(f"    별표 {len(byeol)}개")
        for a in byeol[:3]:
            print(f"    {a['article_no']}({a['article_title']}): {a['content'][:50]}...")
    all_articles.extend(byeol)

    print(f"\n총 {len(all_articles)}개")
    save_jsonl(all_articles, BASE_DIR / "data/raw_laws/도로교통법시행령_articles.jsonl")
    ingest_to_chroma(all_articles)

    # all_articles.jsonl 추가
    src = Path(BASE_DIR / "data/raw_laws/도로교통법시행령_articles.jsonl").read_text(encoding="utf-8")
    with open(BASE_DIR / "data/raw_laws/all_articles.jsonl", "a", encoding="utf-8") as f:
        f.write(src)
    total = sum(1 for l in open(BASE_DIR / "data/raw_laws/all_articles.jsonl", encoding="utf-8") if l.strip())
    print(f"all_articles.jsonl 총 레코드: {total}")


if __name__ == "__main__":
    main()
