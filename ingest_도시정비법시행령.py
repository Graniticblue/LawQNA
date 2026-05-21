"""도시 및 주거환경정비법 시행령 + 시행령 별표 PDF → law_articles ChromaDB 인덱싱"""
import re, json, time
from pathlib import Path
import fitz

BASE_DIR  = Path(__file__).parent
PDF_MAIN  = BASE_DIR / "data/raw_laws/법령소스/도시 및 주거환경정비법 시행령(대통령령)(제36220호)(20260324).pdf"
PDF_BYEOL = BASE_DIR / "data/raw_laws/법령소스/도시 및 주거환경정비법 시행령 별표 (대통령령)(제36220호)(20260324)-2.pdf"

LAW_NAME    = "도시 및 주거환경정비법 시행령"
LAW_ID      = "도시정비법시행령"
LAW_TYPE    = "대통령령"
ENFORCEMENT = "20260324"
SOURCE_URL  = "https://www.law.go.kr/법령/도시및주거환경정비법시행령"
CHROMA_DIR  = BASE_DIR / "data/chroma_db"
COLLECTION  = "law_articles"
EMBED_MODEL = "jhgan/ko-sroberta-multitask"


def extract_text(pdf_path):
    doc = fitz.open(str(pdf_path))
    text = "\n".join(p.get_text("text") for p in doc)
    doc.close()
    return text

def clean_text(text):
    text = re.sub(r'법제처\s+\d+\s+국가법령정보센터\s*\n[^\n]*\n', '', text)
    text = re.sub(r'법제처\s+\d+\s+국가법령정보센터', '', text)
    return text

ARTICLE_PATTERN = re.compile(r'^(제\d+조(?:의\d+)?)(?:\(([^)]+)\))?[ \t]*', re.MULTILINE)

BYEOL_PATTERN = re.compile(
    r'■\s*도시 및 주거환경정비법 시행령\s*\[별표\s*(제?\d+(?:의\d+)?)\](?:\s*<[^>]+>)?[ \t]*([^\n]*)?',
)

def parse_articles(text):
    text = clean_text(text)
    matches = list(ARTICLE_PATTERN.finditer(text))
    articles = []
    for i, m in enumerate(matches):
        art_no    = m.group(1)
        art_title = m.group(2) or ""
        start     = m.start()
        end       = matches[i+1].start() if i+1 < len(matches) else len(text)
        content   = text[start:end].strip()
        if re.search(r'^제\d+조\s+삭제', content[:30]):
            art_title = art_title or "삭제"
        articles.append({
            "law_id": LAW_ID, "law_name": LAW_NAME, "law_type": LAW_TYPE,
            "article_no": art_no, "article_title": art_title,
            "content": content, "enforcement_date": ENFORCEMENT,
            "source_url": SOURCE_URL,
        })
    return articles

def parse_byeolpyo(text):
    text = clean_text(text)
    matches = list(BYEOL_PATTERN.finditer(text))
    articles = []
    for i, m in enumerate(matches):
        art_no    = f"별표{m.group(1).strip()}"
        art_title = (m.group(2) or "").strip()
        start     = m.start()
        end       = matches[i+1].start() if i+1 < len(matches) else len(text)
        content   = text[start:end].strip()
        articles.append({
            "law_id": LAW_ID, "law_name": LAW_NAME, "law_type": LAW_TYPE,
            "article_no": art_no, "article_title": art_title,
            "content": content[:4000], "enforcement_date": ENFORCEMENT,
            "source_url": SOURCE_URL, "is_byeolpyo": True,
        })
    return articles

def ingest_to_chroma(articles):
    import chromadb
    from llama_index.core import Document, VectorStoreIndex, StorageContext, Settings
    from llama_index.vector_stores.chroma import ChromaVectorStore
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding

    print(f"\n임베딩 모델 로드: {EMBED_MODEL}")
    embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL)
    Settings.llm = None
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    chroma_col    = chroma_client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})
    existing_ids  = set(chroma_col.get(limit=100000, include=[]).get("ids", []))
    print(f"기존 law_articles 벡터 수: {len(existing_ids)}")

    docs = []
    for rec in articles:
        doc_id = f"art_{rec['law_id']}_{rec['article_no']}"
        if doc_id in existing_ids:
            continue
        text = f"[{rec['law_name']}] {rec['article_no']} {rec['article_title']}\n{rec['content']}".strip()
        meta = {k: rec[k] for k in ("law_id","law_name","law_type","article_no","enforcement_date","source_url")}
        meta["article_title"] = rec["article_title"][:200]
        meta["source_url"]    = meta["source_url"][:300]
        meta["is_byeolpyo"]   = "true" if rec.get("is_byeolpyo") else "false"
        docs.append(Document(text=text, metadata=meta, id_=doc_id))

    if not docs:
        print("추가할 신규 조문 없음"); return
    print(f"신규 추가: {len(docs)}개")
    vector_store = ChromaVectorStore(chroma_collection=chroma_col)
    storage_ctx  = StorageContext.from_defaults(vector_store=vector_store)
    t0 = time.time()
    VectorStoreIndex.from_documents(docs, storage_context=storage_ctx, embed_model=embed_model, show_progress=True)
    print(f"완료! ({time.time()-t0:.1f}s)  총 벡터 수: {chroma_col.count()}")

def main():
    all_articles = []

    print(f"[1] 시행령 본칙 파싱: {PDF_MAIN.name}")
    arts_main = parse_articles(extract_text(PDF_MAIN))
    print(f"    조문 {len(arts_main)}개")
    for a in arts_main[:3]:
        print(f"    {a['article_no']}({a['article_title']}): {a['content'][:60]}...")
    all_articles.extend(arts_main)

    print(f"\n[2] 시행령 별표 파싱: {PDF_BYEOL.name}")
    arts_byeol = parse_byeolpyo(extract_text(PDF_BYEOL))
    print(f"    별표 {len(arts_byeol)}개")
    for a in arts_byeol[:3]:
        print(f"    {a['article_no']}({a['article_title']}): {a['content'][:60]}...")
    all_articles.extend(arts_byeol)

    if not arts_byeol:
        print("    ⚠ 별표 패턴 미매칭 — PDF 첫 줄 확인:")
        sample = extract_text(PDF_BYEOL)[:500]
        print(sample)

    print(f"\n총 {len(all_articles)}개 항목")
    out = BASE_DIR / "data/raw_laws/도시정비법시행령_articles.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for a in all_articles:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    print(f"JSONL 저장: {out}")
    ingest_to_chroma(all_articles)

if __name__ == "__main__":
    main()
