import sys, json
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
import chromadb
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

CHROMA_DIR = Path('data/chroma_db')
EMBED_MODEL = "jhgan/ko-sroberta-multitask"

print("임베딩 모델 로드...")
embed = HuggingFaceEmbedding(model_name=EMBED_MODEL)

client = chromadb.PersistentClient(path=str(CHROMA_DIR))
col = client.get_collection('qa_precedents')

rec_path = Path('data/qa_precedents/updates/법제처_24-0696.jsonl')
rec = json.loads(rec_path.read_text(encoding='utf-8'))

q = rec['contents'][0]['parts'][0]['text']
a = rec['contents'][1]['parts'][0]['text']
new_doc = f"{q}\n\n{a}"

new_meta = {
    "doc_code":      rec.get('doc_code', '24-0696'),
    "doc_ref":       rec.get('doc_ref', ''),
    "doc_agency":    rec.get('doc_agency', '법제처'),
    "doc_date":      rec.get('doc_date', ''),
    "relation_type": rec.get('relation_type', 'SCOPE_CL'),
    "relation_name": rec.get('relation_name', ''),
    "label_summary": rec.get('label_summary', '')[:300],
    "search_tags":   rec.get('search_tags', ''),
    "tag":           rec.get('tag', '법제처해석례'),
    "question":      q[:500],
}

doc_id = 'qa_법제처_24-0696_0'
print("임베딩 계산 중...")
emb = embed.get_text_embedding(new_doc)

col.update(
    ids=[doc_id],
    embeddings=[emb],
    documents=[new_doc],
    metadatas=[new_meta],
)
print(f'업데이트 완료: {doc_id}')
print(f'search_tags: {new_meta["search_tags"][:80]}')
