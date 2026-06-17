#!/usr/bin/env python3
"""수직증축형 리모델링 질의로 P-009 페어링 효과 검증.

기대: P-009가 검색되고, source_precedents (23-0262, 14-0405)가 자동 페어링됨.
또한 Pass 1 보강 효과로 「주택법」 제46조제1항 같은 약칭 재정의 조문도 law_hints에
포함되어 검색되는지(이건 Pass 1 호출 + retrieve로만 확인 가능 — 여기선 의미 검색 진단까지).
"""
import importlib.util
import sys
import warnings
warnings.filterwarnings("ignore")
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

_REPO = Path(__file__).parent.parent
from dotenv import load_dotenv
load_dotenv(_REPO / ".env")

spec = importlib.util.spec_from_file_location(
    "retriever", _REPO / "pipeline" / "05_Retriever.py",
)
ret = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ret)

QUERY = (
    "공동주택의 1층을 필로티 구조로 전용하여 세대수를 증가하지 않고 수직으로 증축하는 행위가 "
    "「주택법」 제2조제25호다목 단서에 따른 '수직증축형 리모델링'에 포함되는지, "
    "그리고 같은 법 제68조제4항 전단 및 제69조제2항에 규정된 '수직증축형 리모델링'에 "
    "세대수를 증가하지 않는 수직증축 리모델링이 포함되는지?"
)
SEARCH_Q = QUERY + " 약칭 재정의 수직증축형 리모델링 세대수 증가형 단서 본문 제46조 포함한다 이하 같다"

print("Retriever 초기화 중...")
retriever = ret.Retriever()
print("초기화 완료\n")

law_docs, qa_docs, case_docs = retriever.retrieve(
    query=SEARCH_Q,
    question_type="복수조문탐색형",
    relation_types=[
        {"type": "DEF_EXP",  "weight": 1.0},
        {"type": "SCOPE_CL", "weight": 0.7},
    ],
    law_hints=[
        "주택법 제2조제25호",
        "주택법 제46조",
        "주택법 제68조",
        "주택법 제69조",
    ],
    definition_terms=["수직증축형 리모델링", "세대수 증가형 리모델링"],
)
principles_docs = retriever.retrieve_principles(SEARCH_Q, top_k=5)
linked_memos = retriever.fetch_linked_memos(law_docs, qa_docs, case_docs)
semantic_memos = retriever.retrieve_memos(SEARCH_Q, top_k=3)
_seen = {m.get("memo_id", "") for m in linked_memos if m.get("memo_id")}
memo_docs = list(linked_memos)
for m in semantic_memos:
    mid = m.get("memo_id", "")
    if mid and mid not in _seen:
        memo_docs.append(m)
        _seen.add(mid)

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

print(f"[principles_docs] {len(principles_docs)}건")
for p in principles_docs:
    print(f"  - {p.get('principle_id')}: {p.get('title', '')[:70]}")

print(f"\n[qa_docs] {len(qa_docs)}건")
for d in qa_docs:
    code = d.metadata.get("doc_code", "")
    q = d.metadata.get("question", "")[:50]
    tag = "★" if d.score_type == "paired" else " "
    print(f"  {tag} {code:10s} | {q}")

print(f"\n[law_docs] {len(law_docs)}건 (주택법 + 시행령)")
seen_arts: set = set()
for d in law_docs:
    key = (d.law_name, d.article_no)
    if key in seen_arts:
        continue
    seen_arts.add(key)
    print(f"  - {d.law_name} {d.article_no} (score={d.score:.3f}, {d.score_type})")

# 검증
print("\n" + "=" * 70)
print("[P-009 페어링 검증]")
TARGETS = ["23-0262", "14-0405"]
qa_codes_in = {d.metadata.get("doc_code", "") for d in qa_docs}
for t in TARGETS:
    ok = "✓" if t in qa_codes_in else "✗"
    print(f"  {ok} {t}")

p_ids = {p.get("principle_id") for p in principles_docs}
print(f"\nP-009 검색됨: {'✓' if 'P-009' in p_ids else '✗'}")
