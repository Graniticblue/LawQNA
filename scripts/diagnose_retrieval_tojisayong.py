#!/usr/bin/env python3
"""토지사용권원증명서류 질의로 확장된 P-009 작동 확인.

기대: P-009가 검색되고, 본문-괄호 의미 확장 패턴 적용 가능.
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
    "「주택법 시행규칙」 제12조제4항제2호의 토지사용 승낙서가 "
    "괄호 부분에 따른 '토지사용권원증명서류'의 범위에 포함되는지? "
    "택지로 개발·분양하기로 예정된 토지에 대한 권원을 증명할 수 있는 서류"
)
SEARCH_Q = QUERY + " 본문 괄호 의미 확장 정의 보충 조항 별개 유형 포함 관계 입법 취지 요건 완화"

print("Retriever 초기화 중...")
retriever = ret.Retriever()
print("초기화 완료\n")

principles_docs = retriever.retrieve_principles(SEARCH_Q, top_k=5)

print(f"[principles_docs] {len(principles_docs)}건")
for p in principles_docs:
    print(f"  - {p.get('principle_id')}: {p.get('title', '')[:80]}")

p_ids = {p.get("principle_id") for p in principles_docs}
print(f"\nP-009 검색됨: {'✓' if 'P-009' in p_ids else '✗'}")
