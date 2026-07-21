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
BASE_DIR        = Path(__file__).parent.parent
DATA_DIR        = BASE_DIR / "data"
CHROMA_DIR      = Path(os.environ.get("CHROMA_DB_PATH", str(DATA_DIR / "chroma_db")))
MAP_PATH        = DATA_DIR / "keyword_law_map.json"
GRAPH_PATH      = DATA_DIR / "article_graph.json"
DELEGATION_PATH = DATA_DIR / "delegation_graph.json"
ARTICLE_ROLES_DIR = DATA_DIR / "article_roles"

EMBED_MODEL_NAME  = "jhgan/ko-sroberta-multitask"
MEMOS_PATH        = DATA_DIR / "memos.jsonl"
PRINCIPLES_PATH   = DATA_DIR / "principles.jsonl"
AMENDMENTS_PATH   = DATA_DIR / "law_amendments" / "amendments.jsonl"


# ============================================================
# 시점 컷오프 (eval 전용) — 미래 자료 판별
# ============================================================

def _qa_code_key(code: str):
    """법제처 안건번호 'YY-NNNN' → (연도2자리, 일련번호) 튜플. 형식 불일치 시 None."""
    m = re.match(r"(\d{2})-(\d{4})", str(code))
    return (int(m.group(1)), int(m.group(2))) if m else None


def _doc_is_after_cutoff(meta: dict, as_of_date: Optional[str],
                         as_of_code: Optional[str] = None) -> bool:
    """meta가 가리키는 해석례/판례가 기준 시점보다 미래이면 True.

    - as_of_date('YYYY-MM-DD')가 있으면 doc_date/decision_date와 ISO 비교.
      retrieved 날짜가 비면 doc_code 연도로 보수적 판단(같은 해는 통과).
    - as_of_date가 없고 as_of_code('YY-NNNN', 평가 대상 안건번호)만 있으면
      doc_code 안건번호의 (연도, 일련번호)로 비교. 평가 대상의 doc_date가
      비어 컷오프가 무력화되는 것을 막는다(법제처 안건번호 = 처리 순서).
    - 어느 쪽도 판단 불가하면 통과(False) — 과배제 방지.
    """
    if not as_of_date and not as_of_code:
        return False
    dd   = meta.get("doc_date", "") or meta.get("decision_date", "")
    code = meta.get("doc_code", "") or meta.get("case_id", "")

    if as_of_date:
        if dd:
            return dd > as_of_date
        key = _qa_code_key(code)
        if key:
            try:
                return key[0] > int(as_of_date[:4]) - 2000
            except ValueError:
                return False
        return False

    # as_of_date 없음 → 안건번호 (연도, 일련번호) 비교
    a_key = _qa_code_key(as_of_code)
    r_key = _qa_code_key(code)
    if a_key and r_key:
        return r_key > a_key
    return False

_PHRASE_RULES_PATH = DATA_DIR / "phrase_principles.json"
_phrase_rules_cache: Optional[list] = None


def _load_phrase_rules() -> list:
    """문형→원칙 해석례 매핑 로딩 (data/phrase_principles.json, 1회 캐시)."""
    global _phrase_rules_cache
    if _phrase_rules_cache is not None:
        return _phrase_rules_cache
    try:
        _phrase_rules_cache = json.loads(
            _PHRASE_RULES_PATH.read_text(encoding="utf-8")).get("rules", [])
    except Exception:
        _phrase_rules_cache = []
    return _phrase_rules_cache


def _phrase_principle_codes(query: str, law_docs: list) -> list[str]:
    """법정 문형 감지 → 주입할 원칙 해석례 doc_code 목록.

    문형('각 호의 어느 하나'·단서·'등')의 해석 원칙은 도메인 어휘와 직교라
    상황 서술형 질문에서 검색 순위 밖으로 밀린다. text_pattern(질문+검색
    조문)과 query_signals(질문 — 쟁점 신호)가 함께 잡힐 때만 발화해
    일상 질의에 대한 과주입을 막는다."""
    rules = _load_phrase_rules()
    if not rules or not query:
        return []
    law_text = " ".join(str(getattr(d, "content", ""))[:1500] for d in (law_docs or [])[:12])
    haystack = query + "\n" + law_text
    out: list[str] = []
    for r in rules:
        try:
            sig = r.get("query_signals", "")
            if sig and not re.search(sig, query):
                continue
            pat = r.get("text_pattern", "")
            if pat and not re.search(pat, haystack):
                continue
        except re.error:
            continue
        for c in r.get("codes", []):
            if c not in out:
                out.append(c)
    return out


def _attach_cite_label(meta: dict) -> None:
    """해석례 메타에 답변 인용 표기(cite_label)를 부착한다 — 시스템 전체의 단일 생성점.

    법제처 해석례(doc_code 'NN-NNNN')는 기존 '법제처 NN-NNNN' 관례를 그대로 쓰고,
    번호 없는 부처·지자체 회신(서울시질의회신 등, doc_ref '[국토교통부 / '12.07.30.]'
    '[건축기획팀-7544 / '06.12.15.]')은 '국토교통부 2012.07.30. 회신' 형식을 만든다.
    이 라벨은 (1) 컨텍스트 헤더에 표기돼 모델이 그대로 인용하고, (2) 소독기
    (strip_unverified_citations)가 보호하며, (3) chainlit이 팝업을 거는 데 쓰인다.
    이전에는 이 유형의 선례를 인용할 공식 형식이 없어 '(관련 국토교통부 회신)' 같은
    무번호 표현으로 뭉개지고 팝업도 안 걸렸다."""
    if meta.get("cite_label"):
        return
    code = str(meta.get("doc_code", "") or "")
    if re.fullmatch(r"\d{2}-\d{4}", code):
        meta["cite_label"] = f"법제처 {code}"
        return
    ref = str(meta.get("doc_ref", "") or "").strip().strip("[]")
    org, date = "", ""
    if "/" in ref:
        org, date = (p.strip() for p in ref.split("/", 1))
    else:
        org = ref or str(meta.get("doc_agency", "") or "").strip()
        date = str(meta.get("doc_date", "") or "").strip()
    # 'YY.MM.DD. → YYYY.MM.DD.
    # 실데이터 아포스트로피는 U+2018(')이 2,325건으로 지배적이나 오타로
    # ''(이중)·'`(백틱 혼입)도 존재 → 반복 허용. '97 같은 90년대 건도 있어
    # 50 기준으로 세기 판정.
    m = re.match(r"[‘’'`]*(\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?", date)
    if m:
        yy, mm, dd = m.groups()
        century = "19" if int(yy) >= 50 else "20"
        date = f"{century}{yy}.{int(mm):02d}.{int(dd):02d}."
    elif re.match(r"\d{4}-\d{2}-\d{2}", date):
        date = date[:10].replace("-", ".") + "."
    if org:
        label = f"{org} {date} 회신".replace("  ", " ").strip()
        # 서울시 건축조례 질의회신집 수록분은 출처집을 표기에 명기
        # ("국토교통부 '12.07.30. 회신/서울시질의회신집" — 2026-07-21 사용자 지정).
        # 법제처 해석례(NN-NNNN)는 위에서 조기 반환되므로 미적용.
        src = str(meta.get("source_file", "") or "")
        if src.startswith(("labeled_with_doc", "seoul_qa")):
            label += "/서울시질의회신집"
        meta["cite_label"] = label
    # org조차 없으면 라벨 없음 — 일반 표현으로만 서술됨


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
    "도시정비법":      "도시 및 주거환경정비법",
    "도시정비법시행령": "도시 및 주거환경정비법 시행령",
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
    # 도시정비
    "재개발":         ["도시 및 주거환경정비법", "도시 및 주거환경정비법 시행령"],
    "재건축":         ["도시 및 주거환경정비법", "도시 및 주거환경정비법 시행령"],
    "정비사업":       ["도시 및 주거환경정비법", "도시 및 주거환경정비법 시행령"],
    "관리처분계획":   ["도시 및 주거환경정비법"],
    "타당성검증":     ["도시 및 주거환경정비법"],
    "사업시행인가":   ["도시 및 주거환경정비법"],
    "조합설립":       ["도시 및 주거환경정비법"],
    "토지등소유자":   ["도시 및 주거환경정비법"],
    "분양공고":       ["도시 및 주거환경정비법"],
    "분양신청":       ["도시 및 주거환경정비법"],
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

def _normalize_middot(s: str) -> str:
    """법령명 가운뎃점 변종을 U+00B7(·)로 통일.
    국가법령정보센터 PDF는 한글 가운뎃점 ㆍ(U+318D)를 쓰는데 코드 상수·검색 키는
    라틴 ·(U+00B7)을 써서 ChromaDB $eq 매칭이 빗나가 핵심 조문이 검색 누락됐었음."""
    return s.replace("ㆍ", "·").replace("・", "·").replace("‧", "·")


_REGION_PAT = re.compile(
    r'^([가-힣]+(?:특별자치시|특별자치도|광역시|특별시|시|군|구|도))(?=\s|$)'
)


def _extract_region(law_name: str) -> str:
    """조례 법령명 앞부분에서 지역명 추출 (예: '남양주시 건축 조례' → '남양주시').
    다른 대화의 질문에 이 지역명이 언급되면 조례 스레드 스코프 예외를 허용하는 데 쓰인다."""
    m = _REGION_PAT.match(law_name.strip())
    return m.group(1) if m else ""


def _parse_law_hint(hint: str) -> tuple[str, str, bool]:
    """
    "건축법 시행령 별표1" → ("건축법 시행령", "별표1", True)
    "건축법 시행령 제86조제2항" → ("건축법 시행령", "제86조", False)
    "건축법 시행령 제3조의2" → ("건축법 시행령", "제3조의2", False)
    Returns: (law_name, article_prefix, is_byeolpyo)

    의M(가지조문)을 보존해야 사각지대 패치가 제3조의2 힌트에 제3조를(다른 조문)
    잘못 반환하지 않는다. fetch_exact_articles의 부분문자열 매칭도 더 정밀해짐.
    """
    hint = _normalize_middot(hint.strip().strip("「」"))
    m = re.match(r"^(.+?)\s+(별표\s*\d+)", hint)
    if m:
        return m.group(1).strip(), m.group(2).replace(" ", ""), True
    m = re.match(r"^(.+?)\s+(제\d+조(?:의\d+)?)", hint)
    if m:
        return m.group(1).strip(), m.group(2), False
    return hint, "", False


# ============================================================
# 상호참조 확장 (경량 1-hop): 조문 본문이 명시적으로 가리키는 조문 자동 포함
# ============================================================

def _related_laws(law_name: str) -> dict[str, str]:
    """조문이 속한 법령을 기준으로 상대참조('법'/'영'/'규칙')가 가리키는 법령명을 만든다.

    '건축법 시행령'의 본문 속 '법 제N조' → '건축법 제N조'(모법),
    '건축법'의 본문 속 '영 제N조' → '건축법 시행령 제N조'(시행령).
    시행령·시행규칙 접미사가 없으면 base를 법령명 자체로 본다(법 조문의 '이 법 제N조'
    자기참조 등). 접미사 없는 규칙명 등에서 잘못 유도한 이름이 실제 DB에 없으면
    fetch_exact_articles가 조용히 빈 결과를 돌려주므로 오류로 이어지지 않는다."""
    name = law_name.strip()
    for suf in ("시행규칙", "시행령"):
        if name.endswith(suf):
            base = name[: -len(suf)].strip()
            break
    else:
        base = name
    return {"법": base, "영": f"{base} 시행령", "규칙": f"{base} 시행규칙"}


# 조문 본문 상호참조 추출 패턴.
#   (1) 「법령명」 제N조[의M]   — 다른 법령 명시 참조(명확)
#   (2) [이|같은] {법|영|규칙}[시행령|시행규칙] 제N조[의M] — 모법·시행령 상대참조
# '같은 법/영/규칙'(선행 인용 법령을 가리켜 대상이 모호)은 의도적으로 제외한다.
_CROSSREF_PAT = re.compile(
    r'「([^」]{2,40})」\s*(제\d+조(?:의\d+)?)'
    r'|(?<![가-힣])(같은\s*법\s*시행규칙|같은\s*법\s*시행령'
    r'|이\s*법|이\s*영|이\s*규칙|법|영|규칙)\s*(제\d+조(?:의\d+)?)'
)


def _extract_crossref_hints(law_docs, max_hints: int = 10) -> list[str]:
    """검색된 조문 본문이 명시적으로 가리키는 '다른 조문'을 (법령명 제N조) 힌트로 추출.

    1-hop만(추출은 원본 law_docs 본문에서만) 수행하고, 여러 조문이 공통으로 가리키는
    조문일수록(참조 빈도↑) 우선한다. 이미 law_docs에 있는 조문은 제외. 상대참조
    ('법'/'영'/'이 영' 등)는 그 조문이 속한 법령을 기준으로 해소한다."""
    have = {(d.law_name.strip(), d.article_no.replace(" ", "")) for d in law_docs}
    freq: dict[tuple[str, str], int] = {}
    order: dict[tuple[str, str], int] = {}
    seq = 0
    for doc in law_docs:
        rel = _related_laws(doc.law_name)
        for m in _CROSSREF_PAT.finditer(doc.content or ""):
            if m.group(1):                        # 「법령명」 제N조
                # 원문이 긴 법령명을 줄바꿈으로 끊어 넣는 경우가 있어 내부 공백을 한 칸으로 정규화
                target_law = re.sub(r"\s+", " ", _normalize_middot(m.group(1))).strip()
                art = m.group(2)
            else:                                 # 상대참조
                token = re.sub(r"\s+", "", m.group(3))
                art = m.group(4)
                if token == "같은법시행규칙":
                    target_law = rel["규칙"]
                elif token == "같은법시행령":
                    target_law = rel["영"]
                elif token in ("법", "이법"):
                    target_law = rel["법"]
                elif token in ("영", "이영"):
                    target_law = rel["영"]
                elif token in ("규칙", "이규칙"):
                    target_law = rel["규칙"]
                else:
                    continue
            key = (target_law.strip(), art.replace(" ", ""))
            if not key[0] or key in have:
                continue
            if key not in order:
                order[key] = seq
                seq += 1
            freq[key] = freq.get(key, 0) + 1
    # 참조 빈도 내림차순 → 동률이면 최초 등장 순
    ranked = sorted(freq, key=lambda k: (-freq[k], order[k]))
    return [f"{law} {art}" for law, art in ranked[:max_hints]]


_QUERY_HINT_PAT = re.compile(
    r"「([^」]{2,45})」"                                             # 명시 법령명 (last_law 갱신)
    r"(?:\s*\([^)]{0,40}\))?"                                        # (이하 "…"이라 함) 등
    r"\s*(제\d+조(?:의\d+)?|별표\s*\d+(?:의\d+)?)?"                  # 바로 붙은 조문·별표
    r"|(?<![가-힣])(같은\s*법(?:\s*시행령|\s*시행규칙)?)\s*"          # 상대참조
    r"(제\d+조(?:의\d+)?|별표\s*\d+(?:의\d+)?)"
)


def _explicit_query_hints(query: str, max_hints: int = 6) -> list[str]:
    """질의문에 명시된 「법령명」 조문·별표를 결정론 추출한 폴백 힌트.

    Pass 1이 law_hints를 통째로 놓치는 경우가 있다(17-0651 실측: 질의에
    '「건축법」 제2조제1항제11호나목'이 명시돼 있었는데 힌트 0건 → 정의 원문·
    조문 프레임 미로딩 → 가목 오포섭 오답). 질의문이 직접 거명한 조문만큼은
    Pass 1 성패와 무관하게 exact fetch에 태운다. '같은 법 (시행령/시행규칙)'
    상대참조는 직전 명시 법령으로 해소한다."""
    out: list[str] = []
    seen: set = set()
    last_law = None
    for m in _QUERY_HINT_PAT.finditer(query or ""):
        if m.group(1):
            last_law = re.sub(r"\s+", " ", m.group(1)).strip()
            art = m.group(2)
            law = last_law
        else:
            if not last_law:
                continue
            token = re.sub(r"\s+", "", m.group(3))
            base = re.sub(r"\s*시행(령|규칙)$", "", last_law).strip()
            if token.endswith("시행령"):
                law = f"{base} 시행령"
            elif token.endswith("시행규칙"):
                law = f"{base} 시행규칙"
            else:
                law = base
            art = m.group(4)
        if not art:
            continue
        hint = f"{law} {art.replace(' ', '')}"
        key = re.sub(r"\s+", "", hint)
        if key in seen:
            continue
        seen.add(key)
        out.append(hint)
        if len(out) >= max_hints:
            break
    return out


_delegation_graph: Optional[dict] = None


def _load_delegation_graph() -> dict:
    """delegation_graph.json 지연 로드 (빌드타임 lsDelegated 스냅샷 — 런타임 API 접근 없음)."""
    global _delegation_graph
    if _delegation_graph is None:
        try:
            _delegation_graph = json.loads(
                DELEGATION_PATH.read_text(encoding="utf-8")).get("edges", {})
        except Exception:
            _delegation_graph = {}
    return _delegation_graph


def _delegation_hints(law_docs, max_hints: int = 6) -> list[str]:
    """검색된 조문이 발원인 '하향 위임'(법→영→규칙) 대상 조문을 힌트로 추출.

    위임 문구('대통령령으로 정하는')에는 조번호가 없어 텍스트 crossref가
    따라갈 수 없는 방향(16-0506: 영 제25조③7호 → 규칙 제3조 누락 실증)을
    delegation_graph.json으로 해소한다. crossref의 노이즈 투표 교훈에 따라
    트리거는 exact(Pass 1 특정) 문서 + 검색 상위 3건으로 제한한다."""
    graph = _load_delegation_graph()
    if not graph:
        return []
    triggers = [d for d in law_docs if d.score_type == "exact"]
    for d in law_docs[:3]:
        if d not in triggers:
            triggers.append(d)
    have = {(re.sub(r"\s+", "", d.law_name), d.article_no.replace(" ", "")) for d in law_docs}
    hints: list[str] = []
    seen = set()
    for doc in triggers:
        m = re.match(r"(제\d+조(의\d+)?)", doc.article_no.replace(" ", ""))
        if not m:
            continue
        for e in graph.get(f"{doc.law_name.strip()}::{m.group(1)}", []):
            if not e.get("in_corpus"):
                continue
            key = (re.sub(r"\s+", "", e["dst_law"]), e["dst_article"])
            if key in have or key in seen:
                continue
            seen.add(key)
            hints.append(f"{e['dst_law']} {e['dst_article']}")
            if len(hints) >= max_hints:
                return hints
    return hints


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
        self._chroma    = chroma_client
        self._embed     = embed_model
        self._law_col   = chroma_client.get_collection("law_articles")
        self._session_cols: dict[str, object] = {}

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

        # principles: 일반 법리 원칙 RAG (ingest_principles.py로 구축)
        try:
            self._principle_col = chroma_client.get_collection("principles")
        except Exception:
            self._principle_col = None

        # law_amendments: 개정이력 의미 검색 (index_amendments_chroma.py로 구축)
        try:
            self._amend_col = chroma_client.get_collection("law_amendments")
        except Exception:
            self._amend_col = None

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
            law_filter = [_normalize_middot(x) for x in law_filter]
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
            law_filter = [_normalize_middot(x) for x in law_filter]
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

        tokenized = [doc.split() for doc in documents]
        bm25 = BM25Okapi(tokenized)
        scores = bm25.get_scores(query.split())
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
        as_of_date: Optional[str] = None,
        exclude_codes: Optional[set] = None,
        as_of_code: Optional[str] = None,
    ) -> list[RetrievedDoc]:
        """qa_precedents + precedents_2026_april 벡터 검색.

        as_of_date    : 'YYYY-MM-DD'. 지정 시 doc_date가 이 날짜보다 미래인
                        해석례는 제외(그 시점에 존재하지 않았으므로). eval 전용.
        exclude_codes : 제외할 doc_code 집합(평가 대상 자기 자신 등 정답 누수 차단).
        as_of_code    : 평가 대상 안건번호('YY-NNNN'). doc_date가 비어 컷오프가
                        무력화될 때 안건번호 순서로 미래 자료를 거른다.
        """
        query_emb = self._embed_text(query)
        docs = []
        exclude_codes = exclude_codes or set()

        for col, label in [(self._qa_col, "qa_precedents"), (self._prec_col, "precedents_2026_april")]:
            if col is None or col.count() == 0:
                continue
            # dedup·날짜필터 후에도 top_k 채울 수 있도록 후보를 넉넉히 확보
            n = min(top_k * 6, col.count())
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
                # 시점 컷오프: 미래 해석례·자기 자신 제외
                doc_code = meta.get("doc_code", "")
                if doc_code and doc_code in exclude_codes:
                    continue
                if _doc_is_after_cutoff(meta, as_of_date, as_of_code):
                    continue
                meta = dict(meta)
                _attach_cite_label(meta)
                docs.append(RetrievedDoc(
                    source=label,
                    law_name=meta.get("doc_agency", ""),
                    article_no=meta.get("doc_ref", meta.get("doc_code", "")),
                    content=doc_text,
                    score=round(score, 4),
                    score_type="vector",
                    metadata=meta,
                ))

        docs.sort(key=lambda d: -d.score)

        # 동일 자료 중복 제거: doc_code 우선, 없으면 content 첫 120자
        # (인덱스에 같은 해석례가 여러 번 들어가 있는 레거시 자료 다수 존재)
        seen_keys: set[str] = set()
        unique_docs: list[RetrievedDoc] = []
        for d in docs:
            code = d.metadata.get("doc_code", "")
            key = code if code else d.content[:120]
            if key in seen_keys:
                continue
            seen_keys.add(key)
            unique_docs.append(d)

        return unique_docs[:top_k]

    # ----------------------------------------------------------
    # ID 직접 조회 — 원칙·메모 페어링용 (검색 점수 우회 강제 포함)
    # ----------------------------------------------------------

    def fetch_qa_by_codes(self, codes: list[str]) -> list[RetrievedDoc]:
        """doc_code 직접 매칭으로 qa_precedents/precedents_2026_april 가져옴."""
        if not codes:
            return []
        unique_codes = sorted(set(c for c in codes if c))
        if not unique_codes:
            return []
        result: list[RetrievedDoc] = []
        for col, label in [
            (self._qa_col, "qa_precedents"),
            (self._prec_col, "precedents_2026_april"),
        ]:
            if col is None:
                continue
            where = (
                {"doc_code": unique_codes[0]} if len(unique_codes) == 1
                else {"doc_code": {"$in": unique_codes}}
            )
            try:
                res = col.get(
                    where=where,
                    include=["documents", "metadatas"],
                    limit=len(unique_codes) * 5,
                )
            except Exception:
                continue
            for doc_text, meta in zip(res.get("documents", []), res.get("metadatas", [])):
                meta = dict(meta)
                _attach_cite_label(meta)
                result.append(RetrievedDoc(
                    source=label,
                    law_name=meta.get("doc_agency", ""),
                    article_no=meta.get("doc_ref", meta.get("doc_code", "")),
                    content=doc_text,
                    score=2.0,           # 강제 포함, 최우선
                    score_type="paired",
                    metadata=meta,
                ))
        return result

    def fetch_cases_by_ids(self, case_ids: list[str]) -> list[RetrievedDoc]:
        """case_id 직접 매칭으로 court_cases 가져옴."""
        if not case_ids or self._case_col is None:
            return []
        unique_ids = sorted(set(c for c in case_ids if c))
        if not unique_ids:
            return []
        where = (
            {"case_id": unique_ids[0]} if len(unique_ids) == 1
            else {"case_id": {"$in": unique_ids}}
        )
        try:
            res = self._case_col.get(
                where=where,
                include=["documents", "metadatas"],
                limit=len(unique_ids) * 5,
            )
        except Exception:
            return []
        result: list[RetrievedDoc] = []
        for doc_text, meta in zip(res.get("documents", []), res.get("metadatas", [])):
            result.append(RetrievedDoc(
                source="court_cases",
                law_name=meta.get("cited_laws_str", ""),
                article_no=meta.get("case_id", ""),
                content=doc_text,
                score=2.0,
                score_type="paired",
                metadata=dict(meta),
            ))
        return result

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

            # 조례 힌트는 내장 지역 팩에서 조회 (law_articles에는 조례가 없음)
            if "조례" in law_name:
                for d in self.fetch_exact_region(law_name, art_prefix, top_n):
                    key = f"{d.law_name}::{d.article_no}::{d.content[:40]}"
                    if key in seen:
                        continue
                    seen.add(key)
                    result.append(d)
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
    # 사각지대 감지 — law_hints 중 DB 미수록 법령 식별
    # ----------------------------------------------------------

    # 과거 시점·폐지 법령을 가리키는 한글 패턴 (캐싱 어려운 경우 분류)
    _PAST_LAW_PAT = re.compile(
        r'(?:^|\s)(?:구\s+[가-힣]+법|폐지|과거|당시)|'
        r'\d{4}년\s*\d{1,2}월\s*\d{1,2}일\s*당시|'
        r'\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.\s*시행'
    )

    def _byeolpyo_in_db(self, law_name: str, art_prefix: str) -> bool:
        """해당 법령의 별표가 law_articles에 실제 인덱싱돼 있는지 확인."""
        if self._law_col is None:
            return False
        try:
            res = self._law_col.get(
                where={"$and": [
                    {"law_name":    {"$eq": law_name}},
                    {"is_byeolpyo": {"$eq": "true"}},
                ]},
                include=["metadatas"],
                limit=300,
            )
        except Exception:
            return False
        if not res.get("ids"):
            return False
        key = (art_prefix or "").replace(" ", "")
        if not key:
            return True   # 별표 번호 불명이지만 그 법령 별표가 있으면 통과
        return any(
            a == key or a.startswith(key + "의")
            for a in (str(m.get("article_no", "")).replace(" ", "") for m in res["metadatas"])
        )

    def detect_blind_spots(self, law_hints: list[str]) -> dict:
        """
        law_hints를 분류하여 사각지대를 식별한다 (DB 조회만, API 호출 없음).

        반환 형식:
          {
            "fetchable": [{"hint": "신탁법 제22조", "law_name": "신탁법", "article_no": "제22조"}],
            "manual_check": [
              {"hint": "...", "reason": "별표"|"과거시점"|"미상"}
            ],
          }
        """
        result = {"fetchable": [], "manual_check": []}
        if not law_hints:
            return result

        # law_articles에서 law_name 단독 존재 여부 빠르게 조회
        # (n_results=1 + where 필터)
        for hint in law_hints:
            law_name, art_prefix, is_byeolpyo = _parse_law_hint(hint)
            if not law_name:
                continue

            # 분기 1: 별표 → DB에 실제 인덱싱돼 있으면 정상. 없으면 API 패치 가능
            #         (법령·자치법규 API 모두 별표 전문을 제공 — fetcher가 별표 지원).
            if is_byeolpyo or "별표" in hint:
                if not self._byeolpyo_in_db(law_name, art_prefix):
                    result["fetchable"].append({
                        "hint": hint,
                        "law_name": law_name,
                        "article_no": art_prefix.replace(" ", ""),   # "별표1"
                    })
                continue

            # 분기 2: 과거 시점·폐지 → 수동 확인
            if self._PAST_LAW_PAT.search(hint):
                result["manual_check"].append({"hint": hint, "reason": "과거시점"})
                continue

            # 분기 3: 법령 자체가 DB에 있는지 확인
            try:
                res = self._law_col.get(
                    where={"law_name": {"$eq": law_name}},
                    include=[],
                    limit=1,
                )
                exists_in_db = bool(res.get("ids"))
            except Exception:
                exists_in_db = False

            if not exists_in_db:
                # 법령 자체 부재 → API 패치 가능
                result["fetchable"].append({
                    "hint": hint,
                    "law_name": law_name,
                    "article_no": art_prefix,
                })
            # 법령은 있는데 조문이 매칭 안 된 경우 (별표 외) — 정상 운영상 거의 없음.
            # 발생 시 fetch_exact_articles의 prefix 매칭으로 잡혀야 정상. 여기선 무시.

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
    # 일반 법리 원칙 검색 (principles)
    # ----------------------------------------------------------

    def search_principles(
        self,
        query: str,
        top_k: int = 2,
        min_score: float = 0.40,
    ) -> list[dict]:
        """principles 컬렉션 벡터 검색. 유사도 min_score 이상인 원칙 반환."""
        if self._principle_col is None or self._principle_col.count() == 0:
            return []
        query_emb = self._embed_text(query)
        n = min(top_k * 2, self._principle_col.count())
        try:
            res = self._principle_col.query(
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
                "principle_id":      meta.get("principle_id", ""),
                "title":             meta.get("title", ""),
                "trigger":           meta.get("trigger", ""),
                "exception":         meta.get("exception", ""),
                "source_cases":      meta.get("source_cases", ""),
                "source_precedents": meta.get("source_precedents", ""),
                "content":           doc_text,
                "score":             round(score, 4),
            })

        results.sort(key=lambda x: -x["score"])
        return results[:top_k]

    # ----------------------------------------------------------
    # 개정이력 의미 검색 (law_amendments)
    # ----------------------------------------------------------

    def search_amendments_semantic(
        self,
        query: str,
        amendments_cache: list[dict],
        top_k: int = 3,
        min_score: float = 0.45,
    ) -> list[dict]:
        """
        쿼리 의미 기반으로 개정이력 직접 검색.
        '방화문 기준이 어떻게 바뀌었나' 등 개정 관련 질의에 활용.

        Parameters
        ----------
        query            : 검색 쿼리
        amendments_cache : Retriever._amendments (amendments.jsonl 전체)
        top_k            : 반환할 최대 건수
        min_score        : 최소 유사도 (cosine 변환 기준)
        """
        if self._amend_col is None or self._amend_col.count() == 0:
            return []

        query_emb = self._embed_text(query)
        n = min(top_k * 2, self._amend_col.count())
        try:
            res = self._amend_col.query(
                query_embeddings=[query_emb],
                n_results=n,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            return []

        # amendment_id → full record 매핑
        amend_map: dict[str, dict] = {
            rec.get("amendment_id", ""): rec
            for rec in amendments_cache
        }

        results = []
        for doc_text, meta, dist in zip(
            res["documents"][0], res["metadatas"][0], res["distances"][0]
        ):
            score = max(0.0, 1.0 - dist)
            if score < min_score:
                continue
            aid = meta.get("amendment_id", "")
            full_rec = amend_map.get(aid)
            if full_rec is not None:
                results.append(full_rec)

        results_unique = []
        seen_ids: set[str] = set()
        for rec in results:
            aid = rec.get("amendment_id", "")
            if aid not in seen_ids:
                results_unique.append(rec)
                seen_ids.add(aid)

        return results_unique[:top_k]

    # ----------------------------------------------------------
    # 세션 컬렉션 (업로드 PDF 임시 인덱싱)
    # ----------------------------------------------------------

    def create_session_collection(self, key: str) -> None:
        """업로드 전용 영속 컬렉션 (사용자 anon_id 기준, 없으면 세션id). 재사용.
        마지막 사용시각(last_used)을 갱신 → N일 미사용 시 cleanup 대상."""
        from datetime import datetime
        col_name = f"upload_{key[:16]}"
        now = datetime.now().isoformat()
        try:
            col = self._chroma.get_or_create_collection(
                name=col_name,
                metadata={"hnsw:space": "cosine", "last_used": now},
            )
            try:
                col.modify(metadata={"hnsw:space": "cosine", "last_used": now})
            except Exception:
                pass
            self._session_cols[key] = col
        except Exception as e:
            print(f"[업로드 컬렉션 생성 실패] {e}")

    def index_uploaded_chunks(self, session_id: str, chunks: list[dict], thread_id: str = "") -> int:
        """청크를 세션 컬렉션에 임베딩하여 저장. 반환: 저장된 청크 수.
        조례(법령명에 '조례' 포함)는 업로드한 대화(thread_id)에서만 검색되도록 태깅한다."""
        col = self._session_cols.get(session_id)
        if col is None:
            return 0

        import uuid
        batch_uid = uuid.uuid4().hex[:8]   # PDF(호출)마다 고유 → 여러 PDF 업로드 시 id 충돌 방지
        ids, texts, metas = [], [], []
        for i, chunk in enumerate(chunks):
            ln = chunk.get("law_name", "업로드 법령")
            ids.append(f"{session_id[:8]}_{batch_uid}_{i}")
            texts.append(chunk["content"][:6000])
            metas.append({
                "law_name": ln,
                "article_no": chunk.get("article_no", f"chunk_{i}"),
                "source": "uploaded",
                "is_ordinance": "true" if "조례" in ln else "false",
                "thread_id": thread_id or "",
            })

        if not ids:
            return 0

        BATCH = 32
        embeddings = []
        for i in range(0, len(texts), BATCH):
            embeddings.extend([self._embed_text(t) for t in texts[i:i + BATCH]])

        col.add(ids=ids, embeddings=embeddings, documents=texts, metadatas=metas)
        return len(ids)

    def search_uploaded(self, session_id: str, query: str, top_k: int = 5,
                        thread_id: str = "", context: str = "",
                        force_articles: Optional[list] = None,
                        query_regions: Optional[list] = None) -> list:
        """세션 컬렉션에서 유사도 검색. RetrievedDoc 리스트 반환.

        조례는 원칙적으로 업로드한 대화(thread_id)에서만 노출하되, 다음 중 하나면
        다른 대화에서도 허용한다:
          (a) 그 컬렉션에 조례가 1종류뿐 — 구분할 다른 지역 조례가 없어 격리가 무의미
          (b) 질문 또는 직전 대화 맥락(context)에 그 조례의 지역명이 언급됨
        연속 질의에서 후속 질문("각 상세시설 면적은?")에 지역명이 빠져도 직전 맥락으로
        해소된다(과거에는 지역명 없는 후속 질문에서 조례가 통째로 누락됐음).

        query_regions: 질문이 특정한 지역 목록(사실표·지역 매칭에서 산출). 지정되면
        다른 지역의 조례는 전역 등록이라도 벡터 결과에서 제외한다 — 원주 질문에
        남양주 조례가 '참고용'으로 끼어들던 교차 오염 차단. 빈 목록이면 기존 동작.

        force_articles: [(law_name, article_no), ...] — 앞선 답변에서 이미 활용한
        업로드 조문을 벡터 랭킹·스코프와 무관하게 강제 포함(누적 법령 세트). '시설
        리스트' 같은 질문이 조례 제5조와 유사도가 낮아 밀려도 조례를 계속 붙잡게 한다."""
        col = self._session_cols.get(session_id)
        if col is None or col.count() == 0:
            return []

        # 컬렉션 내 '다른 대화에서 올린' 조례가 몇 종류인지 — 1종이면 스코프 필터 스킵
        distinct_foreign_ord = 0
        if thread_id:
            try:
                all_meta = col.get(include=["metadatas"], limit=10000)["metadatas"]
                names = {
                    m.get("law_name", "") for m in all_meta
                    if m.get("is_ordinance") == "true"
                    and m.get("thread_id", "") and m.get("thread_id") != thread_id
                }
                distinct_foreign_ord = len(names)
            except Exception:
                distinct_foreign_ord = 99   # 조회 실패 시 보수적으로 필터 유지

        match_text = f"{query}\n{context}"

        query_emb = self._embed_text(query)
        # 조례 스레드 필터로 일부가 걸러질 수 있어 넉넉히 뽑은 뒤 top_k로 자른다.
        n = min(max(top_k * 3, top_k), col.count())
        try:
            res = col.query(
                query_embeddings=[query_emb],
                n_results=n,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            return []

        results = []
        for doc, meta, dist in zip(
            res["documents"][0], res["metadatas"][0], res["distances"][0]
        ):
            # 조례인데 다른 대화에서 업로드된 것이면 원칙적으로 제외 (thread_id 불일치).
            # 단, 조례가 1종뿐이거나(구분 불필요) 질문·맥락에 지역명이 있으면 허용.
            if meta.get("is_ordinance") == "true":
                # 지역이 특정되지 않은 일반 질문에는 특정 지역 조례를 싣지 않는다
                # ('사업변경신청 일반론' 질문에 부천 조례가 '지역 조례의 적용' 절로
                # 끼던 문제). 후속 질문은 직전 맥락의 지역이 query_regions로 잡혀
                # 유지되고, 누적 법령(carry)의 조례는 아래 force가 계속 붙잡는다.
                if not query_regions:
                    continue
                # 질문이 특정 지역을 언급했으면 다른 지역 조례는 제외 (전역 포함)
                region_of = re.sub(r"\s+", "", _extract_region(meta.get("law_name", "")))
                if region_of and not any(
                    region_of in re.sub(r"\s+", "", str(q)) or
                    re.sub(r"\s+", "", str(q)) in region_of
                    for q in query_regions
                ):
                    continue
                tid = meta.get("thread_id", "")
                if tid and thread_id and tid != thread_id and distinct_foreign_ord > 1:
                    region = _extract_region(meta.get("law_name", ""))
                    if not (region and region in match_text):
                        continue
            score = max(0.0, 1.0 - dist)
            if score < 0.3:
                continue
            results.append(RetrievedDoc(
                source="uploaded",
                law_name=meta.get("law_name", "업로드 법령"),
                article_no=meta.get("article_no", ""),
                content=doc,
                score=score,
                score_type="vector",
                metadata={"source": "uploaded"},
            ))
            if len(results) >= top_k:
                break

        # ── 누적 법령 세트 강제 포함 (벡터 랭킹·스코프 무관) ──
        # 업로드 청킹은 항 단위("제5조 ①"·"제5조 ②")라 조문번호 정확 일치로 가져오면
        # 처음 검색된 항 하나에 갇힌다(제5조 ①만 계속 붙잡고 ②의 시설별 기준은 실종).
        # 조문번호를 조 단위로 정규화해 그 조의 '모든 항 청크'를 포함한다.
        if force_articles:
            have = {(d.law_name, d.article_no) for d in results}
            for ln, art in force_articles:
                if not ln or not art:
                    continue
                root = re.sub(r'[①-⑳㉑-㉚].*$', '', str(art).replace(" ", "")).strip()
                if not root:
                    continue
                try:
                    got = col.get(
                        where={"law_name": {"$eq": ln}},
                        include=["documents", "metadatas"], limit=500,
                    )
                except Exception:
                    continue
                for doc_t, meta in zip(got.get("documents", []), got.get("metadatas", [])):
                    a_n = str(meta.get("article_no", "")).replace(" ", "")
                    # 조 일치 또는 그 조의 항 청크('제5조 ①')·별표 조각('별표1(2)')만
                    # — "제5조의2"가 "제5조"에 딸려오지 않게
                    if a_n != root and not re.match(re.escape(root) + r'[①-⑳㉑-㉚(]', a_n):
                        continue
                    key = (meta.get("law_name", ln), meta.get("article_no", ""))
                    if key in have:
                        continue
                    have.add(key)
                    results.append(RetrievedDoc(
                        source="uploaded",
                        law_name=key[0],
                        article_no=key[1],
                        content=doc_t,
                        score=1.5,            # 강제 포함 — 상위 가중
                        score_type="carry",
                        metadata={"source": "uploaded"},
                    ))
        return results

    def list_uploaded_docs(self, session_id: str) -> list[dict]:
        """업로드 캐시 내용 조회: 법령명별 청크 수·조례 여부 집계."""
        col = self._session_cols.get(session_id)
        if col is None or col.count() == 0:
            return []
        try:
            metas = col.get(include=["metadatas"], limit=10000)["metadatas"]
        except Exception:
            return []
        agg: dict = {}
        for m in metas:
            ln = m.get("law_name", "업로드 법령")
            e = agg.setdefault(ln, {"law_name": ln, "chunks": 0, "is_ordinance": False})
            e["chunks"] += 1
            if m.get("is_ordinance") == "true":
                e["is_ordinance"] = True
        return sorted(agg.values(), key=lambda x: x["law_name"])

    def delete_uploaded_doc(self, session_id: str, law_name: str) -> int:
        """업로드 캐시에서 특정 법령(law_name)의 청크만 삭제. 반환: 삭제 청크 수."""
        col = self._session_cols.get(session_id)
        if col is None:
            return 0
        try:
            ids = col.get(where={"law_name": {"$eq": law_name}}, include=[], limit=10000)["ids"]
            if ids:
                col.delete(ids=ids)
            return len(ids)
        except Exception:
            return 0

    def delete_session_collection(self, key: str) -> None:
        """업로드 컬렉션 명시적 삭제 (예: '대화 초기화'에서 호출)."""
        col_name = f"upload_{key[:16]}"
        try:
            self._chroma.delete_collection(col_name)
        except Exception:
            pass
        self._session_cols.pop(key, None)

    # ----------------------------------------------------------
    # 내장 지역 조례 팩 (region_ordinances 전역 컬렉션)
    #   ingest/region_packs/*.json을 앱 기동 시 인덱싱해 두는 붙박이 조례.
    #   업로드 캐시와 달리 사용자·세션과 무관하게 전 사용자 공용이며,
    #   질문·맥락에 그 지역명이 언급될 때만 벡터 검색에 참여한다.
    # ----------------------------------------------------------

    _REGION_COL_NAME = "region_ordinances"

    def _region_col(self):
        if getattr(self, "_region_col_cache", None) is not None:
            return self._region_col_cache
        try:
            self._region_col_cache = self._chroma.get_or_create_collection(
                name=self._REGION_COL_NAME,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception:
            self._region_col_cache = None
        return self._region_col_cache

    def list_region_laws(self) -> list[dict]:
        """내장 조례 팩 목록: [{'law_name','region','chunks'}] — UI·사각지대 필터용. 캐시됨."""
        cached = getattr(self, "_region_laws_cache", None)
        if cached is not None:
            return cached
        col = self._region_col()
        if col is None or col.count() == 0:
            self._region_laws_cache = []
            return []
        try:
            metas = col.get(include=["metadatas"], limit=100000)["metadatas"]
        except Exception:
            return []
        agg: dict = {}
        for m in metas:
            ln = m.get("law_name", "")
            e = agg.setdefault(ln, {"law_name": ln, "region": m.get("region", ""), "chunks": 0})
            e["chunks"] += 1
        self._region_laws_cache = sorted(agg.values(), key=lambda x: (x["region"], x["law_name"]))
        return self._region_laws_cache

    def index_region_chunks(self, region: str, chunks: list[dict]) -> int:
        """지역 팩 청크 인덱싱 — 그 지역 기존 항목을 지우고 재적재(팩 갱신 대응)."""
        col = self._region_col()
        if col is None or not chunks:
            return 0
        try:
            old = col.get(where={"region": {"$eq": region}}, include=[], limit=100000)["ids"]
            if old:
                col.delete(ids=old)
        except Exception:
            pass
        ids, texts, metas = [], [], []
        for i, ch in enumerate(chunks):
            ids.append(f"region::{region}::{i}")
            texts.append(ch["content"][:6000])
            metas.append({
                "law_name": ch.get("law_name", ""),
                "article_no": ch.get("article_no", f"chunk_{i}"),
                "source": "region",
                "region": region,
                "is_ordinance": "true",
            })
        BATCH = 32
        embeddings = []
        for i in range(0, len(texts), BATCH):
            embeddings.extend([self._embed_text(t) for t in texts[i:i + BATCH]])
        col.add(ids=ids, embeddings=embeddings, documents=texts, metadatas=metas)
        self._region_laws_cache = None   # 목록 캐시 무효화
        return len(ids)

    # 자치구명 → 광역 지자체: 질문이 '강남구 재건축'처럼 구 단위로 와도 그 시의
    # 조례 팩이 발동하게 한다. 타 광역시와 겹치는 구명(중구·강서구 등)은 오탐
    # 방지를 위해 제외 — 그런 질문은 시명이 함께 언급될 때만 매칭된다.
    _REGION_DISTRICTS = {
        "서울특별시": [
            "종로구", "용산구", "성동구", "광진구", "동대문구", "중랑구", "성북구",
            "강북구", "도봉구", "노원구", "은평구", "서대문구", "마포구", "양천구",
            "구로구", "금천구", "영등포구", "동작구", "관악구", "서초구", "강남구",
            "송파구", "강동구",
        ],
    }

    @staticmethod
    def _region_aliases(region: str) -> list[str]:
        """'서울특별시' → ['서울특별시','서울시','서울'] — 질문·맥락의 지역 언급 매칭용."""
        base = re.sub(r"(특별자치시|특별자치도|특별시|광역시|시|군|구|도)$", "", region)
        out = {region}
        if base and base != region:
            out.add(base)
            out.add(base + "시")
        return sorted(out, key=len, reverse=True)

    @classmethod
    def _region_match_terms(cls, region: str) -> list[str]:
        """지역 매칭 어휘 = 지역명 별칭 + 그 지역 자치구명."""
        return cls._region_aliases(region) + cls._REGION_DISTRICTS.get(region, [])

    def match_regions(self, text: str) -> list[str]:
        """텍스트에 언급된 '보유 지역 팩' 목록 (별칭·자치구명 매칭)."""
        if not text:
            return []
        regions = {d["region"] for d in self.list_region_laws() if d["region"]}
        return sorted(r for r in regions
                      if any(t in text for t in self._region_match_terms(r)))

    def search_region(self, query: str, top_k: int = 5, context: str = "",
                      force_articles: Optional[list] = None,
                      exclude: Optional[set] = None) -> list:
        """내장 지역 조례 검색.

        질문 또는 직전 맥락(context)에 팩 지역명이 언급된 경우에만 그 지역 조례를
        벡터 검색한다(무관 지역의 질문을 오염시키지 않게). force_articles의 조례는
        지역 언급과 무관하게 조 단위(모든 항 청크)로 강제 포함 — 누적 법령 세트가
        업로드 캐시와 동일하게 동작한다. exclude: 이미 확보된 (law_name, article_no)."""
        col = self._region_col()
        if col is None or col.count() == 0:
            return []
        have = set(exclude or set())
        results: list = []

        regions = {d["region"] for d in self.list_region_laws() if d["region"]}
        match_text = f"{query}\n{context}"
        matched = [r for r in regions
                   if any(t in match_text for t in self._region_match_terms(r))]
        if matched:
            try:
                where = ({"region": {"$eq": matched[0]}} if len(matched) == 1
                         else {"region": {"$in": matched}})
                res = col.query(
                    query_embeddings=[self._embed_text(query)],
                    n_results=min(top_k * 2, col.count()),
                    where=where,
                    include=["documents", "metadatas", "distances"],
                )
                for doc, meta, dist in zip(
                    res["documents"][0], res["metadatas"][0], res["distances"][0]
                ):
                    score = max(0.0, 1.0 - dist)
                    if score < 0.3:
                        continue
                    key = (meta.get("law_name", ""), meta.get("article_no", ""))
                    if key in have:
                        continue
                    have.add(key)
                    results.append(RetrievedDoc(
                        source="uploaded",
                        law_name=key[0],
                        article_no=key[1],
                        content=doc,
                        score=score,
                        score_type="vector",
                        metadata={"source": "region", "region": meta.get("region", "")},
                    ))
                    if len(results) >= top_k:
                        break
            except Exception:
                pass

        # 누적 법령 세트 강제 포함 — 업로드 캐시 force와 동일한 조 단위 규칙
        if force_articles:
            for ln, art in force_articles:
                if not ln or not art or "조례" not in str(ln):
                    continue
                root = re.sub(r'[①-⑳㉑-㉚].*$', '', str(art).replace(" ", "")).strip()
                if not root:
                    continue
                try:
                    got = col.get(where={"law_name": {"$eq": ln}},
                                  include=["documents", "metadatas"], limit=500)
                except Exception:
                    continue
                for doc_t, meta in zip(got.get("documents", []), got.get("metadatas", [])):
                    a_n = str(meta.get("article_no", "")).replace(" ", "")
                    # 조·항 청크 및 별표 조각('별표1(2)')까지 — '제5조의2'는 제외
                    if a_n != root and not re.match(re.escape(root) + r'[①-⑳㉑-㉚(]', a_n):
                        continue
                    key = (meta.get("law_name", ln), meta.get("article_no", ""))
                    if key in have:
                        continue
                    have.add(key)
                    results.append(RetrievedDoc(
                        source="uploaded",
                        law_name=key[0],
                        article_no=key[1],
                        content=doc_t,
                        score=1.5,
                        score_type="carry",
                        metadata={"source": "region", "region": meta.get("region", "")},
                    ))
        return results

    # ----------------------------------------------------------
    # 조례 리딩 레지스트리 (ordinance_registry)
    #   조례를 읽는 모든 경로(스캔·패치·PDF·내장 팩)가 리딩 메타데이터를
    #   지역 태그로 영속화한다. 별도 시점에 읽힌 조례들이 지역 키로 합쳐져
    #   그 지역 법령체계(조례 × 모법 위임)의 총괄 뷰가 된다.
    # ----------------------------------------------------------

    _REGISTRY_COL_NAME = "ordinance_registry"

    def _registry_col(self):
        try:
            return self._chroma.get_or_create_collection(
                name=self._REGISTRY_COL_NAME,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception:
            return None

    def upsert_ordinance_registry(self, region: str, law_name: str, detail: dict) -> None:
        """조례 리딩 메타데이터 병합 저장. detail: {mst, cited_laws, articles, toc,
        chars, sources:[scan|patch|pdf|pack]}. 같은 (지역, 조례)는 갱신하되
        first_read·sources는 누적한다."""
        col = self._registry_col()
        if col is None or not law_name:
            return
        from datetime import datetime
        rid = "reg::" + re.sub(r"\s+", "", f"{region}::{law_name}")
        detail = dict(detail)
        detail["region"] = region
        detail["law_name"] = law_name
        detail["last_read"] = detail.get("last_read") or datetime.now().strftime("%Y-%m-%d")
        try:
            old = col.get(ids=[rid], include=["documents"])
            if old.get("ids"):
                try:
                    prev = json.loads(old["documents"][0])
                except Exception:
                    prev = {}
                detail.setdefault("first_read", prev.get("first_read", detail["last_read"]))
                detail["sources"] = sorted(
                    set(prev.get("sources", [])) | set(detail.get("sources", [])))
                col.delete(ids=[rid])
            else:
                detail.setdefault("first_read", detail["last_read"])
            col.add(
                ids=[rid],
                embeddings=[[0.0]],   # 벡터 검색 안 함 — get 전용 레지스트리
                documents=[json.dumps(detail, ensure_ascii=False)],
                metadatas=[{
                    "region": region,
                    "law_name": law_name,
                    "cited": ", ".join((detail.get("cited_laws") or [])[:6]),
                    "articles": int(detail.get("articles", 0)),
                    "source": ",".join(detail.get("sources", [])),
                }],
            )
        except Exception:
            pass

    def get_ordinance_registry(self, region: str = "") -> list[dict]:
        """지역별(또는 전체) 조례 리딩 메타데이터 — 지역 법령체계 총괄 뷰."""
        col = self._registry_col()
        if col is None or col.count() == 0:
            return []
        try:
            where = {"region": {"$eq": region}} if region else None
            got = col.get(where=where, include=["documents"], limit=2000)
        except Exception:
            return []
        out = []
        for doc in got.get("documents", []):
            try:
                out.append(json.loads(doc))
            except Exception:
                pass
        return sorted(out, key=lambda d: (d.get("region", ""), d.get("law_name", "")))

    def get_ordinance_article_text(self, session_id: str, law_name: str,
                                   art_root: str = "제1조") -> str:
        """조례의 특정 조(모든 항)/별표(모든 조각)를 세션 업로드 → 내장 지역 팩
        순으로 찾아 원문 반환. 조례→모법 역링크(제1조 약칭 정의)와 인용 팝업에서 씀."""
        def norm(s):
            return re.sub(r"\s+", "", str(s or ""))

        def pick(col):
            if col is None:
                return ""
            try:
                got = col.get(where={"law_name": {"$eq": law_name}},
                              include=["documents", "metadatas"], limit=500)
            except Exception:
                return ""
            parts = []
            for doc_t, meta in zip(got.get("documents", []), got.get("metadatas", [])):
                a_n = norm(meta.get("article_no", ""))
                # 조 일치, 항 청크('제3조 ①'), 별표 조각('별표1(2)') 포함
                if a_n == art_root or re.match(re.escape(art_root) + r'[①-⑳㉑-㉚(]', a_n):
                    parts.append(doc_t)
            return "\n".join(parts)

        txt = pick(self._session_cols.get(session_id)) if session_id else ""
        if not txt:
            txt = pick(self._region_col())
        return txt

    def fetch_exact_region(self, law_name: str, art_prefix: str, top_n: int = 5) -> list:
        """law_hints의 조례 힌트를 내장 팩에서 조문번호 부분일치로 강제 포함
        (fetch_exact_articles의 조례판 — 명칭은 공백 무시 정확 일치)."""
        col = self._region_col()
        if col is None or col.count() == 0:
            return []

        def norm(s):
            return re.sub(r"\s+", "", str(s or ""))

        target = None
        for d in self.list_region_laws():
            if norm(d["law_name"]) == norm(law_name):
                target = d["law_name"]
                break
        if not target:
            return []
        try:
            res = col.get(where={"law_name": {"$eq": target}},
                          include=["documents", "metadatas"], limit=500)
        except Exception:
            return []
        art_key = norm(art_prefix)
        out: list = []
        for doc_text, meta in zip(res.get("documents", []), res.get("metadatas", [])):
            if art_key and art_key not in norm(meta.get("article_no", "")):
                continue
            out.append(RetrievedDoc(
                source="uploaded",
                law_name=meta.get("law_name", ""),
                article_no=meta.get("article_no", ""),
                content=doc_text,
                score=2.0,
                score_type="exact",
                metadata={"source": "region", "region": meta.get("region", "")},
            ))
            if len(out) >= top_n:
                break
        return out

    def cleanup_expired_uploads(self, days: int = 30) -> int:
        """N일 이상 미사용 upload_* 컬렉션 + 레거시 session_* 컬렉션을 정리.
        앱 기동 시 1회 호출 → orphan 누적 방지."""
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(days=days)
        removed = 0
        try:
            for c in self._chroma.list_collections():
                name = c.name
                if name.startswith("session_"):   # 영속화 이전 레거시 — 전부 삭제
                    self._chroma.delete_collection(name)
                    removed += 1
                    continue
                if not name.startswith("upload_"):
                    continue
                lu = (c.metadata or {}).get("last_used", "")
                try:
                    if lu and datetime.fromisoformat(lu) < cutoff:
                        self._chroma.delete_collection(name)
                        removed += 1
                except Exception:
                    pass
        except Exception as e:
            print(f"[업로드 정리 실패] {e}")
        return removed

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

        # chroma 메타데이터 where는 $contains를 지원하지 않아 종전의 필터 3단이
        # 전부 0건 → 항상 전체 벡터 폴백으로 떨어지는 죽은 코드였다(2026-07-20
        # 실측 — 필터/무필터 결과 동일). 넉넉히 뽑아 파이썬 후처리로 거른다.
        n = min(max(top_k * 4, 20), self._case_col.count())
        try:
            res = self._case_col.query(
                query_embeddings=[query_emb], n_results=n,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            res = None
        all_docs = _parse(res)

        def _law_hit(d):
            cited = d.metadata.get("cited_laws_str", "")
            return any(ln and ln in cited for ln in law_names)

        domain = [d for d in all_docs if _law_hit(d)] if law_names else []
        if domain and relation_type:
            typed = [d for d in domain
                     if relation_type in (d.metadata.get("relation_types") or "")]
            if len(typed) >= 2:
                return typed[:top_k]
        if domain:
            return domain[:top_k]
        return all_docs[:top_k]

    def doctrine_vocab_inventory(self) -> list[tuple[str, list[str]]]:
        """횡단 판례의 (계열, doctrine_terms) 목록 — Pass1 doctrine_hints 선택지.

        인덱스 메타데이터에서 도출하므로 판례를 학습할 때마다 자동으로 는다
        (수동 동기화 없음). 큐레이션의 차기 사건 테스트가 어휘 위생을 담보하는
        전제 위에서, Pass1은 이 목록에서 어휘를 '그대로' 골라 담는다
        (문자 매칭이므로 변형하면 불발)."""
        cached = getattr(self, "_doctrine_vocab_cache", None)
        if cached is not None:
            return cached
        inv: dict[str, list[str]] = {}
        try:
            if self._case_col is not None and self._case_col.count() > 0:
                res = self._case_col.get(include=["metadatas"], limit=5000)
                for meta in res.get("metadatas", []) or []:
                    if (meta or {}).get("doctrine_scope") != "횡단":
                        continue
                    series = meta.get("doctrine_series") or "기타"
                    bucket = inv.setdefault(series, [])
                    for t in (meta.get("doctrine_terms") or "").split("|"):
                        if t and t not in bucket:
                            bucket.append(t)
        except Exception:
            pass
        self._doctrine_vocab_cache = sorted(inv.items())
        return self._doctrine_vocab_cache

    def search_cases_by_doctrine(
        self,
        query: str,
        exclude_ids: Optional[set] = None,
        max_hits: int = 3,
        hints_text: str = "",
    ) -> list[RetrievedDoc]:
        """법리(doctrine) 경로 — 판례 역할 기반 소환.

        벡터 상위권은 사건 어휘가 지배해 타 도메인 법리 판례가 묻힌다
        (2011두3388 실측: 침익 처분 질의에서 19위). 레코드의 doctrine_terms
        (법리 어휘)가 질의에 나타나면 유사도 순위와 무관하게 주입한다.
        score_type="doctrine". 컬렉션이 수십 건 규모라 전량 조회로 충분 —
        수백 건 이상으로 커지면 doctrine 전용 인덱스로 분리할 것."""
        if self._case_col is None or self._case_col.count() == 0:
            return []
        exclude_ids = exclude_ids or set()
        # 매칭 대상 = 질의문 + Pass1 논지 힌트 (사안어휘 질의→논지어휘 레코드의
        # 직교를 잇는 다리 — 임베딩 정렬은 원문 질의 그대로 유지)
        q_norm = re.sub(r"\s+", "", query + " " + (hints_text or ""))
        try:
            res = self._case_col.query(
                query_embeddings=[self._embed_text(query)],
                n_results=self._case_col.count(),
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            return []
        hits = []
        for doc_text, meta, dist in zip(
            res["documents"][0], res["metadatas"][0], res["distances"][0]
        ):
            cid = meta.get("case_id", "")
            if cid in exclude_ids:
                continue
            # 횡단 판례 전용 — 도메인 판례는 페어링·벡터가 담당하고, 도메인
            # 어휘가 섞인 doctrine_terms는 오발화원이 된다(91누8319 실측)
            if meta.get("doctrine_scope") != "횡단":
                continue
            terms = [t for t in (meta.get("doctrine_terms") or "").split("|") if t]
            if not any(self._doctrine_hit(t, q_norm) for t in terms):
                continue
            hits.append(RetrievedDoc(
                source="court_cases",
                law_name=meta.get("cited_laws_str", ""),
                article_no=cid,
                content=doc_text,
                score=round(max(0.0, 1.0 - dist), 4),
                score_type="doctrine",
                metadata=dict(meta),
            ))
            if len(hits) >= max_hits:
                break
        return hits

    _DOCTRINE_STOP = {"적용", "제한", "규정", "법률", "요건", "해석", "금지",
                      "판단", "기준", "경우", "여부"}

    @classmethod
    def _doctrine_hit(cls, term: str, q_norm: str) -> bool:
        """법리 어휘 매칭: 공백 제거 질의에 용어 토큰이 합계 4자 이상 등장하되,
        범용 토큰만으로는 불발('제한'+'적용' 오발화 실측 — 비범용 토큰 1개 필수)."""
        toks = [t for t in re.split(r"\s+", term.strip()) if len(t) >= 2]
        matched = [t for t in toks if t in q_norm]
        if not any(t not in cls._DOCTRINE_STOP for t in matched):
            return False
        return sum(len(t) for t in matched) >= 4

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

        tokenized = [doc.split() for doc in documents]
        bm25 = BM25Okapi(tokenized)
        scores = bm25.get_scores(query.split())
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
        self._principles = self._load_principles()
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
    def _load_principles() -> list[dict]:
        """principles.jsonl 전체 로드 (캐시)."""
        if not PRINCIPLES_PATH.exists():
            return []
        records = []
        with open(PRINCIPLES_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
        return records

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
        as_of_date: Optional[str] = None,
        exclude_doc_codes: Optional[set] = None,
        as_of_code: Optional[str] = None,
        doctrine_hints: Optional[list[str]] = None,
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

        # ── 질의문 명시 조문 폴백 힌트 병합 ────────────────
        # Pass 1이 law_hints를 통째로 놓쳐도(17-0651 실측: 힌트 0건 → 명시된
        # 건축법 제2조 원문·프레임 미로딩) 질의문이 직접 거명한 「법령명」
        # 조문·별표는 결정론 추출해 exact fetch·검색 부스트·프레임 로딩에 태운다.
        q_hints = _explicit_query_hints(query)
        if q_hints:
            merged = [h.get("law", str(h)) if isinstance(h, dict) else str(h)
                      for h in (law_hints or [])]
            have_h = {re.sub(r"\s+", "", h) for h in merged}
            for h in q_hints:
                if re.sub(r"\s+", "", h) not in have_h:
                    merged.append(h)
            law_hints = merged

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
            search_q += " " + " ".join(
                h.get("law", str(h)) if isinstance(h, dict) else str(h)
                for h in law_hints[:3]
            )
        if definition_terms:
            search_q += " " + " ".join(
                t.get("term", str(t)) if isinstance(t, dict) else str(t)
                for t in definition_terms[:3]
            )

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

        # ── 상호참조 확장 (경량 1-hop) ────────────────────
        # 검색된 조문 본문이 '시행령 제11조'·'「주택법」 제2조'처럼 다른 조문을 명시적으로
        # 가리키면, 그 조문을 로컬 DB에서 직접 끌어와 컨텍스트에 함께 넣는다(모델 왕복 없음).
        cross_hints = _extract_crossref_hints(law_docs, max_hints=10)
        if cross_hints:
            cross_docs = self._searcher.fetch_exact_articles(cross_hints, top_n=1)
            existing = {f"{d.law_name}::{d.article_no}" for d in law_docs}
            for d in cross_docs:
                dk = f"{d.law_name}::{d.article_no}"
                if dk in existing:
                    continue
                d.score = 1.5            # exact(2.0) 아래, 일반 검색 위 — 뒤쪽 배치
                d.score_type = "crossref"
                law_docs.append(d)
                existing.add(dk)

        # ── 위임 체인 확장 (법→영→규칙 하향 에지) ─────────
        # '대통령령으로 정하는' 류 위임 문구에는 조번호가 없어 위 crossref가
        # 못 따라가는 방향. 빌드타임 lsDelegated 스냅샷(delegation_graph.json)
        # 에서 대상 조문을 로컬 DB로만 끌어온다.
        deleg_hints = _delegation_hints(law_docs, max_hints=6)
        if deleg_hints:
            deleg_docs = self._searcher.fetch_exact_articles(deleg_hints, top_n=1)
            existing = {f"{d.law_name}::{d.article_no}" for d in law_docs}
            for d in deleg_docs:
                dk = f"{d.law_name}::{d.article_no}"
                if dk in existing:
                    continue
                d.score = 1.6            # exact 아래, crossref(1.5) 위 — 위임은 공식 스냅샷 기반
                d.score_type = "delegation"
                law_docs.append(d)
                existing.add(dk)

        # ── 질의회신 선례 검색 (qa_precedents) ────────────
        qa_docs = self._searcher.search_qa(
            search_q, top_k=5,
            as_of_date=as_of_date, exclude_codes=exclude_doc_codes,
            as_of_code=as_of_code,
        )

        # ── 문형 원칙 해석례 페어링 (결정론 훅) ────────────
        # '각 호의 어느 하나'·단서·'등' 같은 법정 문형의 해석 원칙이 도메인
        # 어휘 직교로 검색에서 밀리는 문제 보정(남양주 조례 사안에서 10-0306
        # 미소환 실증). 감지 시 doc_code 직접 조회로 주입 — 컷오프·LOO 준수,
        # 코드당 대표 2청크로 절단해 컨텍스트 비대 방지.
        phrase_codes = _phrase_principle_codes(query, law_docs)
        if phrase_codes:
            have = {d.metadata.get("doc_code", "") for d in qa_docs}
            codes = [c for c in phrase_codes
                     if c not in have
                     and not (exclude_doc_codes and c in exclude_doc_codes)][:3]
            pdocs = self._searcher.fetch_qa_by_codes(codes) if codes else []
            per: dict = {}
            kept = []
            for d in pdocs:
                if _doc_is_after_cutoff(d.metadata, as_of_date, as_of_code):
                    continue
                c = d.metadata.get("doc_code", "")
                if per.get(c, 0) >= 2:
                    continue
                d.score = 1.9
                d.score_type = "phrase_principle"
                kept.append(d)
                per[c] = per.get(c, 0) + 1
            if kept:
                qa_docs = kept + qa_docs

        # ── 판례 검색 (court_cases, PLAN §4.2) ────────────
        case_docs = self._search_cases(
            query, all_laws, relation_types, top_k_case, as_of_date=as_of_date,
            doctrine_hints=doctrine_hints,
        )

        # 항(①②③) 단위 청크를 전체 조문으로 재구성 — 답변·표시에 조문 전체 제공
        law_docs = self._expand_hang_chunks(law_docs)

        return law_docs, qa_docs, case_docs

    _HANG_ORDER = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚"

    def _expand_hang_chunks(self, law_docs):
        """항(①②③) 단위 청크를 같은 조문의 '전체 조문'으로 재구성한다.

        검색은 항 단위로 정밀하게 하되(긴 조문 뒷항 검색 보장), 답변 생성·표시에는
        조문 전체를 제공해 맥락이 잘리지 않게 한다. 같은 (법령, 조) 가 여러 항으로
        매칭되면 1개 doc으로 병합한다(첫 등장 doc의 score·score_type 유지)."""
        if not law_docs:
            return law_docs
        col = self._searcher._law_col
        order = self._HANG_ORDER
        out, seen = [], set()
        for doc in law_docs:
            key = (doc.law_name, doc.article_no)
            if key in seen:
                continue
            seen.add(key)
            try:
                rows = col.get(
                    where={"$and": [
                        {"law_name":   {"$eq": doc.law_name}},
                        {"article_no": {"$eq": doc.article_no}},
                    ]},
                    include=["documents", "metadatas"], limit=50,
                )
                # hang_no별 본문 — 같은 항이 중복(빈 마커 청크 등)이면 본문이 가장 긴 것
                best: dict[str, str] = {}
                title = ""
                for d, m in zip(rows["documents"], rows["metadatas"]):
                    if not title:
                        title = m.get("article_title", "") or ""
                    hn = m.get("hang_no", "")
                    if not hn:
                        continue
                    parts = d.split("\n", 1)
                    body = parts[1].strip() if len(parts) > 1 else ""
                    if len(body) <= 2:      # 마커만 있는 빈 항 청크 제외
                        continue
                    if hn not in best or len(body) > len(best[hn]):
                        best[hn] = body
                if len(best) > 1:
                    items = sorted(
                        best.items(),
                        key=lambda kv: order.index(kv[0]) if kv[0] in order else 999,
                    )
                    header = f"[{doc.law_name}] {doc.article_no} {title}".rstrip()
                    doc.content = header + "\n" + "\n".join(b for _, b in items)
            except Exception:
                pass
            out.append(doc)
        return out

    def _search_cases(
        self,
        query: str,
        all_laws: list[str],
        relation_types: Optional[list[dict]],
        top_k: int,
        as_of_date: Optional[str] = None,
        doctrine_hints: Optional[list[str]] = None,
    ) -> list[RetrievedDoc]:
        """
        weight ≥ 0.5인 유형별로 (법규 × 유형) 쌍 검색 후 RRF 병합.
        weight < 0.5는 court_cases 구축 후 부스트 계수로 활용 예정.

        as_of_date: 'YYYY-MM-DD'. 지정 시 decision_date가 미래인 판례 제외(eval 전용).
        """
        # 법령명만 추출 (조문번호 제거)
        law_names = list(dict.fromkeys(
            re.split(r'\s+제\d+', law)[0].strip()
            for law in all_laws
        ))

        # 페어링·BM25 경로는 Pass1의 relation_types(weight≥0.5)가 있어야 돈다.
        # 반면 doctrine 경로는 법리 어휘 기반이라 relation_type과 무관 —
        # 아래 active 게이트 '밖'에 두어 relation_types가 비어도 항상 실행한다
        # (21-0186 실측: Pass1 relation_types=[]로 case 검색이 통째 early-return
        # 되며 doctrine까지 막혀 계열 판례 94누2985가 미소환됐던 결함 수정).
        active = ([rt for rt in relation_types if rt.get("weight", 0) >= 0.5]
                  if relation_types else [])
        cases = []
        if active:
            typed_results = []
            for rt in active:
                docs = self._searcher.search_cases_by_type(
                    query, law_names, rt["type"], top_k=top_k
                )
                typed_results.append((docs, rt.get("weight", 1.0)))
            bm25_docs = self._searcher.bm25_search_cases(query, top_k=top_k)
            cases = merge_case_results(typed_results, bm25_docs, top_k=top_k)

        # ── 법리(doctrine) 경로: 판례 역할 기반 소환 ─────
        # 페어링·벡터는 사건 어휘가 지배해 타 도메인 법리 판례(침익 엄격해석,
        # 병존 등)가 묻힌다. doctrine_terms가 질의의 법리 어휘와 맞으면
        # 순위 밖이어도 주입한다 (최대 3건 — 2건이면 같은 계열의 원칙 판례가
        # 캡을 채워 한계 판례(2024두50421류)가 밀리는 편향 실측, case_id 중복 제거).
        have_ids = {c.metadata.get("case_id", "") for c in cases}
        cases.extend(self._searcher.search_cases_by_doctrine(
            query, exclude_ids=have_ids, max_hits=3,
            hints_text=" ".join(doctrine_hints or [])))

        # 시점 컷오프: 판결일이 미래인 판례 제외 (eval 전용)
        if as_of_date:
            cases = [c for c in cases if not _doc_is_after_cutoff(c.metadata, as_of_date)]
        return cases

    @staticmethod
    def apply_date_cutoff(
        docs: list,
        as_of_date: Optional[str],
        exclude_codes: Optional[set] = None,
        as_of_code: Optional[str] = None,
    ) -> list:
        """문서 리스트에서 시점 이후 자료·제외 코드를 걸러낸다.

        원칙·메모 페어링(fetch_*_sources)처럼 doc_code 직접 fetch로 검색 컷오프를
        우회하는 경로에 사후 적용하기 위한 공용 필터. eval 전용.
        """
        if not as_of_date and not exclude_codes and not as_of_code:
            return docs
        exclude_codes = exclude_codes or set()
        out = []
        for d in docs:
            meta = getattr(d, "metadata", {}) or {}
            code = meta.get("doc_code", "") or meta.get("case_id", "")
            if code and code in exclude_codes:
                continue
            if _doc_is_after_cutoff(meta, as_of_date, as_of_code):
                continue
            out.append(d)
        return out

    def doctrine_vocab_inventory(self) -> list[tuple[str, list[str]]]:
        """횡단 판례 (계열, 법리 어휘) 목록 — Pass1 doctrine_hints 선택지 위임."""
        return self._searcher.doctrine_vocab_inventory()

    def retrieve_memos(self, query: str, top_k: int = 3) -> list[dict]:
        """질의와 관련된 해석 원칙 메모 검색 (memos 컬렉션)."""
        return self._searcher.search_memos(query, top_k=top_k)

    def retrieve_principles(self, query: str, top_k: int = 2) -> list[dict]:
        """질의와 관련된 일반 법리 원칙 검색 (principles 컬렉션)."""
        return self._searcher.search_principles(query, top_k=top_k)

    def search_amendments_semantic(self, query: str, top_k: int = 3) -> list[dict]:
        """쿼리 의미 기반으로 개정이력 직접 검색. '방화문 기준이 어떻게 바뀌었나' 등."""
        return self._searcher.search_amendments_semantic(
            query, self._amendments, top_k=top_k
        )

    def create_session_collection(self, session_id: str) -> None:
        self._searcher.create_session_collection(session_id)

    def index_uploaded_chunks(self, session_id: str, chunks: list[dict], thread_id: str = "") -> int:
        return self._searcher.index_uploaded_chunks(session_id, chunks, thread_id)

    def search_uploaded(self, session_id: str, query: str, top_k: int = 5,
                        thread_id: str = "", context: str = "",
                        force_articles: Optional[list] = None,
                        query_regions: Optional[list] = None) -> list:
        # 사용자 업로드 + 내장 지역 조례 팩을 하나의 스트림으로 (업로드 우선, 중복 제거)
        res = self._searcher.search_uploaded(
            session_id, query, top_k, thread_id, context, force_articles,
            query_regions=query_regions)
        have = {(d.law_name, d.article_no) for d in res}
        res += self._searcher.search_region(
            query, top_k=top_k, context=context,
            force_articles=force_articles, exclude=have)
        return res

    def list_uploaded_docs(self, session_id: str) -> list[dict]:
        return self._searcher.list_uploaded_docs(session_id)

    def list_region_laws(self) -> list[dict]:
        return self._searcher.list_region_laws()

    def index_region_chunks(self, region: str, chunks: list[dict]) -> int:
        return self._searcher.index_region_chunks(region, chunks)

    def get_ordinance_article_text(self, session_id: str, law_name: str,
                                   art_root: str = "제1조") -> str:
        return self._searcher.get_ordinance_article_text(session_id, law_name, art_root)

    def match_regions(self, text: str) -> list[str]:
        return self._searcher.match_regions(text)

    def upsert_ordinance_registry(self, region: str, law_name: str, detail: dict) -> None:
        self._searcher.upsert_ordinance_registry(region, law_name, detail)

    def get_ordinance_registry(self, region: str = "") -> list[dict]:
        return self._searcher.get_ordinance_registry(region)

    def fetch_exact_articles(self, law_hints: list[str], top_n: int = 5) -> list[RetrievedDoc]:
        """law_hints에 명시된 법령 조문을 강제로 가져오는 wrapper 메서드"""
        return self._searcher.fetch_exact_articles(law_hints, top_n)

    def delete_uploaded_doc(self, session_id: str, law_name: str) -> int:
        return self._searcher.delete_uploaded_doc(session_id, law_name)

    def delete_session_collection(self, session_id: str) -> None:
        self._searcher.delete_session_collection(session_id)

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
            doc_ref  = d.metadata.get("doc_ref", "")
            doc_code = d.metadata.get("doc_code", "")
            if doc_ref:
                retrieved_ids.add(doc_ref)
            if doc_code:
                retrieved_ids.add(doc_code)

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
            조문_변경 = rec.get("조문_변경", [])

            for item in 조문_변경:
                art_norm = item.get("조문", "").replace(" ", "")
                m = re.match(r'(제\d+조)', art_norm)
                if not m:
                    continue
                art_prefix = m.group(1)
                if (law_name, art_prefix) in retrieved_pairs:
                    matched.append(rec)
                    seen_ids.add(aid)
                    break

        return matched

    # ----------------------------------------------------------
    # 원칙·메모 → 출처 페어링 (인용된 해석례·판례 강제 동반)
    # ----------------------------------------------------------

    _LAWBUREAU_ID_PAT = re.compile(r'^\d{2}-\d{4}$')
    _COURT_CASE_ID_PAT = re.compile(r'^\d{2,4}[가-힣]\d{3,5}$')

    def fetch_principle_sources(
        self,
        principles_docs: list[dict],
    ) -> tuple[list[RetrievedDoc], list[RetrievedDoc]]:
        """
        검색된 원칙(principles_docs)의 source_precedents/source_cases에 명시된
        해석례·판례를 강제로 가져온다. 원칙 텍스트가 인용한 출처를 LLM이 raw 텍스트로
        함께 참조할 수 있게 만들어, '원칙 + 출처 인용문언' 페어를 답변에 노출시킨다.

        반환: (qa 페어, case 페어)
        """
        if not principles_docs:
            return [], []
        qa_codes: set[str] = set()
        case_ids: set[str] = set()
        for p in principles_docs:
            sp = p.get("source_precedents", "")
            if isinstance(sp, str):
                sp = [c.strip() for c in sp.split(",") if c.strip()]
            for c in sp:
                qa_codes.add(c)
            sc = p.get("source_cases", "")
            if isinstance(sc, str):
                sc = [c.strip() for c in sc.split(",") if c.strip()]
            for c in sc:
                case_ids.add(c)
        extra_qa = self._searcher.fetch_qa_by_codes(sorted(qa_codes))
        extra_cs = self._searcher.fetch_cases_by_ids(sorted(case_ids))
        return extra_qa, extra_cs

    def fetch_memo_sources(
        self,
        memo_docs: list[dict],
    ) -> tuple[list[RetrievedDoc], list[RetrievedDoc]]:
        """
        검색된 메모(memo_docs)의 linked_to에 명시된 해석례·판례를 강제로 가져온다.
        ID 형식으로 자동 분류:
          - 'NN-NNNN' (법제처 해석례) → qa_precedents
          - 'YY+한글+숫자' (대법원 판례) → court_cases
        """
        if not memo_docs:
            return [], []
        qa_codes: set[str] = set()
        case_ids: set[str] = set()
        for m in memo_docs:
            lt = m.get("linked_to", "")
            if isinstance(lt, str):
                lt = [x.strip() for x in lt.split(",") if x.strip()]
            for x in lt:
                if self._LAWBUREAU_ID_PAT.match(x):
                    qa_codes.add(x)
                elif self._COURT_CASE_ID_PAT.match(x):
                    case_ids.add(x)
        extra_qa = self._searcher.fetch_qa_by_codes(sorted(qa_codes))
        extra_cs = self._searcher.fetch_cases_by_ids(sorted(case_ids))
        return extra_qa, extra_cs

    def get_article_roles(
        self,
        law_hints: list[str],
        definition_terms: Optional[list[str]] = None,
    ) -> list[dict]:
        """law_hints + definition_terms로 조문 해석 프레임 JSON 로드."""
        return load_article_roles(law_hints, definition_terms=definition_terms)

    def explicit_query_hints(self, query: str) -> list[str]:
        """질의문 명시 「법령명」 조문·별표의 결정론 폴백 힌트 (Pass1 실패 대비)."""
        return _explicit_query_hints(query)

    def detect_blind_spots(self, law_hints: list[str]) -> dict:
        """law_hints 중 DB 미수록 법령(API 패치 가능) + 수동 확인 필요 항목 식별."""
        return self._searcher.detect_blind_spots(law_hints)

    def format_context(
        self,
        law_docs: list[RetrievedDoc],
        qa_docs: list[RetrievedDoc],
        case_docs: list[RetrievedDoc],
        article_roles: Optional[list[dict]] = None,
        principles_docs: Optional[list[dict]] = None,
        memo_docs: Optional[list[dict]] = None,
        amendment_docs: Optional[list[dict]] = None,
        amendment_semantic_docs: Optional[list[dict]] = None,
        uploaded_docs: Optional[list] = None,
    ) -> str:
        """
        검색 결과를 Pass 2 LLM 컨텍스트로 포맷 (PLAN §2.2).
        0층: 조문 해석 프레임 / 1층: 법령 조문 / 2층: 질의회신 선례 / 3층: 판례
        memo층: 관련 해석 원칙 메모 (always-on이 아닌 케이스-특정 원칙)
        amendment_semantic_docs: 의미 검색으로 찾은 개정이력 (조문 매칭과 별도)
        """
        lines = []

        # ── 업로드 문서층 ────────────────────────────────
        if uploaded_docs:
            lines.append("=== [사용자 업로드·내장 조례 법령] ===")
            lines.append("※ 아래는 사용자가 업로드했거나 시스템에 내장된 조례·법령 조문입니다. 질의와 관련된 경우 우선 참조하세요.")
            for doc in uploaded_docs:
                lines.append(f"\n[{doc.law_name} {doc.article_no}]")
                lines.append(doc.content)

        # ── 개정연혁층: 목적론적 해석 재료 ──────────────
        if amendment_docs:
            lines.append("=== [관련 개정연혁] ===")
            lines.append(
                "※ 아래는 검색된 조문의 개정 이유 및 입법 목적입니다. "
                "목적론적 해석 시 반드시 참조하세요."
            )
            for i, rec in enumerate(amendment_docs, 1):
                lines.append(
                    f"\n[입법요지{i}] {rec.get('law_name','')} {rec.get('시행일','')} "
                    f"{rec.get('공포번호','')}"
                )
                lines.append(f"개정이유: {rec.get('개정이유','')}")
                키포인트 = rec.get('목적론적_키포인트', '')
                if 키포인트:
                    if isinstance(키포인트, list):
                        lines.append("목적론적 키포인트:")
                        for kp in 키포인트:
                            lines.append(f"  · {kp}")
                    else:
                        lines.append(f"목적론적 키포인트: {키포인트}")
                주요내용 = rec.get('주요내용', '')
                if 주요내용:
                    if isinstance(주요내용, str):
                        lines.append(f"주요 개정 내용: {주요내용}")
                    else:
                        lines.append("주요 개정 내용:")
                        for item in 주요내용:
                            조문 = ", ".join(item.get('조문', []))
                            lines.append(f"  · [{조문}] {item.get('항목','')}: {item.get('내용','')}")
                부칙 = rec.get('부칙_상세', [])
                if 부칙:
                    lines.append("부칙(적용례·경과조치):")
                    if isinstance(부칙, dict):
                        for k, v in 부칙.items():
                            v_str = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                            lines.append(f"  · {k}: {v_str[:200]}")
                    else:
                        for b in 부칙:
                            if isinstance(b, dict):
                                lines.append(f"  · {b.get('조항','')}: {b.get('내용','')}")
                            else:
                                lines.append(f"  · {b}")
                연동 = rec.get('연동_조문_주의', '')
                if 연동:
                    lines.append(f"※ 연동 개정: {연동}")
                연관 = rec.get('연관_개정', [])
                if 연관:
                    lines.append(f"※ 연관 개정: {', '.join(연관[:5])}")

        # ── 개정이력 검색 결과층: 의미 검색 기반 ─────────
        if amendment_semantic_docs:
            # amendment_docs에 이미 포함된 ID는 중복 렌더링 제외
            existing_ids: set[str] = set()
            if amendment_docs:
                existing_ids = {
                    rec.get("amendment_id", "") for rec in amendment_docs
                }
            unique_semantic = [
                rec for rec in amendment_semantic_docs
                if rec.get("amendment_id", "") not in existing_ids
            ]
            if unique_semantic:
                lines.append("\n=== [개정이력 검색 결과] ===")
                lines.append(
                    "※ 아래는 질의와 의미적으로 관련된 개정이력입니다. "
                    "목적론적 해석 시 참조하세요."
                )
                _amend_offset = len(amendment_docs) if amendment_docs else 0
                for j, rec in enumerate(unique_semantic, _amend_offset + 1):
                    lines.append(
                        f"\n[입법요지{j}] {rec.get('law_name','')} {rec.get('시행일','')} "
                        f"{rec.get('공포번호','')}"
                    )
                    lines.append(f"개정이유: {rec.get('개정이유','')}")
                    키포인트 = rec.get('목적론적_키포인트', '')
                    if 키포인트:
                        if isinstance(키포인트, list):
                            lines.append("목적론적 키포인트:")
                            for kp in 키포인트:
                                lines.append(f"  · {kp}")
                        else:
                            lines.append(f"목적론적 키포인트: {키포인트}")
                    주요내용 = rec.get('주요내용', '')
                    if 주요내용:
                        if isinstance(주요내용, str):
                            lines.append(f"주요 개정 내용: {주요내용}")
                        else:
                            lines.append("주요 개정 내용:")
                            for item in 주요내용:
                                조문 = ", ".join(item.get('조문', []))
                                lines.append(f"  · [{조문}] {item.get('항목','')}: {item.get('내용','')}")
                    부칙 = rec.get('부칙_상세', [])
                    if 부칙:
                        lines.append("부칙(적용례·경과조치):")
                        if isinstance(부칙, dict):
                            for k, v in 부칙.items():
                                v_str = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                                lines.append(f"  · {k}: {v_str[:200]}")
                        else:
                            for b in 부칙:
                                if isinstance(b, dict):
                                    lines.append(f"  · {b.get('조항','')}: {b.get('내용','')}")
                                else:
                                    lines.append(f"  · {b}")
                    연동 = rec.get('연동_조문_주의', '')
                    if 연동:
                        lines.append(f"※ 연동 개정: {연동}")
                    연관 = rec.get('연관_개정', [])
                    if 연관:
                        lines.append(f"※ 연관 개정: {', '.join(연관[:5])}")

        # ── principles층: 일반 법리 원칙 ────────────────
        if principles_docs:
            lines.append("=== [관련 법리 원칙] ===")
            lines.append(
                "아래는 이 질의에 발동될 수 있는 일반 법리 원칙입니다. "
                "본 건에 실제 적용 가능한지 판단한 후 활용하세요:"
            )
            for p in principles_docs:
                pid   = p.get("principle_id", "")
                title = p.get("title", "")
                lines.append(f"\n[{pid}] {title}")
                lines.append(p.get("content", ""))
                exc = p.get("exception", "")
                if exc:
                    lines.append(f"  ※ 예외: {exc}")
                sc = p.get("source_cases", "")
                sp = p.get("source_precedents", "")
                if sc:
                    lines.append(f"  근거 판례: {sc}")
                if sp:
                    lines.append(f"  근거 선례: {sp}")

        # ── memo층: 관련 해석 원칙 메모 ─────────────────
        if memo_docs:
            lines.append("=== [관련 해석 원칙 메모] ===")
            lines.append(
                "아래는 유사 사안에서 확립된 해석 원칙입니다. 본 건과 관련된 원칙이 있으면 적용하세요.\n"
                "⚠ 중요 — 메모는 인용 마커가 아닙니다. 'memo_NNN' 자체를 답변 본문에 인용하지 마세요.\n"
                "메모의 원칙을 답변에 활용할 때는 메모의 '원출처(linked_to)'에 명시된 "
                "해석례·판례를 [해석례N] 또는 [판례N] 마커로 인용하세요.\n"
                "  · 원출처가 [참조 자료 목록]에 있으면 → 해당 번호로 마커 사용\n"
                "  · 원출처가 목록에 없으면 → 본문에 출처명만 적고 마커는 생략 "
                "(예: \"법제처 22-0155에 따르면 ~\")"
            )
            for m in memo_docs:
                mid    = m.get("memo_id", "")
                title  = m.get("title", "")
                linked = m.get("linked_to", "")
                if isinstance(linked, list):
                    linked_str = ", ".join(str(x) for x in linked)
                else:
                    linked_str = str(linked)
                # 대괄호 제거 — 모델이 인용 마커로 오인하지 않도록
                lines.append(
                    f"\n● 메모 {mid} (원출처: {linked_str or '미지정'})"
                )
                lines.append(f"  제목: {title}")
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
            lines.append("=== [법령원문] ===")
            lines.append(
                "※ 아래는 질문에서 특정된 조문을 DB에서 직접 가져온 법령원문입니다. "
                "이 내용을 답변의 1차 근거로 삼고, 인용 시 [법령원문N] 마커를 사용하세요."
            )
            for i, doc in enumerate(exact_docs, 1):
                lines.append(f"\n[법령원문{i}] {doc.law_name} {doc.article_no}")
                lines.append(doc.content)

        if vector_docs:
            lines.append("\n=== [관련 법령 조문] ===")
            for i, doc in enumerate(vector_docs, 1):
                lines.append(f"\n[법령{i}] {doc.law_name} {doc.article_no}")
                lines.append(doc.content)

        # ── 2층: 질의회신 선례 ──────────────────────────
        if qa_docs:
            lines.append("\n=== [유사 질의회신 선례] ===")
            for i, doc in enumerate(qa_docs, 1):
                meta = doc.metadata
                doc_ref    = meta.get("doc_ref", "")
                doc_agency = meta.get("doc_agency", "")
                doc_date   = meta.get("doc_date", "")
                header = f"\n[해석례{i}]"
                if doc_ref:
                    header += f" {doc_ref}"
                elif doc_agency:
                    label = doc_agency
                    if doc_date:
                        label += f" ({doc_date})"
                    header += f" {label}"
                # 출처 위계 마커 — T3(중앙부처)·T4(지자체) 회신은 '실무 확인
                # 사례'로 별도 제시 대상임을 모델에게 표시 (PASS2 출처 원칙 4번)
                if meta.get("tier") in ("T3", "T4"):
                    header += f" 〔실무 확인 사례·{meta['tier']}〕"
                # 인용 표기: 모델이 본문에서 이 선례를 인용할 때 그대로 써야 하는
                # 문자열(팝업 연결·소독기 보호가 이 표기에 걸려 있음)
                if meta.get("cite_label"):
                    header += f'\n(인용 표기: "{meta["cite_label"]}" — 이 선례 인용 시 반드시 이 표기를 그대로 사용)'
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
