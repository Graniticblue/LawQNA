#!/usr/bin/env python3
"""
테스트 모드 통합 테스트 — Retriever + 제외 로직만 검증 (LLM 호출 없음).

검증 시나리오:
  1. 일반 검색: "토지등소유자 1인 재개발사업 타당성검증" → 26-0202가 qa_docs에 포함
  2. 테스트 모드: "토지등소유자 1인 재개발사업 타당성검증 [26-0202]" → 26-0202 제외
  3. memo_026 (linked_to: ["26-0202"]) 도 함께 제외되는지 확인
"""
import importlib.util
import re
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

_REPO = Path(__file__).parent.parent

# Retriever 로드
spec = importlib.util.spec_from_file_location(
    "retriever", _REPO / "pipeline" / "05_Retriever.py",
)
ret = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ret)

# Generator의 extract/필터 함수 로드
gen_spec = importlib.util.spec_from_file_location(
    "generator", _REPO / "pipeline" / "06_Generator.py",
)
# Generator class 초기화 회피 — 함수만 가져오기 위해 모듈은 import하지 않고 함수만 재구현
_LAWBUREAU_PATTERN = re.compile(r'(?<!\d)(\d{2}-\d{4})(?!\d)')
_COURT_CASE_PATTERN = re.compile(r'(?<![가-힣\d])(\d{2,4}[가-힣]\d{3,5})(?!\d)')

def extract_test_exclusions(query: str) -> list[str]:
    excl: set[str] = set()
    excl.update(_LAWBUREAU_PATTERN.findall(query))
    excl.update(_COURT_CASE_PATTERN.findall(query))
    return sorted(excl)

def _memo_linked_str(m: dict) -> str:
    lt = m.get("linked_to", "")
    if isinstance(lt, list):
        return ",".join(str(x) for x in lt)
    return str(lt)


print("Retriever 초기화 중 (임베딩 모델 로드)...")
retriever = ret.Retriever()
print("초기화 완료\n")

# ── 시나리오 1: 일반 검색 (제외 없음) ──
print("=" * 60)
print("[시나리오 1] 일반 검색 — 제외 없음")
print("=" * 60)
query1 = "도시정비법 제78조제3항 타당성검증 1인 재개발사업"
law_docs, qa_docs, case_docs = retriever.retrieve(
    query=query1,
    relation_types=[{"type": "EXCEPT", "weight": 1.0}],
    law_hints=["도시 및 주거환경정비법 제78조"],
)
principles_docs = retriever.retrieve_principles(query1, top_k=2)
linked_memos = retriever.fetch_linked_memos(law_docs, qa_docs, case_docs)
semantic_memos = retriever.retrieve_memos(query1, top_k=3)
_seen = {m.get("memo_id", "") for m in linked_memos if m.get("memo_id")}
memo_docs = list(linked_memos)
for m in semantic_memos:
    mid = m.get("memo_id", "")
    if mid and mid not in _seen:
        memo_docs.append(m)
        _seen.add(mid)

print(f"qa_docs: {len(qa_docs)}건")
for d in qa_docs[:3]:
    print(f"  - {d.metadata.get('doc_code', '')} | {d.metadata.get('question', '')[:50]}")
print(f"principles_docs: {[p.get('principle_id') for p in principles_docs]}")
print(f"memo_docs: {[m.get('memo_id') for m in memo_docs]}")

# 26-0202가 qa_docs에 포함되는지 확인
has_26_0202_qa = any(d.metadata.get("doc_code") == "26-0202" for d in qa_docs)
has_memo_026 = any(m.get("memo_id") == "memo_026" for m in memo_docs)
print(f"\n→ 26-0202 검색됨: {has_26_0202_qa}")
print(f"→ memo_026 검색됨: {has_memo_026}")

# ── 시나리오 2: 테스트 모드 (26-0202 명시) ──
print("\n" + "=" * 60)
print("[시나리오 2] 테스트 모드 — '[법제처 26-0202]' 포함")
print("=" * 60)
query2 = "도시정비법 제78조제3항 타당성검증 1인 재개발사업 [법제처 26-0202]"
exclusions = extract_test_exclusions(query2)
print(f"감지된 제외 대상: {exclusions}")

# 같은 검색 실행
law_docs2, qa_docs2, case_docs2 = retriever.retrieve(
    query=query2,
    relation_types=[{"type": "EXCEPT", "weight": 1.0}],
    law_hints=["도시 및 주거환경정비법 제78조"],
)
principles_docs2 = retriever.retrieve_principles(query2, top_k=2)
linked_memos2 = retriever.fetch_linked_memos(law_docs2, qa_docs2, case_docs2)
semantic_memos2 = retriever.retrieve_memos(query2, top_k=3)
_seen2 = {m.get("memo_id", "") for m in linked_memos2 if m.get("memo_id")}
memo_docs2 = list(linked_memos2)
for m in semantic_memos2:
    mid = m.get("memo_id", "")
    if mid and mid not in _seen2:
        memo_docs2.append(m)
        _seen2.add(mid)

# 제외 로직 적용
before = (len(qa_docs2), len(case_docs2), len(principles_docs2), len(memo_docs2))
qa_docs2 = [d for d in qa_docs2 if d.metadata.get("doc_code", "") not in exclusions]
case_docs2 = [d for d in case_docs2 if d.metadata.get("case_id", "") not in exclusions]
principles_docs2 = [
    p for p in principles_docs2
    if not any(
        e in (str(p.get("source_cases", "")) + str(p.get("source_precedents", "")))
        for e in exclusions
    )
]
memo_docs2 = [
    m for m in memo_docs2
    if not any(e in _memo_linked_str(m) for e in exclusions)
]
after = (len(qa_docs2), len(case_docs2), len(principles_docs2), len(memo_docs2))
print(f"제외 전/후 (해석례·판례·원칙·메모): {before} → {after}")

# 검증
has_26_0202_after = any(d.metadata.get("doc_code") == "26-0202" for d in qa_docs2)
has_memo_026_after = any(m.get("memo_id") == "memo_026" for m in memo_docs2)
print(f"\n→ 제외 후 26-0202: {has_26_0202_after} (기대: False)")
print(f"→ 제외 후 memo_026: {has_memo_026_after} (기대: False)")

# ── 결과 요약 ──
print("\n" + "=" * 60)
print("[결과 요약]")
print("=" * 60)
ok = True
if not has_26_0202_qa:
    print("⚠ 시나리오 1: 일반 검색에서 26-0202가 안 잡힘 → 검증 의미 약함")
if has_26_0202_after:
    print("✗ FAIL: 테스트 모드에서 26-0202가 여전히 qa_docs에 있음")
    ok = False
else:
    print("✓ PASS: 26-0202 제외 정상 작동")

if has_memo_026 and has_memo_026_after:
    print("✗ FAIL: memo_026 (linked_to: 26-0202)이 제외 안 됨")
    ok = False
elif has_memo_026 and not has_memo_026_after:
    print("✓ PASS: memo_026 (linked_to: 26-0202)도 함께 제외됨")
else:
    print("○ memo_026이 원래 검색되지 않아 제외 검증 N/A")

sys.exit(0 if ok else 1)
