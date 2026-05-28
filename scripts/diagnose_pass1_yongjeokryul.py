#!/usr/bin/env python3
"""
용적률 완화 질의에 대한 Pass 1 분류 진단.
법제처는 이 질의의 핵심 쟁점을 '도로가 그 밖의 공지에 포함되는가'(DEF_EXP)로 보는데,
현재 Pass 1이 이를 잡는지 확인.
"""
import importlib.util
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

_REPO = Path(__file__).parent.parent
from dotenv import load_dotenv
load_dotenv(_REPO / ".env")

spec = importlib.util.spec_from_file_location(
    "generator", _REPO / "pipeline" / "06_Generator.py",
)
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)
import os
gen.GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

QUERY = (
    "건축물이 있는 대지가 너비 25미터 미만인 도로에 20미터 이상 접하고 있고, "
    "그 도로가 해당 대지의 전면도로가 아닌 경우, "
    "해당 대지안의 건축물에 국토계획법 시행령 제85조제7항제1호 또는 제2호가 적용되어 "
    "용적률을 완화 받을 수 있는지?"
)

print("=" * 70)
print("질의:")
print(QUERY)
print("=" * 70)

client = gen.get_gemini_client()
pass1_text = gen.call_gemini(client, gen.PASS1_SYSTEM, QUERY, temperature=0.3)

print("\n[Pass 1 원문]")
print(pass1_text)
print("\n" + "=" * 70)

parsed = gen.parse_pass1(pass1_text)
print("\n[파싱 결과]")
print(f"question_type   : {parsed.get('question_type')}")
print(f"law_hints       : {parsed.get('law_hints')}")
print(f"definition_terms: {parsed.get('definition_terms')}")
print(f"relation_types  :")
for r in parsed.get('relation_types', []):
    print(f"  - {r.get('type')} (weight={r.get('weight')}) :: {r.get('reason', '')}")

print("\n" + "=" * 70)
print("[가설 검증]")
print("법제처 답변의 핵심 쟁점: '도로가 그 밖에 건축이 금지된 공지에 포함되는가?'")
print("→ 이는 본질적으로 DEF_EXP(정의·범위 외연 쟁점).")
print()
rels = parsed.get('relation_types', [])
has_def_exp = any(r.get('type') == 'DEF_EXP' for r in rels)
top = max(rels, key=lambda r: r.get('weight', 0)) if rels else {}
print(f"DEF_EXP 포함 여부: {has_def_exp}")
print(f"최상위 relation:   {top.get('type')} (weight={top.get('weight')})")
if top.get('type') != 'DEF_EXP':
    print("⚠ DEF_EXP가 최상위로 잡히지 않음 → 핵심 쟁점 인식 실패 가설 확인")
