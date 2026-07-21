#!/usr/bin/env python3
"""
02_Indexer.py -- 최초 전체 인덱스 빌드

실행:
  python 02_Indexer.py                       # 전체 빌드 (없는 데이터는 스킵)
  python 02_Indexer.py --reset               # 기존 컬렉션 삭제 후 전체 재빌드
  python 02_Indexer.py --collection laws     # 법령 인덱스만 (재)빌드
  python 02_Indexer.py --collection qa       # 질의회신 인덱스만 (재)빌드

결과물:
  data/chroma_db/   <-- Chroma 영구 저장소
    law_articles/   <-- 법령 조문 + 별표 벡터 인덱스
    qa_precedents/  <-- 질의회신 선례 벡터 인덱스

필요 패키지:
  pip install llama-index-core llama-index-vector-stores-chroma
              llama-index-embeddings-huggingface
              chromadb sentence-transformers
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

# ============================================================
# 경로 설정
# ============================================================
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
CHROMA_DIR = Path(os.environ.get("CHROMA_DB_PATH", str(DATA_DIR / "chroma_db")))

ALL_ARTICLES_PATH = DATA_DIR / "raw_laws" / "all_articles.jsonl"
BYEOLPYO_PATH     = DATA_DIR / "raw_laws" / "byeolpyo" / "byeolpyo_chunks.jsonl"
QA_UPDATES_DIR    = DATA_DIR / "qa_precedents" / "updates"
MANIFEST_PATH     = DATA_DIR / "qa_precedents" / "manifest.json"
LABELED_WITH_DOC_PATH = DATA_DIR / "labeled_with_doc.jsonl"

# 법제처 해석례 전용 컬렉션
PRECEDENTS_ADD_COLLECTION = "precedents_2026_april"
PRECEDENTS_MANIFEST_PATH  = DATA_DIR / "qa_precedents" / "manifest_법제처.json"

# ============================================================
# 임베딩 모델 설정
# ============================================================
# [A] 한국어 특화 -- 빠르고 가볍다, 순수 한국어 텍스트에 적합
EMBED_MODEL_A = "jhgan/ko-sroberta-multitask"

# [B] 다국어 -- 성능이 더 높지만 모델 크기 560MB, prefix 필요
EMBED_MODEL_B = "intfloat/multilingual-e5-large"

# ★ 여기서 모델 선택
EMBED_MODEL_NAME = EMBED_MODEL_A
USE_E5_PREFIX    = (EMBED_MODEL_NAME == EMBED_MODEL_B)
# multilingual-e5 사용 시:
#   인덱싱(passage): "passage: " + text
#   쿼리(query):     "query: "   + text
# ko-sroberta 사용 시: prefix 없음

# ============================================================
# 헬퍼
# ============================================================

def truncate(s: str, max_len: int = 500) -> str:
    """Chroma 메타데이터 크기 제한 대비 문자열 자름"""
    if not isinstance(s, str):
        s = str(s)
    return s[:max_len]


def _extract_search_tags(answer_text: str) -> str:
    """답변 텍스트의 [검색 태그] 섹션에서 #해시태그 추출"""
    m = re.search(r'###\s*\[검색 태그\](.*?)(?=###|\Z)', answer_text, re.DOTALL)
    if not m:
        return ""
    tags = re.findall(r'#(\S+)', m.group(1))
    return " ".join(tags)


# ============================================================
# Document 로더 -- 법령
# ============================================================

_HANG_MARKERS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚"


def split_article_into_hangs(content: str):
    """조문 content를 항(①②③) 단위로 분할.

    반환: [(항마커, 항텍스트), ...]. 항 마커가 2개 미만이면 None(분할 안 함).
    긴 다항(多項) 조문이 하나의 벡터로 임베딩되면 max_seq_length(128토큰)에
    뒷항이 잘려 검색되지 않으므로(예: 제55조의2 제3항 돌봄센터 단서가 309번째
    토큰), 항 단위로 쪼개 각 항이 독립 벡터를 갖게 한다.
    """
    positions = [(m.start(), m.group()) for m in re.finditer(f"[{_HANG_MARKERS}]", content)]
    if len(positions) < 2:
        return None
    hangs = []
    for i, (pos, marker) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(content)
        hangs.append((marker, content[pos:end].strip()))
    return hangs


def _normalize_middot(s: str) -> str:
    """법령명 가운뎃점 변종을 U+00B7(·)로 통일. 검색측(05_Retriever)·코드 상수와
    표기를 맞춰 ChromaDB $eq 매칭 누락을 방지한다."""
    return s.replace("ㆍ", "·").replace("・", "·").replace("‧", "·")


def load_law_documents() -> list:
    """
    all_articles.jsonl (법령 조문)
    + byeolpyo_chunks.jsonl (별표)
    -> LlamaIndex Document 리스트
    """
    docs = []

    # ── 1) 법령 조문 ──────────────────────────────────────────
    if ALL_ARTICLES_PATH.exists():
        print(f"  [조문] {ALL_ARTICLES_PATH.name} 로드 중...")
        with open(ALL_ARTICLES_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                law_name      = _normalize_middot(rec.get("law_name", ""))
                article_no    = rec.get("article_no", "")
                article_title = rec.get("article_title", "")
                content       = rec.get("content", "")
                law_id        = rec.get("law_id", "")

                base_meta = {
                    "law_id":           truncate(law_id, 100),
                    "law_name":         truncate(law_name, 100),
                    "law_type":         rec.get("law_type", ""),
                    "article_no":       article_no,
                    "article_title":    truncate(article_title, 200),
                    "enforcement_date": rec.get("enforcement_date", ""),
                    "promulgation_no":  rec.get("promulgation_no", ""),  # 공포번호(예: 법률 제21323호)
                    "source_url":       truncate(rec.get("source_url", ""), 300),
                    "is_byeolpyo":      "false",
                }

                # 다항(多項) 조문은 항 단위로 분할 — 긴 조문의 뒷항이 128토큰에
                # 잘려 검색되지 않는 문제 방지. 각 항에 조문 헤더([법령] 조번호 제목)를
                # 붙여 맥락을 유지하고, 항이 1개뿐이면 조문 통째로 1개 doc을 만든다.
                hangs = split_article_into_hangs(content)
                if hangs:
                    for hno, (marker, htext) in enumerate(hangs, 1):
                        text = (
                            f"[{law_name}] {article_no} {article_title} {marker}\n{htext}"
                        ).strip()
                        meta = dict(base_meta)
                        meta["hang_no"] = marker
                        doc_id = f"art_{law_id}_{article_no}_h{hno}"
                        docs.append({"id": doc_id, "text": text, "meta": meta})
                else:
                    text = (
                        f"[{law_name}] {article_no} {article_title}\n{content}"
                    ).strip()
                    meta = dict(base_meta)
                    meta["hang_no"] = ""
                    doc_id = f"art_{law_id}_{article_no}"
                    docs.append({"id": doc_id, "text": text, "meta": meta})

        print(f"    -> {len(docs):,}개 조문 로드 완료")
    else:
        print(f"  [SKIP] all_articles.jsonl 없음")
        print(f"         (API 키 설정 후 01_Law_Downloader.py 실행 필요)")

    # ── 2) 별표 청크 ──────────────────────────────────────────
    byeolpyo_start = len(docs)
    if BYEOLPYO_PATH.exists():
        print(f"  [별표] {BYEOLPYO_PATH.name} 로드 중...")
        with open(BYEOLPYO_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)

                bp_law_name = _normalize_middot(rec.get("law_name", ""))
                section  = rec.get("section_title", "")
                related  = rec.get("related_article", "")
                text = (
                    f"[{bp_law_name}] "
                    f"{rec.get('article_no', '')} {rec.get('article_title', '')}"
                    + (f" [{section}]" if section else "")
                    + (f" (관련조문: {related})" if related else "")
                    + f"\n{rec.get('content', '')}"
                ).strip()

                meta = {
                    "law_id":           truncate(rec.get("law_id", ""), 100),
                    "law_name":         truncate(bp_law_name, 100),
                    "law_type":         rec.get("law_type", ""),
                    "article_no":       rec.get("article_no", ""),
                    "article_title":    truncate(rec.get("article_title", ""), 200),
                    "enforcement_date": rec.get("enforcement_date", ""),
                    "source_url":       truncate(rec.get("source_url", ""), 300),
                    "is_byeolpyo":      "true",
                    "byeolpyo_no":      rec.get("byeolpyo_no", ""),
                    "related_article":  rec.get("related_article", ""),
                    "chunk_seq":        str(rec.get("chunk_seq", 0)),
                    "section_title":    truncate(rec.get("section_title", ""), 200),
                }
                doc_id = f"byp_{rec.get('law_id', '')}_{rec.get('chunk_seq', 0)}"
                docs.append({"id": doc_id, "text": text, "meta": meta})

        added = len(docs) - byeolpyo_start
        print(f"    -> {added}개 별표 청크 로드 완료")
    else:
        print(f"  [SKIP] byeolpyo_chunks.jsonl 없음")

    print(f"  [합계] 법령 인덱스 Document {len(docs):,}개")
    return docs


# ============================================================
# Document 로더 -- 질의회신
# ============================================================

def load_qa_documents(jsonl_path: Path, source_label: str = "") -> list:
    """
    v9_final.jsonl (또는 업데이트 JSONL) -> LlamaIndex Document 리스트

    JSONL 레코드 구조:
      {"contents": [
          {"role": "user",  "parts": [{"text": "질문"}]},
          {"role": "model", "parts": [{"text": "CoT 답변"}]}
      ]}
    """
    docs = []
    label = source_label or jsonl_path.name

    with open(jsonl_path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            contents = rec.get("contents", [])

            question = ""
            answer   = ""
            for turn in contents:
                role  = turn.get("role", "")
                parts = turn.get("parts", [{}])
                text  = parts[0].get("text", "") if parts else ""
                if role == "user":
                    question = text
                elif role == "model":
                    answer = text

            if not question:
                continue

            # 검색태그: top-level search_tags 필드(법제처 JSONL) 우선,
            # 없으면 답변 본문의 ### [검색 태그] 섹션에서 추출
            search_tags   = rec.get("search_tags", "").strip() or _extract_search_tags(answer)
            label_summary = rec.get("label_summary", "").strip()

            # 임베딩 텍스트 구성
            # 전략: 변별력 높은 순서로 맨 앞에 배치 -> 임베딩 모델 max_seq_length(128토큰)가
            #       긴 질문·답변에 잠식되지 않고 핵심 신호를 확실히 반영.
            #       [태그]+[요약](결론)이 앞 128토큰을 채움. 질문 도입부가 일반적 법령
            #       인용이라 변별력이 약한 케이스(예: 21-0347)도 요약으로 보완됨.
            #       답변은 뒤에 둬도 documents 반환에는 그대로 포함됨.
            # doc 필드 (labeled_with_doc.jsonl 등에서 존재)
            doc_ref    = rec.get("doc_ref", "")
            doc_agency = rec.get("doc_agency", "")
            doc_code   = rec.get("doc_code", "")
            doc_date   = rec.get("doc_date", "")
            tag        = rec.get("tag", "")

            embed_text = ""
            if search_tags:
                embed_text += f"[태그] {search_tags}\n"
            if label_summary:
                embed_text += f"[요약] {label_summary}\n"
            embed_text += f"[질문]\n{question}"
            if doc_ref:
                embed_text += f"\n[참조] {doc_ref}"
            embed_text += f"\n\n[답변]\n{answer}"

            meta = {
                "question":    truncate(question, 500),
                "answer_head": truncate(answer, 300),    # 결과 미리보기용
                "search_tags": truncate(search_tags, 300),
                "doc_ref":     truncate(doc_ref, 100),
                "doc_agency":  truncate(doc_agency, 50),
                "doc_code":    truncate(doc_code, 50),
                "doc_date":    doc_date,
                "tag":         truncate(tag, 50),
                "source_file": label,
                "record_idx":  str(i),
                # 레코드 명시 인용 표기 — 있으면 리트리버의 자동 생성 대신 이걸 사용
                # (T3/T4 부처·지자체 회신은 수동 지정 원칙, 2026-07-21)
                "cite_label":  truncate(rec.get("cite_label", ""), 80),
            }
            doc_id = f"qa_{jsonl_path.stem}_{i}"
            docs.append({"id": doc_id, "text": embed_text, "meta": meta})

            # 문단 청크 (jsonl에 paragraphs 있으면) — 논지별 독립 검색용.
            # 통째 doc과 같은 doc_code라, search_qa dedup이 "1해석례=1대표결과"를
            # 유지하면서(쿼리에 가장 맞는 문단 OR 통째가 대표로 노출됨) 정밀도를 높인다.
            for pi, para in enumerate(rec.get("paragraphs", []), 1):
                gist = (para.get("gist", "") or "").strip()
                body = (para.get("text", "") or "").strip()
                if not gist or gist == "SKIP" or not body:
                    continue
                p_text = f"[{doc_ref}] 논지: {gist}\n{body}"
                p_meta = dict(meta)
                p_meta["is_paragraph"] = "true"
                p_meta["para_seq"]     = str(pi)
                p_meta["gist"]         = truncate(gist, 300)
                docs.append({"id": f"{doc_id}_p{pi}", "text": p_text, "meta": p_meta})

    return docs


# ============================================================
# 인덱스 빌더
# ============================================================

def build_index(
    collection_name: str,
    documents: list,
    chroma_client,
    embed_model,
    reset: bool = False,
) -> None:
    """dict 리스트를 Chroma 컬렉션에 임베딩 + 저장 (중복 스킵)"""
    if not documents:
        print(f"  [SKIP] {collection_name}: 저장할 Document 없음")
        return

    if reset:
        try:
            chroma_client.delete_collection(collection_name)
            print(f"  기존 컬렉션 삭제 완료: {collection_name}")
        except Exception:
            pass

    col = chroma_client.get_or_create_collection(
        collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    # 기존 ID 조회 → 중복 스킵
    existing_ids = set(col.get(limit=200_000, include=[])["ids"])
    new_docs = [d for d in documents if d["id"] not in existing_ids]

    # 같은 빌드 배치 내 중복 ID 제거 (소스 jsonl에 동일 ID가 중복될 수 있음 —
    # 중복 시 chromadb add가 DuplicateIDError로 전체 빌드를 중단시킨다)
    _seen: set = set()
    _deduped = []
    for d in new_docs:
        if d["id"] in _seen:
            continue
        _seen.add(d["id"])
        _deduped.append(d)
    if len(_deduped) < len(new_docs):
        print(f"  [{collection_name}] 빌드 내 중복 ID {len(new_docs) - len(_deduped)}개 제거")
    new_docs = _deduped

    if not new_docs:
        print(f"  [{collection_name}] 신규 없음 (전부 중복)")
        return
    if len(new_docs) < len(documents):
        skipped = len(documents) - len(new_docs)
        print(f"  [{collection_name}] {skipped}개 중복 스킵, {len(new_docs):,}개 신규")

    print(f"  [{collection_name}] {len(new_docs):,}개 임베딩 + 저장 중...")
    t0 = time.time()

    BATCH = 50
    added = 0
    for i in range(0, len(new_docs), BATCH):
        batch = new_docs[i: i + BATCH]
        ids, embeddings, texts, metas = [], [], [], []
        for doc in batch:
            ids.append(doc["id"])
            embeddings.append(embed_model.get_text_embedding(doc["text"]))
            texts.append(doc["text"])
            metas.append(doc["meta"])
        col.add(ids=ids, embeddings=embeddings, documents=texts, metadatas=metas)
        added += len(batch)
        print(f"    {added}/{len(new_docs)} 완료", end="\r")

    elapsed = time.time() - t0
    rate    = len(new_docs) / elapsed if elapsed > 0 else 0
    print(f"\n  [{collection_name}] 완료! ({elapsed:.1f}s, {rate:.0f} docs/s)")


# ============================================================
# Manifest 관리 (qa_precedents 처리 이력)
# ============================================================

def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"indexed": []}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def get_indexed_files(manifest: dict) -> set:
    return {item["file"] for item in manifest.get("indexed", [])}


def record_in_manifest(manifest: dict, fname: str, count: int) -> None:
    """manifest에 처리 완료 기록 (이미 있으면 갱신)"""
    manifest["indexed"] = [x for x in manifest["indexed"] if x["file"] != fname]
    manifest["indexed"].append({
        "file":  fname,
        "count": count,
        "date":  date.today().isoformat(),
    })


# ============================================================
# 메인
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="02_Indexer: Chroma 인덱스 초기 빌드")
    parser.add_argument(
        "--reset", action="store_true",
        help="기존 컬렉션 삭제 후 전체 재빌드",
    )
    parser.add_argument(
        "--collection", choices=["laws", "qa", "법제처", "all"], default="all",
        help="빌드할 컬렉션 선택 (기본: all). 법제처: updates/ → precedents_2026_april",
    )
    args = parser.parse_args()

    # ── 패키지 임포트 확인 ─────────────────────────────────────
    print("패키지 임포트 중...")
    try:
        import chromadb
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding
    except ImportError as e:
        print(f"\n[ERROR] 필요한 패키지가 없습니다: {e}")
        print(
            "\n아래 명령어로 설치하세요:\n"
            "pip install llama-index-embeddings-huggingface "
            "chromadb sentence-transformers"
        )
        sys.exit(1)

    # ── 임베딩 모델 로드 ──────────────────────────────────────
    print(f"\n임베딩 모델 로드: {EMBED_MODEL_NAME}")
    print("  (처음 실행 시 HuggingFace Hub에서 모델 다운로드 -- 수분 소요)")

    if USE_E5_PREFIX:
        embed_model = HuggingFaceEmbedding(
            model_name=EMBED_MODEL_NAME,
            query_instruction="query: ",
            text_instruction="passage: ",
        )
    else:
        embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)

    print("  임베딩 모델 로드 완료")

    # ── Chroma 클라이언트 ─────────────────────────────────────
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\nChroma DB 경로: {CHROMA_DIR}")
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    # ==============================================================
    # [1/2] 법령 인덱스 빌드
    # ==============================================================
    if args.collection in ("laws", "all"):
        print("\n" + "=" * 60)
        print("[1/2] 법령 인덱스 (law_articles) 빌드")
        print("=" * 60)

        law_docs = load_law_documents()

        if law_docs:
            build_index(
                collection_name="law_articles",
                documents=law_docs,
                chroma_client=chroma_client,
                embed_model=embed_model,
                reset=args.reset,
            )
        else:
            print("  [SKIP] 인덱싱할 법령 데이터 없음")
            print("         --> 01_Law_Downloader.py 실행 후 재시도하세요")

    # ==============================================================
    # [2/2] 질의회신 인덱스 빌드
    # ==============================================================
    if args.collection in ("qa", "all"):
        print("\n" + "=" * 60)
        print("[2/2] 질의회신 인덱스 (qa_precedents) 빌드")
        print("=" * 60)

        manifest      = load_manifest()
        indexed_files = get_indexed_files(manifest)
        qa_docs_all   = []          # 이번에 실제로 로드된 Document 모음
        loaded_files  = {}          # {fname: count} -- manifest 업데이트용

        # ── labeled_with_doc (CoT 답변 + doc_agency/code/date) ─────
        labeled_label = LABELED_WITH_DOC_PATH.name
        if args.reset or labeled_label not in indexed_files:
            if LABELED_WITH_DOC_PATH.exists():
                print(f"  [labeled] {labeled_label} 로드 중...")
                labeled_docs = load_qa_documents(LABELED_WITH_DOC_PATH, labeled_label)
                print(f"    -> {len(labeled_docs):,}개 Q&A (CoT + doc 필드 포함)")
                qa_docs_all.extend(labeled_docs)
                loaded_files[labeled_label] = len(labeled_docs)
            else:
                print(f"  [SKIP] {labeled_label} 없음 (enrich_labeled.py 실행 필요)")
        else:
            print(f"  [SKIP] {labeled_label} 이미 인덱싱됨 (--reset 으로 재빌드 가능)")

        # ── updates/ 폴더 내 미처리 JSONL ────────────────────
        if QA_UPDATES_DIR.exists():
            update_files = sorted(QA_UPDATES_DIR.glob("*.jsonl"))
            if update_files:
                print(f"\n  updates/ 폴더 확인 ({len(update_files)}개 파일):")
                for upd_path in update_files:
                    fname = upd_path.name
                    if not args.reset and fname in indexed_files:
                        print(f"    [SKIP] {fname} 이미 인덱싱됨")
                        continue
                    print(f"    [{fname}] 로드 중...")
                    upd_docs = load_qa_documents(upd_path, fname)
                    print(f"      -> {len(upd_docs):,}개 Q&A")
                    qa_docs_all.extend(upd_docs)
                    loaded_files[fname] = len(upd_docs)

        # ── 실제 인덱싱 ───────────────────────────────────────
        if qa_docs_all:
            print(f"\n  총 {len(qa_docs_all):,}개 Q&A 인덱싱 시작")
            build_index(
                collection_name="qa_precedents",
                documents=qa_docs_all,
                chroma_client=chroma_client,
                embed_model=embed_model,
                reset=args.reset,
            )

            # manifest 업데이트
            manifest = load_manifest()   # 다시 읽어서 최신 상태 유지
            for fname, cnt in loaded_files.items():
                record_in_manifest(manifest, fname, cnt)
            save_manifest(manifest)
            print(f"  manifest.json 업데이트 완료: {list(loaded_files.keys())}")
        else:
            print("  [SKIP] 새로 인덱싱할 Q&A 데이터 없음")

    # ==============================================================
    # [3] 법제처 해석례 인덱스 (precedents_2026_april)
    # ==============================================================
    if args.collection == "법제처":
        print("\n" + "=" * 60)
        print(f"[법제처] 해석례 인덱스 ({PRECEDENTS_ADD_COLLECTION}) 빌드")
        print("=" * 60)

        # 전용 manifest 로드
        if PRECEDENTS_MANIFEST_PATH.exists():
            import json as _json
            prec_manifest = _json.loads(PRECEDENTS_MANIFEST_PATH.read_text(encoding="utf-8"))
        else:
            prec_manifest = {"indexed": []}
        prec_indexed = {item["file"] for item in prec_manifest.get("indexed", [])}

        prec_docs_all  = []
        prec_loaded    = {}

        if QA_UPDATES_DIR.exists():
            update_files = sorted(QA_UPDATES_DIR.glob("*.jsonl"))
            if update_files:
                print(f"  updates/ 폴더 확인 ({len(update_files)}개 파일):")
                for upd_path in update_files:
                    fname = upd_path.name
                    if not args.reset and fname in prec_indexed:
                        print(f"    [SKIP] {fname} 이미 인덱싱됨")
                        continue
                    print(f"    [{fname}] 로드 중...")
                    upd_docs = load_qa_documents(upd_path, fname)
                    print(f"      -> {len(upd_docs):,}개 Q&A")
                    prec_docs_all.extend(upd_docs)
                    prec_loaded[fname] = len(upd_docs)

        if prec_docs_all:
            print(f"\n  총 {len(prec_docs_all):,}개 Q&A 인덱싱 시작")
            build_index(
                collection_name=PRECEDENTS_ADD_COLLECTION,
                documents=prec_docs_all,
                chroma_client=chroma_client,
                embed_model=embed_model,
                reset=args.reset,
            )
            # 전용 manifest 갱신
            import json as _json
            from datetime import date as _date
            for fname, cnt in prec_loaded.items():
                prec_manifest["indexed"] = [x for x in prec_manifest["indexed"] if x["file"] != fname]
                prec_manifest["indexed"].append({"file": fname, "count": cnt, "date": _date.today().isoformat()})
            PRECEDENTS_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
            PRECEDENTS_MANIFEST_PATH.write_text(_json.dumps(prec_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  manifest_법제처.json 업데이트 완료: {list(prec_loaded.keys())}")
        else:
            print("  [SKIP] 새로 인덱싱할 법제처 해석례 없음")

    # ==============================================================
    # 완료 요약
    # ==============================================================
    print("\n" + "=" * 60)
    print("완료! 인덱스 현황:")
    print("=" * 60)
    for col_name in ["law_articles", "qa_precedents", PRECEDENTS_ADD_COLLECTION]:
        try:
            col = chroma_client.get_collection(col_name)
            print(f"  {col_name:25s}: {col.count():,}개 벡터")
        except Exception:
            print(f"  {col_name:25s}: (없음)")


if __name__ == "__main__":
    main()
