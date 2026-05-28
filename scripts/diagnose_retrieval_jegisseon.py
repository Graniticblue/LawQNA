#!/usr/bin/env python3
"""제93조 기존 건축물 특례 질의로 P-008 페어링 효과 검증.

기대: P-008이 principles_docs에 잡히고, source_precedents에 명시된
      24-0241, 14-0171, 13-0246, 20-0156, 20-0535 5건이 qa_docs에
      자동 페어링되어야 함.
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
    "「국토의 계획 및 이용에 관한 법률 시행령」 제93조제2항의 특례를 적용받아 "
    "기존의 건축물에 대하여 기존 부지 내에서 연면적 및 층수를 늘리는 증축을 완료한 경우, "
    "그 건축물을 기존 용도로 계속 사용하기 위해 같은 조 제1항의 특례를 다시 적용받아 "
    "대수선할 수 있는지?"
)
SEARCH_Q = QUERY + " 기존건축물 특례 제93조 부적합 증축 개축 대수선 재축 동일 건축물 재적용 반복 적용"

print("Retriever 초기화 중...")
retriever = ret.Retriever()
print("초기화 완료\n")

law_docs, qa_docs, case_docs = retriever.retrieve(
    query=SEARCH_Q,
    question_type="복수조문탐색형",
    relation_types=[
        {"type": "DEF_EXP", "weight": 1.0},
        {"type": "EXCEPT",  "weight": 0.8},
    ],
    law_hints=[
        "국토의 계획 및 이용에 관한 법률 시행령 제93조",
        "국토의 계획 및 이용에 관한 법률 제82조",
    ],
    definition_terms=["기존의 건축물"],
)
principles_docs = retriever.retrieve_principles(SEARCH_Q, top_k=3)
linked_memos = retriever.fetch_linked_memos(law_docs, qa_docs, case_docs)
semantic_memos = retriever.retrieve_memos(SEARCH_Q, top_k=3)
_seen = {m.get("memo_id", "") for m in linked_memos if m.get("memo_id")}
memo_docs = list(linked_memos)
for m in semantic_memos:
    mid = m.get("memo_id", "")
    if mid and mid not in _seen:
        memo_docs.append(m)
        _seen.add(mid)

# 페어링 적용
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
    pid = p.get("principle_id")
    title = p.get("title", "")[:70]
    print(f"  - {pid}: {title}")

print(f"\n[qa_docs] {len(qa_docs)}건")
for d in qa_docs:
    code = d.metadata.get("doc_code", "")
    q = d.metadata.get("question", "")[:55]
    score_tag = "★" if d.score_type == "paired" else " "
    print(f"  {score_tag} {code:10s} | {q}")

print(f"\n[case_docs] {len(case_docs)}건")
for d in case_docs:
    cid = d.metadata.get("case_id", d.article_no)
    score_tag = "★" if d.score_type == "paired" else " "
    print(f"  {score_tag} {cid}")

print(f"\n[memo_docs] {len(memo_docs)}건")
for m in memo_docs:
    print(f"  - {m.get('memo_id')}: {m.get('title', '')[:60]}")

# 5건 검증
print("\n" + "=" * 70)
print("[5건 검증]")
TARGETS = ["24-0241", "14-0171", "13-0246", "20-0156", "20-0535"]
qa_codes_in = {d.metadata.get("doc_code", "") for d in qa_docs}
for t in TARGETS:
    ok = "✓" if t in qa_codes_in else "✗"
    print(f"  {ok} {t}")

# P-008 검증
p_ids = {p.get("principle_id") for p in principles_docs}
print(f"\nP-008 검색됨: {'✓' if 'P-008' in p_ids else '✗'}")
