"""건설기술 진흥법 시행령 PDF → law_articles ChromaDB 인덱싱 (대통령령 제36151호, 2026.02.27.)"""
import re, json, time, sys
from pathlib import Path
import fitz
sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).parent
PDF_MAIN  = BASE_DIR / "data/raw_laws/법령소스/건설기술 진흥법 시행령(대통령령)(제36151호)(20260227).pdf"
PDF_BYEOL = BASE_DIR / "data/raw_laws/법령소스/건설기술 진흥법 시행령 별표 (대통령령)(제36151호)(20260227).pdf"

LAW_NAME    = "건설기술 진흥법 시행령"
LAW_ID      = "건설기술진흥법시행령"
LAW_TYPE    = "대통령령"
ENFORCEMENT = "20260227"
SOURCE_URL  = "https://www.law.go.kr/법령/건설기술진흥법시행령"
CHROMA_DIR  = BASE_DIR / "data/chroma_db"
COLLECTION  = "law_articles"
EMBED_MODEL = "jhgan/ko-sroberta-multitask"


def extract_text(p):
    doc = fitz.open(str(p))
    t = "\n".join(pg.get_text("text") for pg in doc)
    doc.close()
    return t

def clean_text(t):
    t = re.sub(r'법제처\s+\d+\s+국가법령정보센터\s*\n[^\n]*\n', '', t)
    return re.sub(r'법제처\s+\d+\s+국가법령정보센터', '', t)

def parse_articles(text):
    text = clean_text(text)
    ms = list(re.finditer(r'^(제\d+조(?:의\d+)?)(?:\(([^)]+)\))?[ \t]*', text, re.MULTILINE))
    arts = []
    for i, m in enumerate(ms):
        end = ms[i+1].start() if i+1 < len(ms) else len(text)
        arts.append({"law_id": LAW_ID, "law_name": LAW_NAME, "law_type": LAW_TYPE,
            "article_no": m.group(1), "article_title": m.group(2) or "",
            "content": text[m.start():end].strip(),
            "enforcement_date": ENFORCEMENT, "source_url": SOURCE_URL})
    return arts

def parse_byeolpyo(text):
    text = clean_text(text)
    # 공백 유무 모두 처리: "건설기술진흥법" 또는 "건설기술 진흥법"
    ms = list(re.finditer(
        r'■\s*건설기술\s*진흥법\s*시행령\s*\[별표\s*(\d+(?:의\d+)?)\](?:\s*삭제[^\n]*)?\s*(?:<[^>]+>)?[ \t]*([^\n]*)?',
        text
    ))
    arts = []
    for i, m in enumerate(ms):
        end = ms[i+1].start() if i+1 < len(ms) else len(text)
        arts.append({"law_id": LAW_ID, "law_name": LAW_NAME, "law_type": LAW_TYPE,
            "article_no": f"별표{m.group(1)}", "article_title": (m.group(2) or "").strip(),
            "content": text[m.start():end].strip()[:3000],
            "enforcement_date": ENFORCEMENT, "source_url": SOURCE_URL, "is_byeolpyo": True})
    return arts

def ingest_to_chroma(articles):
    import chromadb
    from llama_index.core import Document, VectorStoreIndex, StorageContext, Settings
    from llama_index.vector_stores.chroma import ChromaVectorStore
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding
    embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL)
    Settings.llm = None
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    col    = client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})
    existing = set(col.get(limit=100000, include=[]).get("ids", []))
    print(f"기존 벡터 수: {len(existing)}")
    docs = []
    for rec in articles:
        did = f"art_{rec['law_id']}_{rec['article_no']}"
        if did in existing: continue
        t = f"[{rec['law_name']}] {rec['article_no']} {rec['article_title']}\n{rec['content']}".strip()
        meta = {k: rec[k] for k in ("law_id","law_name","law_type","enforcement_date")}
        meta["article_no"]    = rec["article_no"]
        meta["article_title"] = rec["article_title"][:200]
        meta["source_url"]    = rec["source_url"][:300]
        meta["is_byeolpyo"]   = "true" if rec.get("is_byeolpyo") else "false"
        docs.append(Document(text=t, metadata=meta, id_=did))
    if not docs: print("추가할 신규 항목 없음"); return
    print(f"신규 추가: {len(docs)}개")
    vs  = ChromaVectorStore(chroma_collection=col)
    ctx = StorageContext.from_defaults(vector_store=vs)
    t0  = time.time()
    VectorStoreIndex.from_documents(docs, storage_context=ctx, embed_model=embed_model, show_progress=True)
    print(f"완료! ({time.time()-t0:.1f}s)  총 벡터 수: {col.count()}")

def main():
    all_arts = []

    print(f"[1] 본칙: {PDF_MAIN.name}")
    arts = parse_articles(extract_text(PDF_MAIN))
    print(f"    조문 {len(arts)}개")
    for a in arts[:3]: print(f"    {a['article_no']}({a['article_title']}): {a['content'][:50]}...")
    all_arts.extend(arts)

    print(f"\n[2] 별표: {PDF_BYEOL.name}")
    byeol = parse_byeolpyo(extract_text(PDF_BYEOL))
    print(f"    별표 {len(byeol)}개")
    for a in byeol[:3]: print(f"    {a['article_no']}({a['article_title'][:30]}): {a['content'][:50]}...")
    all_arts.extend(byeol)

    print(f"\n총 {len(all_arts)}개")
    out = BASE_DIR / "data/raw_laws/건설기술진흥법시행령_articles.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        [f.write(json.dumps(a, ensure_ascii=False)+"\n") for a in all_arts]
    print(f"JSONL 저장: {out}")

    ingest_to_chroma(all_arts)

    with open(BASE_DIR / "data/raw_laws/all_articles.jsonl", "a", encoding="utf-8") as f:
        f.write(out.read_text(encoding="utf-8"))
    total = sum(1 for l in open(BASE_DIR / "data/raw_laws/all_articles.jsonl", encoding="utf-8") if l.strip())
    print(f"all_articles.jsonl 총 레코드: {total}")

if __name__ == "__main__":
    main()
