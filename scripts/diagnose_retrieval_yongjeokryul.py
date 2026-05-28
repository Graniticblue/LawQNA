#!/usr/bin/env python3
"""
용적률 질의로 실제 retrieval을 돌려 어떤 자료가 잡히는지 종합 진단.
법제처 답변이 인용한 핵심 자료:
  - 대법원 2006다81035 (문언 명확 원칙)
  - 법제처 21-0142 (용적률 예외규정 엄격해석)
이 두 자료가 어디 컬렉션에 있고 retrieval에서 잡히는지 확인.
"""
import importlib.util
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

_REPO = Path(__file__).parent.parent
from dotenv import load_dotenv
load_dotenv(_REPO / ".env")

# Retriever만 로드 (Generator API 불필요)
spec = importlib.util.spec_from_file_location(
    "retriever", _REPO / "pipeline" / "05_Retriever.py",
)
ret = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ret)

QUERY = (
    "건축물이 있는 대지가 너비 25미터 미만인 도로에 20미터 이상 접하고 있고, "
    "그 도로가 해당 대지의 전면도로가 아닌 경우, "
    "해당 대지안의 건축물에 국토계획법 시행령 제85조제7항제1호 또는 제2호가 적용되어 "
    "용적률을 완화 받을 수 있는지?"
)

# Pass 1 보강된 검색 컨텍스트 (DEF_EXP, '그 밖에 건축이 금지된 공지' 보강)
SEARCH_QUERY = (
    QUERY
    + " 그 밖에 건축이 금지된 공지 그 밖의 토지 전면도로 도로 "
    + "공원 광장 하천 용적률 완화"
)

print("Retriever 초기화 중...")
retriever = ret.Retriever()
print("초기화 완료\n")

# 검색 실행 (Pass 1이 만들어내는 컨텍스트와 비슷하게)
law_docs, qa_docs, case_docs = retriever.retrieve(
    query=SEARCH_QUERY,
    question_type="복수조문탐색형",
    relation_types=[
        {"type": "DEF_EXP",  "weight": 1.0},
        {"type": "SCOPE_CL", "weight": 0.7},
    ],
    law_hints=[
        "국토의 계획 및 이용에 관한 법률 시행령 제85조제7항",
        "국토의 계획 및 이용에 관한 법률 제78조제4항",
    ],
    definition_terms=[
        "그 밖에 건축이 금지된 공지",
        "전면도로",
        "도로",
    ],
)
principles_docs = retriever.retrieve_principles(SEARCH_QUERY, top_k=3)
linked_memos = retriever.fetch_linked_memos(law_docs, qa_docs, case_docs)
semantic_memos = retriever.retrieve_memos(SEARCH_QUERY, top_k=3)
_seen = {m.get("memo_id", "") for m in linked_memos if m.get("memo_id")}
memo_docs = list(linked_memos)
for m in semantic_memos:
    mid = m.get("memo_id", "")
    if mid and mid not in _seen:
        memo_docs.append(m)
        _seen.add(mid)

# 원칙·메모 → 출처 페어링 (NEW)
paired_qa_p, paired_cs_p = retriever.fetch_principle_sources(principles_docs)
paired_qa_m, paired_cs_m = retriever.fetch_memo_sources(memo_docs)
seen_qa_codes = {d.metadata.get("doc_code", "") for d in qa_docs if d.metadata.get("doc_code")}
for d in paired_qa_p + paired_qa_m:
    code = d.metadata.get("doc_code", "")
    if code and code not in seen_qa_codes:
        qa_docs.insert(0, d)
        seen_qa_codes.add(code)
seen_case_ids = {d.metadata.get("case_id", "") for d in case_docs if d.metadata.get("case_id")}
for d in paired_cs_p + paired_cs_m:
    cid = d.metadata.get("case_id", "")
    if cid and cid not in seen_case_ids:
        case_docs.insert(0, d)
        seen_case_ids.add(cid)

# ── 결과 표시 ────────────────────────────────────────────────
print("=" * 70)
print(f"[law_docs] {len(law_docs)}건")
for d in law_docs:
    print(f"  - {d.law_name} {d.article_no} (score={d.score:.3f}, type={d.score_type})")

print(f"\n[qa_docs] {len(qa_docs)}건 (해석례)")
for d in qa_docs:
    code = d.metadata.get("doc_code", "")
    print(f"  - {code} | {d.metadata.get('question', '')[:60]}")

print(f"\n[case_docs] {len(case_docs)}건 (판례)")
for d in case_docs:
    cid = d.metadata.get("case_id", d.article_no)
    print(f"  - {cid} | {d.law_name[:50]}")

print(f"\n[principles_docs] {len(principles_docs)}건")
for p in principles_docs:
    print(f"  - {p.get('principle_id')}: {p.get('title')}")
    print(f"      source_cases:      {p.get('source_cases')}")
    print(f"      source_precedents: {p.get('source_precedents')}")

print(f"\n[memo_docs] {len(memo_docs)}건")
for m in memo_docs:
    print(f"  - {m.get('memo_id')}: {m.get('title', '')[:60]}")
    print(f"      linked_to: {m.get('linked_to')}")

# ── 핵심 자료 누락 진단 ─────────────────────────────────────
print("\n" + "=" * 70)
print("[핵심 자료 누락 진단]")
print("=" * 70)

# 21-0142 in qa_docs?
has_21_0142 = any(d.metadata.get("doc_code") == "21-0142" for d in qa_docs)
print(f"법제처 21-0142 (용적률 예외규정 엄격해석): {'✓ 검색됨' if has_21_0142 else '✗ DB에 없음/검색 안 됨'}")

# 2006다81035 in case_docs?
has_2006da = any(d.metadata.get("case_id", "") == "2006다81035" for d in case_docs)
print(f"대법원 2006다81035 (문언 명확 원칙):     {'✓ 검색됨' if has_2006da else '✗ 검색 안 됨'}")

# 대체 활용 가능 자료 ── 예외규정 엄격해석 패턴
print(f"\n[대체 활용 가능 자료 — 예외규정 엄격해석 원칙]")
elig_principles = [p for p in principles_docs if 'EXCEPT' in str(p.get('title', '')) or '예외' in str(p.get('title', '')) or '엄격' in str(p.get('title', ''))]
for p in elig_principles:
    print(f"  · {p.get('principle_id')}: {p.get('title')}")
elig_memos = [m for m in memo_docs if '예외' in str(m.get('title', '')) or '엄격' in str(m.get('title', '')) or '제한' in str(m.get('title', ''))]
for m in elig_memos:
    print(f"  · {m.get('memo_id')}: {m.get('title', '')[:60]}")
