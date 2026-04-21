#!/usr/bin/env python3
"""
05_Retriever.py -- 3-Layer 법령 라우팅 + 하이브리드 검색

사용:
  from 05_Retriever import Retriever

  retriever = Retriever()
  law_docs, qa_docs, case_docs = retriever.retrieve(
      query="다중이용업소의 용도변경 시 필요한 절차는?",
      question_type="복수조문탐색형",
      relation_types=[
          {"type": "SCOPE_CL", "weight": 1.0},
          {"type": "REQ_INT",  "weight": 0.7},
      ],
  )
  context = retriever.format_context(law_docs, qa_docs, case_docs)

검색 계층:
  1층: law_articles  -법령 조문 (법규 필터 + 하이브리드)
  2층: qa_precedents -질의회신 선례 (doc_ref 기반, 유사도 0.60 이상)
  3층: court_cases   -판례 (법규 × 유형 쌍 필터, 컬렉션 구축 후 활성화)
"""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import chromadb
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

# ============================================================
# 경로 설정
# ============================================================
BASE_DIR        = Path(__file__).parent
DATA_DIR        = BASE_DIR / "data"
CHROMA_DIR      = Path(os.environ.get("CHROMA_DB_PATH", str(DATA_DIR / "chroma_db")))
MAP_PATH        = DATA_DIR / "keyword_law_map.json"
GRAPH_PATH      = DATA_DIR / "article_graph.json"
ARTICLE_ROLES_DIR = DATA_DIR / "article_roles"

EMBED_MODEL_NAME = "jhgan/ko-sroberta-multitask"
MEMOS_PATH      = DATA_DIR / "memos.jsonl"
AMENDMENTS_PATH = DATA_DIR / "law_amendments" / "amendments.jsonl"

# 법령명 축약어 → 정식명칭 매핑 (메모 태그 매칭용)
LAW_ABBREV_MAP: dict[str, str] = {
    "건축법시행령":      "건축법 시행령",
    "건축법":           "건축법",
    "국토계획법":       "국토의 계획 및 이용에 관한 법률",
    "국토계획법시행령":  "국토의 계획 및 이용에 관한 법률 시행령",
    "농지법":          "농지법",
    "주택법":          "주택법",
    "주택법시행령":     "주택법 시행령",
    "소방시설법":       "소방시설 설치 및 관리에 관한 법률",
    "다중이용업법":     "다중이용업소의 안전관리에 관한 특별법",
    "장애인편의법":     "장애인·노인·임산부 등의 편의증진 보장에 관한 법률",
    "주차장법":        "주차장법",
}

# 판례-법령 관계 7가지 유형 (PLAN §1)
RELATION_TYPES: dict[str, str] = {
    "DEF_EXP":   "정의확장형",
    "SCOPE_CL":  "적용범위 확정형",
    "REQ_INT":   "요건해석형",
    "EXCEPT":    "예외인정형",
    "INTER_ART": "조문간관계 해석형",
    "PROC_DISC": "절차·재량 확인형",
    "SANC_SC":   "벌칙·제재 범위형",
}


# ============================================================
# 결과 타입
# ============================================================

@dataclass
class RetrievedDoc:
    """검색 결과 1건"""
    source: str        # "law_articles" | "court_cases"
    law_name: str
    article_no: str
    content: str
    score: float
    score_type: str    # "vector" | "bm25" | "hybrid"
    metadata: dict = field(default_factory=dict)

    def __str__(self):
        return (
            f"[{self.source}] {self.law_name} {self.article_no} "
            f"(score={self.score:.3f})\n"
            f"  {self.content[:100]}..."
        )


# ============================================================
# Layer 1: 주제 분류 → 기본 법령 세트
# ============================================================

TOPIC_LAW_MAP: dict[str, list[str]] = {
    # 용도·분류
    "용도":           ["건축법", "건축법 시행령"],
    "용도변경":        ["건축법", "건축법 시행령"],
    "건축물 용도":     ["건축법", "건축법 시행령"],
    "근린생활시설":    ["건축법 시행령"],
    "다중이용업소":    ["건축법 시행령", "다중이용업소의 안전관리에 관한 특별법"],
    "고시원":         ["건축법 시행령"],
    "숙박시설":        ["건축법 시행령", "공중위생관리법"],
    # 건축허가·신고
    "건축허가":        ["건축법"],
    "건축신고":        ["건축법"],
    "허가":           ["건축법"],
    "신고":           ["건축법"],
    "착공":           ["건축법"],
    "사용승인":        ["건축법"],
    # 면적·높이
    "건폐율":         ["건축법", "국토의 계획 및 이용에 관한 법률"],
    "용적률":         ["건축법", "국토의 계획 및 이용에 관한 법률",
                       "국토의 계획 및 이용에 관한 법률 시행령"],
    "높이제한":        ["건축법", "건축법 시행령"],
    "바닥면적":        ["건축법 시행령"],
    "연면적":         ["건축법 시행령"],
    "대지면적":        ["건축법 시행령"],
    # 구조·안전
    "내화구조":        ["건축물의 피난·방화구조 등의 기준에 관한 규칙"],
    "방화":           ["건축법", "건축물의 피난·방화구조 등의 기준에 관한 규칙"],
    "피난":           ["건축법", "건축물의 피난·방화구조 등의 기준에 관한 규칙"],
    "계단":           ["건축법 시행령", "건축물의 피난·방화구조 등의 기준에 관한 규칙"],
    "복도":           ["건축법 시행령", "건축물의 피난·방화구조 등의 기준에 관한 규칙"],
    # 소방
    "소방":           ["소방시설 설치 및 관리에 관한 법률",
                       "소방시설 설치 및 관리에 관한 법률 시행령"],
    "스프링클러":      ["소방시설 설치 및 관리에 관한 법률 시행령"],
    "소화기":         ["소방시설 설치 및 관리에 관한 법률 시행령"],
    # 주택
    "주택":           ["주택법", "주택법 시행령"],
    "공동주택":        ["주택법", "주택법 시행령"],
    "아파트":         ["주택법", "주택법 시행령"],
    "사업계획승인":    ["주택법"],
    # 국토계획
    "용도지역":        ["국토의 계획 및 이용에 관한 법률",
                       "국토의 계획 및 이용에 관한 법률 시행령"],
    "지구단위계획":    ["국토의 계획 및 이용에 관한 법률"],
    "도시계획":        ["국토의 계획 및 이용에 관한 법률"],
    # 장애인
    "장애인":         ["장애인·노인·임산부 등의 편의증진 보장에 관한 법률"],
    "편의시설":        ["장애인·노인·임산부 등의 편의증진 보장에 관한 법률"],
    # 주차
    "주차":           ["주차장법"],
    "주차장":         ["주차장법"],
    # 기타
    "건설":           ["건설산업기본법"],
    "건설업":         ["건설산업기본법"],
    "설비":           ["건축물의 설비기준 등에 관한 규칙"],
    "환기":           ["건축물의 설비기준 등에 관한 규칙"],
}

DEFAULT_LAWS = ["건축법", "건축법 시행령"]


# ============================================================
# law_hint 파서 (직접 조문 페칭용)
# ============================================================

def _parse_law_hint(hint: str) -> tuple[str, str, bool]:
    """
    "건축법 시행령 별표1" → ("건축법 시행령", "별표1", True)
    "건축법 시행령 제86조제2항" → ("건축법 시행령", "제86조", False)
    Returns: (law_name, article_prefix, is_byeolpyo)
    """
    hint = hint.strip().strip("「」")
    m = re.match(r"^(.+?)\s+(별표\s*\d+)", hint)
    if m:
        return m.group(1).strip(), m.group(2).replace(" ", ""), True
    m = re.match(r"^(.+?)\s+(제\d+조)", hint)
    if m:
        return m.group(1).strip(), m.group(2), False
    return hint, "", False


# ============================================================
# 조문 해석 프레임 로더
# ============================================================

def _normalize_article_key(hint: str) -> str:
    """
    "건축법 시행령 제86조제2항" → "건축법시행령_제86조"
    파일명 prefix 매칭용 키로 변환.
    """
    # 공백 제거 후 첫 번째 "제XX조" 이후를 잘라냄
    key = hint.replace(" ", "").replace("「」", "")
    m = re.match(r'([가-힣]+)(제\d+조)', key)
    if m:
        return f"{m.group(1)}_{m.group(2)}"
    return key


def load_article_roles(
    law_hints: list[str],
    definition_terms: Optional[list[str]] = None,
) -> list[dict]:
    """
    law_hints(Pass 1 식별 조문)에 대응하는 article_roles JSON 파일을 로드.
    파일명 prefix 매칭: "건축법시행령_제86조" → 건축법시행령_제86조*.json

    definition_terms가 있으면 article_type == "정의조항"인 파일도 추가 로드.
    """
    if not ARTICLE_ROLES_DIR.exists():
        return []

    roles = []
    matched_ids: set[str] = set()

    for hint in law_hints:
        prefix = _normalize_article_key(hint)
        for fpath in ARTICLE_ROLES_DIR.glob("*.json"):
            stem = fpath.stem
            if stem.startswith(prefix) and stem not in matched_ids:
                try:
                    data = json.loads(fpath.read_text(encoding="utf-8"))
                    roles.append(data)
                    matched_ids.add(stem)
                except Exception:
                    pass

    # definition_terms가 있으면 정의조항 타입 파일 추가 로드
    if definition_terms:
        for fpath in ARTICLE_ROLES_DIR.glob("*.json"):
            stem = fpath.stem
            if stem in matched_ids:
                continue
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                if data.get("article_type") == "정의조항":
                    roles.append(data)
                    matched_ids.add(stem)
            except Exception:
                pass

    return roles


def format_article_roles(roles: list[dict]) -> str:
    """article_roles를 Pass 2 컨텍스트 문자열로 변환."""
    if not roles:
        return ""

    lines = ["\n=== [조문 해석 프레임] ===",
             "※ 아래는 해당 조문의 요건별 역할과 해석 원칙입니다. "
             "이 프레임을 해석의 출발점으로 삼으세요.\n"]

    ROLE_LABELS = {
        "보호메커니즘": "🔴 보호메커니즘",
        "수혜자격요건": "🔵 수혜자격요건",
        "절차요건":    "🟡 절차요건",
        "정량기준":    "🟢 정량기준",
        "용도정의":    "⚪ 용도정의",
        "적용범위획정": "🟣 적용범위획정",
        "정의조항":    "📖 정의조항",
    }
    SOURCE_LABELS = {
        "해석례": "[해석례]",
        "판례":   "[판례]",
        "입법취지": "[입법취지]",
        "부칙":   "[부칙]",
    }

    for role_doc in roles:
        lines.append(f"▶ {role_doc.get('law', '')} {role_doc.get('article_no', '')}"
                     f" -{role_doc.get('article_summary', '')}")

        for req in role_doc.get("requirements", []):
            label = ROLE_LABELS.get(req.get("role", ""), req.get("role", ""))
            lines.append(f"\n  요건 {req['req_id']}. {req['text']}")
            lines.append(f"  역할: {label}")
            lines.append(f"  이유: {req.get('role_reason', '')}")
            for src in req.get("role_sources", []):
                stag = SOURCE_LABELS.get(src.get("type", ""), f"[{src.get('type','')}]")
                lines.append(f"    {stag} {src.get('ref', '')} → {src.get('point', '')}")

        logic = role_doc.get("interpretation_logic", "")
        if logic:
            lines.append(f"\n  ■ 해석 원칙: {logic}")
            for src in role_doc.get("interpretation_sources", []):
                stag = SOURCE_LABELS.get(src.get("type", ""), f"[{src.get('type','')}]")
                lines.append(f"    {stag} {src.get('ref', '')} → {src.get('point', '')}")

        pc = role_doc.get("penal_connection", {})
        if pc.get("connected"):
            lines.append(f"\n  ⚠ 형벌법규 연결: {pc.get('basis', '')} -{pc.get('implication', '')}")

    return "\n".join(lines)


def layer1_topic_laws(query: str) -> list[str]:
    """Layer 1: 질문 키워드 → 기본 법령 세트"""
    laws = list(DEFAULT_LAWS)
    for keyword, law_list in TOPIC_LAW_MAP.items():
        if keyword in query:
            for law in law_list:
                if law not in laws:
                    laws.append(law)
    return laws


# ============================================================
# Layer 2: 키워드-법령 매핑
# ============================================================

def layer2_keyword_laws(query: str, kw_map: dict) -> list[str]:
    """Layer 2: keyword_law_map에서 추가 법령 특정"""
    extra_laws = []
    for keyword, info in kw_map.items():
        if keyword in query and info.get("confidence", 0) >= 0.6:
            for law in info.get("laws", []):
                if law not in extra_laws:
                    extra_laws.append(law)
    return extra_laws


# ============================================================
# Layer 3: 조문 그래프 1-hop 확장
# ============================================================

def layer3_graph_expand(
    source_nodes: list[str],
    graph: dict,
) -> list[tuple[str, str]]:
    """
    Layer 3: 조문 그래프 1-hop 확장.
    source_nodes: ["건축법:제2조", ...]
    반환: [(law_name, article_no), ...]
    """
    extra = []
    for node_key in source_nodes:
        if node_key in graph:
            for edge in graph[node_key].get("outbound", [])[:3]:
                pair = (edge["law"], edge["article"])
                if pair not in extra:
                    extra.append(pair)
    return extra


# ============================================================
# 하이브리드 검색 엔진
# ============================================================

class HybridSearcher:
    """BM25 + 벡터 하이브리드 검색 (law_articles + qa_precedents + court_cases)"""

    def __init__(self, chroma_client, embed_model):
        self._client    = chroma_client
        self._embed     = embed_model
        self._law_col   = chroma_client.get_collection("law_articles")

        # qa_precedents: labeled_with_doc 인덱스
        try:
            self._qa_col = chroma_client.get_collection("qa_precedents")
        except Exception:
            self._qa_col = None

        # precedents_2026_april: 법제처 해석례 추가분
        try:
            self._prec_col = chroma_client.get_collection("precedents_2026_april")
        except Exception:
            self._prec_col = None

        # court_cases: 판례 파이프라인 구축 후 활성화
        try:
            self._case_col = chroma_client.get_collection("court_cases")
        except Exception:
            self._case_col = None

        # memos: 해석 원칙 메모 RAG (ingest_memos.py로 구축)
        try:
            self._memo_col = chroma_client.get_collection("memos")
        except Exception:
            self._memo_col = None

    def _embed_text(self, text: str) -> list[float]:
        return self._embed.get_text_embedding(text)

    # ----------------------------------------------------------
    # 법령 조문 검색
    # ----------------------------------------------------------

    def search_laws(
        self,
        query: str,
        law_filter: Optional[list[str]],
        top_k: int = 10,
    ) -> list[RetrievedDoc]:
        """law_articles 벡터 검색. law_filter가 있으면 해당 법령만."""
        where_clause = None
        if law_filter:
            if len(law_filter) == 1:
                where_clause = {"law_name": {"$eq": law_filter[0]}}
            else:
                where_clause = {"law_name": {"$in": law_filter}}

        query_emb = self._embed_text(query)
        kwargs = dict(
            query_embeddings=[query_emb],
            n_results=min(top_k, self._law_col.count()),
            include=["documents", "metadatas", "distances"],
        )
        if where_clause:
            kwargs["where"] = where_clause

        try:
            res = self._law_col.query(**kwargs)
        except Exception:
            # 필터 결과 없음 → fallback
            kwargs.pop("where", None)
            res = self._law_col.query(**kwargs)

        docs = []
        for doc_text, meta, dist in zip(
            res["documents"][0], res["metadatas"][0], res["distances"][0]
        ):
            score = max(0.0, 1.0 - dist)
            docs.append(RetrievedDoc(
                source="law_articles",
                law_name=meta.get("law_name", ""),
                article_no=meta.get("article_no", ""),
                content=doc_text,
                score=round(score, 4),
                score_type="vector",
                metadata=dict(meta),
            ))
        return docs

    def bm25_search_laws(
        self,
        query: str,
        law_filter: Optional[list[str]],
        top_k: int = 10,
    ) -> list[RetrievedDoc]:
        """law_articles BM25 키워드 검색"""
        try:
            from rank_bm25 import BM25Okapi
            import numpy as np
        except ImportError:
            return []

        where_clause = None
        if law_filter and len(law_filter) <= 10:
            if len(law_filter) == 1:
                where_clause = {"law_name": {"$eq": law_filter[0]}}
            else:
                where_clause = {"law_name": {"$in": law_filter}}

        fetch_kwargs = dict(include=["documents", "metadatas"], limit=2000)
        if where_clause:
            fetch_kwargs["where"] = where_clause

        try:
            res = self._law_col.get(**fetch_kwargs)
        except Exception:
            fetch_kwargs.pop("where", None)
            res = self._law_col.get(**fetch_kwargs)

        documents = res.get("documents", [])
        metadatas = res.get("metadatas", [])
        if not documents:
            return []

        tokenized = [list(doc) for doc in documents]
        bm25 = BM25Okapi(tokenized)
        scores = bm25.get_scores(list(query))
        top_indices = np.argsort(scores)[::-1][:top_k]

        docs = []
        max_score = float(scores[top_indices[0]]) if len(top_indices) > 0 else 1.0
        for idx in top_indices:
            raw_score = float(scores[idx])
            if raw_score <= 0:
                continue
            norm_score = raw_score / max_score if max_score > 0 else 0.0
            meta = metadatas[idx] if idx < len(metadatas) else {}
            docs.append(RetrievedDoc(
                source="law_articles",
                law_name=meta.get("law_name", ""),
                article_no=meta.get("article_no", ""),
                content=documents[idx],
                score=round(norm_score, 4),
                score_type="bm25",
                metadata=dict(meta),
            ))
        return docs

    # ----------------------------------------------------------
    # 질의회신 선례 검색 (qa_precedents)
    # ----------------------------------------------------------

    def search_qa(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.60,
    ) -> list[RetrievedDoc]:
        """qa_precedents + precedents_2026_april 벡터 검색."""
        query_emb = self._embed_text(query)
        docs = []

        for col, label in [(self._qa_col, "qa_precedents"), (self._prec_col, "precedents_2026_april")]:
            if col is None or col.count() == 0:
                continue
            n = min(top_k * 2, col.count())
            try:
                res = col.query(
                    query_embeddings=[query_emb],
                    n_results=n,
                    include=["documents", "metadatas", "distances"],
                )
            except Exception:
                continue
            for doc_text, meta, dist in zip(
                res["documents"][0], res["metadatas"][0], res["distances"][0]
            ):
                score = max(0.0, 1.0 - dist)
                if score < min_score:
                    continue
                docs.append(RetrievedDoc(
                    source=label,
                    law_name=meta.get("doc_agency", ""),
                    article_no=meta.get("doc_ref", meta.get("doc_code", "")),
                    content=doc_text,
                    score=round(score, 4),
                    score_type="vector",
                    metadata=dict(meta),
                ))

        docs.sort(key=lambda d: -d.score)
        return docs[:top_k]

    # ----------------------------------------------------------
    # 직접 조문 페칭 (law_hints 특정 조문 강제 포함)
    # ----------------------------------------------------------

    def fetch_exact_articles(
        self,
        law_hints: list[str],
        top_n: int = 5,
    ) -> list["RetrievedDoc"]:
        """
        Pass 1 law_hints에 명시된 법령+조문/별표를 메타데이터 직접 쿼리로 가져옴.
        벡터 유사도 순위와 무관하게 항상 포함시킬 조문 보장.
        """
        result: list[RetrievedDoc] = []
        seen: set[str] = set()

        for hint in law_hints:
            law_name, art_prefix, is_byeolpyo = _parse_law_hint(hint)
            if not law_name or not art_prefix:
                continue

            if is_byeolpyo:
                where: dict = {"$and": [
                    {"law_name":    {"$eq": law_name}},
                    {"is_byeolpyo": {"$eq": "true"}},
                ]}
            else:
                where = {"law_name": {"$eq": law_name}}

            try:
                res = self._law_col.get(
                    where=where,
                    limit=500,
                    include=["documents", "metadatas"],
                )
            except Exception:
                continue

            art_key = art_prefix.replace(" ", "").replace("\u3000", "")
            count = 0
            for doc_text, meta in zip(res.get("documents", []), res.get("metadatas", [])):
                art_no = meta.get("article_no", "").replace(" ", "").replace("\u3000", "")
                if art_key not in art_no:
                    continue
                key = f"{meta.get('law_name')}::{meta.get('article_no')}::{doc_text[:40]}"
                if key in seen:
                    continue
                seen.add(key)
                result.append(RetrievedDoc(
                    source="law_articles",
                    law_name=meta.get("law_name", ""),
                    article_no=meta.get("article_no", ""),
                    content=doc_text,
                    score=2.0,          # exact match → 최우선
                    score_type="exact",
                    metadata=dict(meta),
                ))
                count += 1
                if count >= top_n:
                    break

        return result

    # ----------------------------------------------------------
    # 메모 RAG 검색 (memos)
    # ----------------------------------------------------------

    def search_memos(
        self,
        query: str,
        top_k: int = 3,
        min_score: float = 0.45,
    ) -> list[dict]:
        """memos 컬렉션 벡터 검색. 유사도 min_score 이상인 메모 반환."""
        if self._memo_col is None or self._memo_col.count() == 0:
            return []
        query_emb = self._embed_text(query)
        n = min(top_k * 2, self._memo_col.count())
        try:
            res = self._memo_col.query(
                query_embeddings=[query_emb],
                n_results=n,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            return []

        results = []
        for doc_text, meta, dist in zip(
            res["documents"][0], res["metadatas"][0], res["distances"][0]
        ):
            score = max(0.0, 1.0 - dist)
            if score < min_score:
                continue
            results.append({
                "memo_id":  meta.get("memo_id", ""),
                "title":    meta.get("title", ""),
                "tags":     meta.get("tags", ""),
                "linked_to": meta.get("linked_to", ""),
                "content":  doc_text,
                "score":    round(score, 4),
            })

        results.sort(key=lambda x: -x["score"])
        return results[:top_k]

    # ----------------------------------------------------------
    # 판례 검색 (court_cases) -PLAN §4.2
    # ----------------------------------------------------------

    def search_cases_by_type(
        self,
        query: str,
        law_names: list[str],
        relation_type: str,
        top_k: int = 5,
    ) -> list[RetrievedDoc]:
        """
        (법규 × 유형) 쌍 필터로 court_cases 벡터 검색.
        Fallback: 유형 필터 완화 → 법규만 → 전체 검색 (PLAN §4.2)
        """
        if self._case_col is None or self._case_col.count() == 0:
            return []

        query_emb = self._embed_text(query)

        def _run_query(where_clause):
            try:
                kwargs = dict(
                    query_embeddings=[query_emb],
                    n_results=min(top_k * 2, self._case_col.count()),
                    include=["documents", "metadatas", "distances"],
                )
                if where_clause:
                    kwargs["where"] = where_clause
                return self._case_col.query(**kwargs)
            except Exception:
                return None

        def _parse(res) -> list[RetrievedDoc]:
            if res is None:
                return []
            docs = []
            for doc_text, meta, dist in zip(
                res["documents"][0], res["metadatas"][0], res["distances"][0]
            ):
                score = max(0.0, 1.0 - dist)
                docs.append(RetrievedDoc(
                    source="court_cases",
                    law_name=meta.get("cited_laws_str", ""),
                    article_no=meta.get("case_id", ""),
                    content=doc_text,
                    score=round(score, 4),
                    score_type="vector",
                    metadata=dict(meta),
                ))
            return docs

        law_name = law_names[0] if law_names else ""

        # 1차: law + relation_type 필터
        if law_name and relation_type:
            where = {"$and": [
                {"cited_laws_str": {"$contains": law_name}},
                {"relation_types":  {"$contains": relation_type}},
            ]}
            docs = _parse(_run_query(where))
            if len(docs) >= 2:
                return docs[:top_k]

        # Fallback 1: 법규만
        if law_name:
            where = {"cited_laws_str": {"$contains": law_name}}
            docs = _parse(_run_query(where))
            if len(docs) >= 1:
                return docs[:top_k]

        # Fallback 2: 전체
        return _parse(_run_query(None))[:top_k]

    def bm25_search_cases(self, query: str, top_k: int = 5) -> list[RetrievedDoc]:
        """court_cases BM25 키워드 검색"""
        if self._case_col is None or self._case_col.count() == 0:
            return []

        try:
            from rank_bm25 import BM25Okapi
            import numpy as np
        except ImportError:
            return []

        res = self._case_col.get(include=["documents", "metadatas"], limit=5000)
        documents = res.get("documents", [])
        metadatas = res.get("metadatas", [])
        if not documents:
            return []

        tokenized = [list(doc) for doc in documents]
        bm25 = BM25Okapi(tokenized)
        scores = bm25.get_scores(list(query))
        top_indices = np.argsort(scores)[::-1][:top_k]

        docs = []
        max_score = float(scores[top_indices[0]]) if len(top_indices) > 0 else 1.0
        for idx in top_indices:
            raw_score = float(scores[idx])
            if raw_score <= 0:
                continue
            norm_score = raw_score / max_score if max_score > 0 else 0.0
            meta = metadatas[idx] if idx < len(metadatas) else {}
            docs.append(RetrievedDoc(
                source="court_cases",
                law_name=meta.get("cited_laws_str", ""),
                article_no=meta.get("case_id", ""),
                content=documents[idx],
                score=round(norm_score, 4),
                score_type="bm25",
                metadata=dict(meta),
            ))
        return docs


# ============================================================
# RRF 병합
# ============================================================

def merge_results(
    vector_docs: list[RetrievedDoc],
    bm25_docs: list[RetrievedDoc],
    top_k: int,
    vector_weight: float = 0.6,
    bm25_weight: float = 0.4,
) -> list[RetrievedDoc]:
    """벡터 + BM25 결과 RRF 융합"""
    rrf_k = 60
    combined: dict[str, dict] = {}

    def doc_key(doc: RetrievedDoc) -> str:
        return f"{doc.law_name}::{doc.article_no}::{doc.content[:50]}"

    for rank, doc in enumerate(vector_docs, 1):
        k = doc_key(doc)
        if k not in combined:
            combined[k] = {"doc": doc, "rrf_score": 0.0}
        combined[k]["rrf_score"] += vector_weight / (rrf_k + rank)

    for rank, doc in enumerate(bm25_docs, 1):
        k = doc_key(doc)
        if k not in combined:
            combined[k] = {"doc": doc, "rrf_score": 0.0}
        combined[k]["rrf_score"] += bm25_weight / (rrf_k + rank)

    sorted_items = sorted(combined.values(), key=lambda x: -x["rrf_score"])
    results = []
    for item in sorted_items[:top_k]:
        doc = item["doc"]
        doc.score = round(item["rrf_score"] * 100, 4)
        doc.score_type = "hybrid"
        results.append(doc)
    return results


def merge_case_results(
    typed_results: list[tuple[list[RetrievedDoc], float]],
    bm25_docs: list[RetrievedDoc],
    top_k: int,
) -> list[RetrievedDoc]:
    """
    복수 유형별 판례 검색 결과 + BM25 RRF 병합 (PLAN §4.2).
    typed_results: [(docs, weight), ...]
    중복 판례는 최고 가중 점수 채택.
    """
    rrf_k = 60
    combined: dict[str, dict] = {}

    def doc_key(doc: RetrievedDoc) -> str:
        case_id = doc.metadata.get("case_id", doc.article_no)
        return f"case::{case_id}::{doc.content[:50]}"

    for docs, weight in typed_results:
        for rank, doc in enumerate(docs, 1):
            k = doc_key(doc)
            contribution = weight * 0.6 / (rrf_k + rank)
            if k not in combined:
                combined[k] = {"doc": doc, "rrf_score": 0.0}
            # 중복 시 최고 가중 점수 채택
            combined[k]["rrf_score"] = max(combined[k]["rrf_score"], contribution)

    for rank, doc in enumerate(bm25_docs, 1):
        k = doc_key(doc)
        contribution = 0.4 / (rrf_k + rank)
        if k not in combined:
            combined[k] = {"doc": doc, "rrf_score": 0.0}
        combined[k]["rrf_score"] += contribution

    sorted_items = sorted(combined.values(), key=lambda x: -x["rrf_score"])
    results = []
    for item in sorted_items[:top_k]:
        doc = item["doc"]
        doc.score = round(item["rrf_score"] * 100, 4)
        doc.score_type = "hybrid"
        results.append(doc)
    return results


# ============================================================
# 메인 Retriever
# ============================================================

class Retriever:
    """
    3-Layer 법령 라우팅 + 하이브리드 검색 (법령 조문 + 질의회신 + 판례).

    반환: (law_docs, qa_docs, case_docs)
      - qa_docs: qa_precedents 컬렉션에서 유사도 0.60 이상 선례 (doc_ref 포함)
      - case_docs: court_cases 구축 후 활성화, 그 전까지 []
    """

    def __init__(self, top_k_law: int = 7, top_k_case: int = 5):
        self.top_k_law  = top_k_law
        self.top_k_case = top_k_case
        self._kw_map    = self._load_json(MAP_PATH)
        self._graph     = self._load_json(GRAPH_PATH)
        self._memos      = self._load_memos()
        self._amendments = self._load_amendments()
        self._searcher   = self._init_searcher()

    @staticmethod
    def _load_json(path: Path) -> dict:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        print(f"[WARN] 파일 없음: {path}")
        return {}

    @staticmethod
    def _load_memos() -> list[dict]:
        """memos.jsonl 전체 로드 (fetch_linked_memos용 캐시)."""
        if not MEMOS_PATH.exists():
            return []
        memos = []
        with open(MEMOS_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    memos.append(json.loads(line))
                except Exception:
                    pass
        return memos

    @staticmethod
    def _load_amendments() -> list[dict]:
        """amendments.jsonl 전체 로드 (fetch_linked_amendments용 캐시)."""
        if not AMENDMENTS_PATH.exists():
            return []
        records = []
        with open(AMENDMENTS_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
        return records

    def _init_searcher(self) -> HybridSearcher:
        print("임베딩 모델 로드 중...")
        embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
        print("Chroma DB 연결 중...")
        chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        return HybridSearcher(chroma_client, embed_model)

    def retrieve(
        self,
        query: str,
        question_type: Optional[str] = None,
        extra_article_nodes: Optional[list[str]] = None,
        relation_types: Optional[list[dict]] = None,
        law_hints: Optional[list[str]] = None,
        definition_terms: Optional[list[str]] = None,
        top_k_law: Optional[int] = None,
        top_k_case: Optional[int] = None,
    ) -> tuple[list[RetrievedDoc], list[RetrievedDoc], list[RetrievedDoc]]:
        """
        Parameters
        ----------
        query              : 사용자 질문 (검색용)
        question_type      : "단일조문형" | "복수조문탐색형" | "조건분기형"
        extra_article_nodes: Pass 1이 특정한 조문 노드 ["건축법:제2조", ...]
        relation_types     : Pass 1이 분류한 관계 유형 (PLAN §4.1)
                             예: [{"type": "DEF_EXP", "weight": 1.0}, ...]
        law_hints          : Pass 1이 특정한 법령 힌트 ["건축법 제2조", ...]

        Returns
        -------
        (law_docs, qa_docs, case_docs)
        """
        top_k_law  = top_k_law  or self.top_k_law
        top_k_case = top_k_case or self.top_k_case

        # 질문 유형에 따라 top_k 조정
        if question_type == "단일조문형":
            top_k_law = max(3, top_k_law - 2)
        elif question_type == "복수조문탐색형":
            top_k_law = top_k_law + 3
        elif question_type == "조건분기형":
            top_k_law = top_k_law + 1

        # ── Layer 1 ────────────────────────────────────────
        base_laws = layer1_topic_laws(query)

        # ── Layer 2 ────────────────────────────────────────
        extra_laws = layer2_keyword_laws(query, self._kw_map)
        all_laws = list(dict.fromkeys(base_laws + extra_laws))

        # ── Layer 3 ────────────────────────────────────────
        if extra_article_nodes and self._graph:
            graph_extras = layer3_graph_expand(extra_article_nodes, self._graph)
            for law, _ in graph_extras:
                if law not in all_laws:
                    all_laws.append(law)

        # ── 법령 조문 하이브리드 검색 ─────────────────────
        law_filter = all_laws if all_laws else None
        # law_hints + definition_terms를 검색 쿼리에 보강
        search_q = query
        if law_hints:
            search_q += " " + " ".join(law_hints[:3])
        if definition_terms:
            search_q += " " + " ".join(definition_terms[:3])

        vector_law = self._searcher.search_laws(search_q, law_filter, top_k=top_k_law * 2)
        bm25_law   = self._searcher.bm25_search_laws(search_q, law_filter, top_k=top_k_law * 2)

        if bm25_law:
            law_docs = merge_results(vector_law, bm25_law, top_k=top_k_law)
        else:
            law_docs = vector_law[:top_k_law]

        # ── 직접 조문 페칭 (law_hints 명시 조문 강제 포함) ─
        if law_hints:
            exact_docs = self._searcher.fetch_exact_articles(law_hints, top_n=5)
            if exact_docs:
                existing = {
                    f"{d.law_name}::{d.article_no}::{d.content[:40]}"
                    for d in law_docs
                }
                new_exact = [
                    d for d in exact_docs
                    if f"{d.law_name}::{d.article_no}::{d.content[:40]}" not in existing
                ]
                law_docs = new_exact + law_docs   # exact match를 컨텍스트 앞에 배치

        # ── 질의회신 선례 검색 (qa_precedents) ────────────
        qa_docs = self._searcher.search_qa(search_q, top_k=5)

        # ── 판례 검색 (court_cases, PLAN §4.2) ────────────
        case_docs = self._search_cases(query, all_laws, relation_types, top_k_case)

        return law_docs, qa_docs, case_docs

    def _search_cases(
        self,
        query: str,
        all_laws: list[str],
        relation_types: Optional[list[dict]],
        top_k: int,
    ) -> list[RetrievedDoc]:
        """
        weight ≥ 0.5인 유형별로 (법규 × 유형) 쌍 검색 후 RRF 병합.
        weight < 0.5는 court_cases 구축 후 부스트 계수로 활용 예정.
        """
        if not relation_types:
            return []

        # 법령명만 추출 (조문번호 제거)
        law_names = list(dict.fromkeys(
            re.split(r'\s+제\d+', law)[0].strip()
            for law in all_laws
        ))

        active = [rt for rt in relation_types if rt.get("weight", 0) >= 0.5]
        if not active:
            return []

        typed_results = []
        for rt in active:
            docs = self._searcher.search_cases_by_type(
                query, law_names, rt["type"], top_k=top_k
            )
            typed_results.append((docs, rt.get("weight", 1.0)))

        bm25_docs = self._searcher.bm25_search_cases(query, top_k=top_k)
        return merge_case_results(typed_results, bm25_docs, top_k=top_k)

    def retrieve_memos(self, query: str, top_k: int = 3) -> list[dict]:
        """질의와 관련된 해석 원칙 메모 검색 (memos 컬렉션)."""
        return self._searcher.search_memos(query, top_k=top_k)

    def fetch_linked_memos(
        self,
        law_docs: list[RetrievedDoc],
        qa_docs:  list[RetrievedDoc],
        case_docs: list[RetrievedDoc],
    ) -> list[dict]:
        """
        retrieved docs와 메모의 linked_to / 태그를 결정론적으로 매칭.
        벡터 검색 없이 — 검색된 판례·선례·법령 조문이 트리거.

        매칭 규칙 (OR):
          1. memo.linked_to에 검색된 판례 case_id 또는 선례 doc_ref 포함
          2. memo.tags의 법령+조문 코드가 검색된 law_docs에 있음
        """
        if not self._memos:
            return []

        # ── 검색된 ID 집합 (판례 + 선례) ─────────────────────
        retrieved_ids: set[str] = set()
        for d in case_docs:
            cid = d.metadata.get("case_id", d.article_no)
            if cid:
                retrieved_ids.add(cid)
        for d in qa_docs:
            ref = d.metadata.get("doc_ref", "") or d.metadata.get("doc_code", "")
            if ref:
                retrieved_ids.add(ref)

        # ── 검색된 법령조문 키 집합 ───────────────────────────
        # key 형식: "<법령명(공백제거)><제XX조>"  예: "건축법제11조"
        # LAW_ABBREV_MAP의 역방향도 포함
        _full_to_abbrev: dict[str, str] = {
            v.replace(" ", ""): k
            for k, v in LAW_ABBREV_MAP.items()
        }
        retrieved_law_keys: set[str] = set()
        for d in law_docs:
            law_norm = d.law_name.replace(" ", "")
            m = re.match(r'(제\d+조)', d.article_no.replace(" ", ""))
            if not m:
                continue
            art = m.group(1)
            retrieved_law_keys.add(law_norm + art)
            # 알려진 축약어가 있으면 축약어 버전도 추가
            abbrev = _full_to_abbrev.get(law_norm)
            if abbrev:
                retrieved_law_keys.add(abbrev + art)

        # ── 메모 매칭 ─────────────────────────────────────────
        matched: list[dict] = []
        seen_ids: set[str] = set()

        for memo in self._memos:
            mid = memo.get("memo_id", "")
            if mid in seen_ids:
                continue

            # 규칙 1: linked_to 매칭
            linked_to = memo.get("linked_to", [])
            if isinstance(linked_to, str):
                linked_to = [linked_to]
            if any(lt in retrieved_ids for lt in linked_to):
                matched.append(memo)
                seen_ids.add(mid)
                continue

            # 규칙 2: 태그 법령조문 매칭
            tags = memo.get("tags", [])
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",")]
            for tag in tags:
                tag_norm = tag.replace(" ", "")
                if any(tag_norm.startswith(key) for key in retrieved_law_keys):
                    matched.append(memo)
                    seen_ids.add(mid)
                    break

        return matched

    def fetch_linked_amendments(
        self,
        law_docs: list[RetrievedDoc],
    ) -> list[dict]:
        """
        검색된 law_docs의 법령명+조문번호와 amendments.jsonl의 개정조문을 매칭.
        목적론적 해석 컨텍스트로 주입할 개정연혁 반환.

        매칭 규칙:
          amendment.law_name == doc.law_name
          AND amendment.개정조문 중 하나가 doc.article_no의 제XX조 prefix와 일치
        """
        if not self._amendments or not law_docs:
            return []

        # 검색된 (법령명, 제XX조) 쌍 수집
        retrieved_pairs: set[tuple[str, str]] = set()
        for d in law_docs:
            m = re.match(r'(제\d+조)', d.article_no.replace(" ", ""))
            if m:
                retrieved_pairs.add((d.law_name, m.group(1)))

        matched: list[dict] = []
        seen_ids: set[str] = set()

        for rec in self._amendments:
            aid = rec.get("amendment_id", "")
            if aid in seen_ids:
                continue
            law_name = rec.get("law_name", "")
            개정조문 = rec.get("개정조문", [])

            for art in 개정조문:
                art_norm = art.replace(" ", "")
                m = re.match(r'(제\d+조)', art_norm)
                if not m:
                    continue
                art_prefix = m.group(1)
                if (law_name, art_prefix) in retrieved_pairs:
                    matched.append(rec)
                    seen_ids.add(aid)
                    break

        return matched

    def get_article_roles(
        self,
        law_hints: list[str],
        definition_terms: Optional[list[str]] = None,
    ) -> list[dict]:
        """law_hints + definition_terms로 조문 해석 프레임 JSON 로드."""
        return load_article_roles(law_hints, definition_terms=definition_terms)

    def format_context(
        self,
        law_docs: list[RetrievedDoc],
        qa_docs: list[RetrievedDoc],
        case_docs: list[RetrievedDoc],
        article_roles: Optional[list[dict]] = None,
        memo_docs: Optional[list[dict]] = None,
        amendment_docs: Optional[list[dict]] = None,
    ) -> str:
        """
        검색 결과를 Pass 2 LLM 컨텍스트로 포맷 (PLAN §2.2).
        0층: 조문 해석 프레임 / 1층: 법령 조문 / 2층: 질의회신 선례 / 3층: 판례
        memo층: 관련 해석 원칙 메모 (always-on이 아닌 케이스-특정 원칙)
        """
        lines = []

        # ── 개정연혁층: 목적론적 해석 재료 ──────────────
        if amendment_docs:
            lines.append("=== [관련 개정연혁] ===")
            lines.append(
                "※ 아래는 검색된 조문의 개정 이유 및 입법 목적입니다. "
                "목적론적 해석 시 반드시 참조하세요."
            )
            for rec in amendment_docs:
                lines.append(
                    f"\n[{rec.get('law_name','')} {rec.get('시행일','')} "
                    f"{rec.get('공포번호','')}]"
                )
                lines.append(f"개정이유: {rec.get('개정이유','')}")
                키포인트 = rec.get('목적론적_키포인트', '')
                if 키포인트:
                    lines.append(f"목적론적 키포인트: {키포인트}")
                주요내용 = rec.get('주요내용', [])
                if 주요내용:
                    lines.append("주요 개정 내용:")
                    for item in 주요내용:
                        조문 = ", ".join(item.get('조문', []))
                        lines.append(f"  · [{조문}] {item.get('항목','')}: {item.get('내용','')}")
                연동 = rec.get('연동_조문_주의', '')
                if 연동:
                    lines.append(f"※ 연동 개정: {연동}")

        # ── memo층: 관련 해석 원칙 메모 ─────────────────
        if memo_docs:
            lines.append("=== [관련 해석 원칙 메모] ===")
            lines.append(
                "아래는 유사 사안에서 확립된 해석 원칙입니다. "
                "본 건과 관련된 원칙이 있으면 적용하세요:"
            )
            for m in memo_docs:
                mid   = m.get("memo_id", "")
                title = m.get("title", "")
                lines.append(f"\n[{mid}] {title}")
                lines.append(m.get("content", ""))

        # ── 0층: 조문 해석 프레임 ────────────────────────
        if article_roles:
            roles_text = format_article_roles(article_roles)
            if roles_text:
                lines.append(roles_text)

        # ── 1층: 법령 조문 ──────────────────────────────
        exact_docs  = [d for d in law_docs if d.score_type == "exact"]
        vector_docs = [d for d in law_docs if d.score_type != "exact"]

        if exact_docs:
            lines.append("=== [직접 참조 조문] ===")
            lines.append(
                "※ 아래는 질문에서 특정된 조문을 DB에서 직접 가져온 것입니다. "
                "이 내용을 답변의 1차 근거로 삼으세요."
            )
            for i, doc in enumerate(exact_docs, 1):
                lines.append(f"\n[직접{i}] {doc.law_name} {doc.article_no}")
                lines.append(doc.content)

        if vector_docs:
            lines.append("\n=== [관련 법령 조문] ===")
            for i, doc in enumerate(vector_docs, 1):
                lines.append(f"\n[{i}] {doc.law_name} {doc.article_no}")
                lines.append(doc.content)

        # ── 2층: 질의회신 선례 ──────────────────────────
        if qa_docs:
            lines.append("\n=== [유사 질의회신 선례] ===")
            for i, doc in enumerate(qa_docs, 1):
                meta = doc.metadata
                doc_ref    = meta.get("doc_ref", "")
                doc_agency = meta.get("doc_agency", "")
                doc_date   = meta.get("doc_date", "")
                header = f"\n[선례{i}]"
                if doc_ref:
                    header += f" {doc_ref}"
                elif doc_agency:
                    label = doc_agency
                    if doc_date:
                        label += f" ({doc_date})"
                    header += f" {label}"
                lines.append(header)
                if meta.get("question"):
                    lines.append(f"질문: {meta['question']}")
                lines.append(doc.content)

        # ── 3층: 판례 ────────────────────────────────
        if case_docs:
            lines.append("\n=== [참조 판례 풀] ===")
            lines.append(
                "아래는 (법규 × 유형) 쌍으로 검색된 관련 판례입니다.\n"
                "법리 해석 중 조문만으로 판단이 애매한 지점에서만 인용하세요.\n"
                "확장된 정의를 원용할 경우, 해당 판례의 조건이 본 건과 일치하는지 반드시 검토하세요."
            )
            for i, doc in enumerate(case_docs, 1):
                meta      = doc.metadata
                case_id   = meta.get("case_id", "")
                court     = meta.get("court", "")
                dec_date  = meta.get("decision_date", "")
                rel_types = meta.get("relation_types", "")
                rel_names = ", ".join(
                    RELATION_TYPES.get(t.strip(), t.strip())
                    for t in rel_types.split(",") if t.strip()
                ) if rel_types else ""
                cited = meta.get("cited_laws_str", "")

                header_parts = [x for x in [court, case_id] if x]
                if dec_date:
                    header_parts.append(f"({dec_date} 선고)")
                lines.append(f"\n[판례{i}] {' '.join(header_parts)}")
                if rel_names:
                    lines.append(f"  유형: {rel_names} | 법규: {cited}")
                lines.append(doc.content)
                if meta.get("apply_condition"):
                    lines.append(f"  적용 조건: {meta['apply_condition']}")

        return "\n".join(lines)


# ============================================================
# 테스트 실행
# ============================================================

def run_test():
    print("=" * 60)
    print("05_Retriever 테스트")
    print("=" * 60)

    retriever = Retriever()

    test_queries = [
        (
            "다중이용업소의 용도변경 시 건축허가 대상인가요?",
            "복수조문탐색형",
            [{"type": "SCOPE_CL", "weight": 1.0}, {"type": "REQ_INT", "weight": 0.7}],
        ),
        (
            "건축법상 용적률 산정 시 지하층 면적은 포함되나요?",
            "단일조문형",
            [{"type": "DEF_EXP", "weight": 1.0}],
        ),
        (
            "근린생활시설을 숙박시설로 변경하려면 어떤 절차가 필요한가요?",
            "복수조문탐색형",
            [{"type": "SCOPE_CL", "weight": 1.0}, {"type": "PROC_DISC", "weight": 0.6}],
        ),
    ]

    for query, qtype, rel_types in test_queries:
        print(f"\n질문: {query}")
        print(f"유형: {qtype} | 관계: {[r['type'] for r in rel_types]}")
        law_docs, _, case_docs = retriever.retrieve(
            query, question_type=qtype, relation_types=rel_types
        )
        print(f"\n[법령 {len(law_docs)}건]")
        for doc in law_docs[:3]:
            print(f"  {doc.law_name} {doc.article_no}  (score={doc.score:.4f})")
            print(f"    {doc.content[:80]}...")
        print(f"[판례 {len(case_docs)}건] (court_cases 컬렉션 구축 후 활성화)")
        print("-" * 60)


if __name__ == "__main__":
    run_test()
