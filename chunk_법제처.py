"""
chunk_법제처.py

data/qa_precedents/updates/ 의 법제처 해석례 JSONL을 읽어
구조화된 청크(A/B/C)를 생성하고 ChromaDB precedents_2026_april에 직접 인덱싱.

청크 종류 (PLAN_법제처해석례_청킹전략.md §2):
  A  QA_CORE        : 질의요지 + 회답 + 검색태그  ← 유사 질문 매칭 최적화
  B  REASONING_STEP : 이유 단락별 (ANCHOR/ANALYSIS/PREREQUISITE/RESOLUTION)
  C  CONCLUSION     : label_summary + relation_type  ← 선례 포지셔닝

사용법:
  python chunk_법제처.py              # updates/ 전체 → 신규 파일만 인덱싱
  python chunk_법제처.py --reset      # precedents_2026_april 초기화 후 전체 재빌드
  python chunk_법제처.py --dry-run    # 청크 생성 미리보기 (인덱싱 없음)
"""

import json
import os
import re
import argparse
from datetime import date
from pathlib import Path

# ─── 경로 ─────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent
DATA_DIR       = BASE_DIR / "data"
CHROMA_DIR     = DATA_DIR / "chroma_db"
UPDATES_DIR    = DATA_DIR / "qa_precedents" / "updates"
MANIFEST_PATH  = DATA_DIR / "qa_precedents" / "manifest_법제처_chunks.json"

COLLECTION_NAME  = "precedents_2026_april"
EMBED_MODEL_NAME = "jhgan/ko-sroberta-multitask"

# RESOLUTION 판별 패턴
RESOLUTION_RE  = re.compile(r"이상과 같은 점을 종합해 볼 때|따라서 이 사안")
ANALYSIS_RE    = re.compile(r"입법연혁|도입된 이래|개정 이유|입법취지|입법 취지")
ANCHOR_RE      = re.compile(r"제\d+조제?\d*항?에서는|제\d+조[^를가이]|규정하고 있고")


# ─── 섹션 파싱 ────────────────────────────────────────────────

def _extract_section(text: str, marker: str, end_markers: list) -> str:
    """answer 텍스트에서 특정 마커 뒤 섹션 추출"""
    idx = text.find(marker)
    if idx == -1:
        return ""
    start = idx + len(marker)
    end = len(text)
    for em in end_markers:
        ei = text.find(em, start)
        if ei != -1 and ei < end:
            end = ei
    return text[start:end].strip()


def parse_answer_sections(answer: str) -> dict:
    """【회답】/【이유】/【관계 법령】 분리"""
    # 관계법령 마커 두 가지 처리
    law_text = _extract_section(answer, "【관계 법령】", []) or \
               _extract_section(answer, "【관계법령】", [])

    answer_head = _extract_section(answer, "【회답】",
                                   ["【이유】", "【관계 법령】", "【관계법령】"])
    reasoning   = _extract_section(answer, "【이유】",
                                   ["【관계 법령】", "【관계법령】", "[검색태그]"])

    # [검색태그] 제거 후 반환
    answer_head = re.sub(r'\[검색태그\].*', '', answer_head, flags=re.DOTALL).strip()
    reasoning   = re.sub(r'\[검색태그\].*', '', reasoning,   flags=re.DOTALL).strip()

    return {
        "answer_head": answer_head,
        "reasoning":   reasoning,
        "law_refs":    law_text,
    }


# ─── 이유 단락 분리 & logic_step 역할 매핑 ────────────────────

def split_reasoning_paragraphs(reasoning: str) -> list[str]:
    """이유 텍스트를 단락 단위로 분리"""
    paras = re.split(r'\n[ \t]*\n|\n \n', reasoning)
    paras = [p.strip() for p in paras if p.strip() and len(p.strip()) > 20]
    return paras


def assign_role(para: str) -> str:
    """단락 텍스트 → logic_step role (휴리스틱)"""
    if RESOLUTION_RE.search(para):
        return "RESOLUTION"
    if ANALYSIS_RE.search(para):
        return "ANALYSIS"
    if ANCHOR_RE.search(para):
        return "ANCHOR"
    return "PREREQUISITE"


# ─── 청크 생성 ────────────────────────────────────────────────

def build_chunks(rec: dict) -> list[dict]:
    """
    1개 해석례 레코드 → A/B/C 청크 리스트
    공통 메타: doc_ref, doc_code, doc_date, doc_agency,
              relation_type, relation_name, search_tags, source_file
    """
    question    = rec["contents"][0]["parts"][0]["text"]
    full_answer = rec["contents"][1]["parts"][0]["text"]
    sections    = parse_answer_sections(full_answer)

    doc_ref      = rec.get("doc_ref", "")
    doc_code     = rec.get("doc_code", "")
    doc_date     = rec.get("doc_date", "")
    doc_agency   = rec.get("doc_agency", "법제처")
    relation_type = rec.get("relation_type", "SCOPE_CL")
    relation_name = rec.get("relation_name", "")
    label_summary = rec.get("label_summary", "")
    search_tags   = rec.get("search_tags", "")
    source_file   = rec.get("_source_file", "")

    base_meta = {
        "doc_ref":       doc_ref,
        "doc_code":      doc_code,
        "doc_date":      doc_date,
        "doc_agency":    doc_agency,
        "relation_type": relation_type,
        "relation_name": relation_name,
        "search_tags":   search_tags[:300],
        "source_file":   source_file,
        "tag":           "법제처해석례",
    }

    chunks = []

    # ── 청크 A: QA_CORE ────────────────────────────────────────
    qa_embed = f"[질의요지]\n{question}"
    if sections["answer_head"]:
        qa_embed += f"\n\n[회답]\n{sections['answer_head']}"
    if doc_ref:
        qa_embed += f"\n\n[출처] {doc_ref}"
    if search_tags:
        qa_embed += f"\n[검색태그] {search_tags}"

    chunks.append({
        "chunk_type":  "QA_CORE",
        "embed_text":  qa_embed,
        "question":    question[:500],
        "answer_head": sections["answer_head"][:300],
        "full_answer": full_answer,
        **base_meta,
    })

    # ── 청크 B: REASONING_STEP ─────────────────────────────────
    if sections["reasoning"]:
        paras = split_reasoning_paragraphs(sections["reasoning"])
        for seq, para in enumerate(paras, 1):
            role = assign_role(para)
            embed_text = (
                f"[{role}] {doc_ref}\n"
                f"[쟁점 유형] {relation_name}\n"
                f"[논증 {seq}]\n{para}"
            )
            if label_summary:
                embed_text += f"\n[결론 요약] {label_summary[:200]}"

            chunks.append({
                "chunk_type":  "REASONING_STEP",
                "embed_text":  embed_text,
                "step_role":   role,
                "step_seq":    str(seq),
                "step_text":   para[:800],
                "question":    question[:300],
                "answer_head": sections["answer_head"][:200],
                **base_meta,
            })

    # ── 청크 C: CONCLUSION ─────────────────────────────────────
    if label_summary:
        conclusion_embed = (
            f"[해석 결론] {relation_name} ({relation_type})\n"
            f"{label_summary}\n\n"
            f"[출처] {doc_ref}\n"
            f"[검색태그] {search_tags}"
        )
        chunks.append({
            "chunk_type":     "CONCLUSION",
            "embed_text":     conclusion_embed,
            "label_summary":  label_summary[:500],
            "question":       question[:300],
            "answer_head":    sections["answer_head"][:200],
            **base_meta,
        })

    return chunks


# ─── manifest ─────────────────────────────────────────────────

def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {"indexed": []}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


# ─── ChromaDB 직접 인덱싱 ────────────────────────────────────

def index_chunks(all_chunks: list[dict], reset: bool = False) -> int:
    """청크 리스트를 precedents_2026_april에 직접 임베딩+저장"""
    import chromadb
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding

    print(f"임베딩 모델 로드: {EMBED_MODEL_NAME}")
    embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    if reset:
        try:
            client.delete_collection(COLLECTION_NAME)
            print(f"  기존 컬렉션 삭제: {COLLECTION_NAME}")
        except Exception:
            pass

    col = client.get_or_create_collection(
        COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    print(f"  [{COLLECTION_NAME}] {len(all_chunks)}개 청크 임베딩 중...")
    BATCH = 50
    added = 0
    for i in range(0, len(all_chunks), BATCH):
        batch = all_chunks[i: i + BATCH]
        ids, embeddings, documents, metadatas = [], [], [], []
        for j, chunk in enumerate(batch):
            chunk_id = (
                f"chk_{chunk['source_file'].replace('.jsonl','')}"
                f"_{chunk['chunk_type']}"
                f"_{chunk.get('step_seq', '0')}"
                f"_{i+j}"
            )
            emb = embed_model.get_text_embedding(chunk["embed_text"])
            # ChromaDB metadata는 str/int/float/bool만 허용
            meta = {k: v for k, v in chunk.items()
                    if k != "embed_text" and isinstance(v, (str, int, float, bool))}
            ids.append(chunk_id)
            embeddings.append(emb)
            documents.append(chunk["embed_text"])
            metadatas.append(meta)

        col.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
        added += len(batch)
        print(f"    {added}/{len(all_chunks)} 완료", end="\r")

    print(f"\n  인덱싱 완료. 컬렉션 총 {col.count():,}개 벡터")
    return added


# ─── 메인 ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="법제처 해석례 구조화 청킹 + 인덱싱")
    parser.add_argument("--reset",   action="store_true", help="컬렉션 초기화 후 전체 재빌드")
    parser.add_argument("--dry-run", action="store_true", help="청크 생성 미리보기 (인덱싱 없음)")
    args = parser.parse_args()

    manifest     = load_manifest()
    indexed_set  = {item["file"] for item in manifest.get("indexed", [])}

    files = sorted(UPDATES_DIR.glob("*.jsonl"))
    if not files:
        print(f"처리할 파일 없음: {UPDATES_DIR}")
        return

    all_chunks   = []
    loaded_files = {}

    for jsonl_path in files:
        fname = jsonl_path.name
        if not args.reset and fname in indexed_set:
            print(f"  [SKIP] {fname} 이미 청킹됨")
            continue

        print(f"\n청킹 중: {fname}")
        lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
        file_chunks = 0

        for line in lines:
            rec = json.loads(line)
            rec["_source_file"] = fname
            chunks = build_chunks(rec)
            all_chunks.extend(chunks)
            file_chunks += len(chunks)

            if args.dry_run:
                print(f"  doc_ref : {rec.get('doc_ref', '?')}")
                for c in chunks:
                    role = c.get("step_role", "-")
                    print(f"    [{c['chunk_type']}] step_role={role} | "
                          f"{c['embed_text'][:80].replace(chr(10),' ')}...")

        print(f"  → {len(lines)}건 × 평균 {file_chunks/max(len(lines),1):.1f}청크 = {file_chunks}청크")
        loaded_files[fname] = file_chunks

    if args.dry_run:
        print(f"\n[dry-run] 총 {len(all_chunks)}개 청크 생성 예정 (인덱싱 안 함)")
        return

    if not all_chunks:
        print("\n새로 처리할 파일 없음.")
        return

    print(f"\n총 {len(all_chunks)}개 청크 인덱싱 시작")
    index_chunks(all_chunks, reset=args.reset)

    # manifest 갱신
    manifest = load_manifest()
    for fname, cnt in loaded_files.items():
        manifest["indexed"] = [x for x in manifest["indexed"] if x["file"] != fname]
        manifest["indexed"].append({"file": fname, "chunks": cnt, "date": date.today().isoformat()})
    save_manifest(manifest)
    print(f"\nmanifest_법제처_chunks.json 갱신: {list(loaded_files.keys())}")


if __name__ == "__main__":
    main()
