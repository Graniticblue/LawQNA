#!/usr/bin/env python3
"""
Pass 1 회귀 테스트셋 — Generator의 단일실패점(SPOF) 모니터링.

각 테스트 케이스:
  - query: 사용자 질문
  - expect_question_type: any-of (set) — 본질적으로 fuzzy하므로 허용 집합으로 평가
  - expect_relation_top: 최상위(weight 최대) relation_type이 이 집합 중 하나여야 함
  - expect_law_any_of: law_hints에 이 법령들 중 최소 하나가 포함돼야 함 (부분일치 허용)
  - expect_def_any_of: (선택) definition_terms에 이 용어들 중 최소 하나가 포함돼야 함

실행:
  python tests/pass1_regression.py                   # 전체 실행
  python tests/pass1_regression.py --verbose         # 실패 케이스 Pass 1 원문 표시
  python tests/pass1_regression.py --case 5          # 5번 케이스만 실행

결과:
  - 콘솔: 케이스별 PASS/FAIL + 최종 통계
  - tests/pass1_results_{YYYYMMDD}.json: 상세 로그 (추세 추적용)
"""
import argparse
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# ── 루트 .env 명시 로드 (Generator는 pipeline/.env를 찾으므로 보충) ──
_REPO = Path(__file__).parent.parent
from dotenv import load_dotenv
load_dotenv(_REPO / ".env")

# ── Generator 동적 import ────────────────────────────────────
spec = importlib.util.spec_from_file_location(
    "generator", _REPO / "pipeline" / "06_Generator.py"
)
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)
# Generator 모듈의 모듈변수도 환경변수에서 다시 읽기
import os
gen.GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
gen.ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


# ── 테스트 케이스 ────────────────────────────────────────────
TESTS = [
    {
        "id": 1,
        "query": "건축법상 '대수선'이란 무엇인가요?",
        "expect_question_type": {"단일조문형", "복수조문탐색형"},
        "expect_relation_top": {"DEF_EXP"},
        "expect_law_any_of": ["건축법 제2조", "건축법 시행령 제3조의2"],
        "expect_def_any_of": ["대수선"],
    },
    {
        "id": 2,
        "query": "다중이용업소의 용도변경 시 건축허가가 필요한가요?",
        "expect_question_type": {"복수조문탐색형", "조건분기형"},
        "expect_relation_top": {"SCOPE_CL", "REQ_INT"},
        "expect_law_any_of": ["건축법 제19조", "건축법 시행령"],
    },
    {
        "id": 3,
        "query": "공동주택에는 건축법과 주택법 중 어느 법이 우선 적용되나요?",
        "expect_question_type": {"복수조문탐색형", "단일조문형"},
        "expect_relation_top": {"INTER_ART", "SCOPE_CL"},
        "expect_law_any_of": ["주택법", "건축법"],
    },
    {
        "id": 4,
        "query": "연면적 500제곱미터 미만의 공장도 건축허가 대상인가요?",
        "expect_question_type": {"조건분기형", "복수조문탐색형"},
        "expect_relation_top": {"REQ_INT", "SCOPE_CL"},
        "expect_law_any_of": ["건축법 제11조", "건축법 제14조"],
    },
    {
        "id": 5,
        "query": "비도시지역 면지역에서도 접도의무가 적용되나요?",
        "expect_question_type": {"단일조문형", "복수조문탐색형", "조건분기형"},
        "expect_relation_top": {"EXCEPT", "SCOPE_CL"},
        "expect_law_any_of": ["건축법 제3조", "건축법 제44조"],
    },
    {
        "id": 6,
        "query": "건축법 위반 시 이행강제금은 어떻게 산정되나요?",
        "expect_question_type": {"단일조문형", "복수조문탐색형", "조건분기형"},
        "expect_relation_top": {"SANC_SC"},
        "expect_law_any_of": ["건축법 제80조"],
    },
    {
        "id": 7,
        "query": "토지등소유자가 1인인 경우에도 재개발사업의 관리처분계획 타당성검증을 요청해야 하나요?",
        "expect_question_type": {"단일조문형", "조건분기형", "복수조문탐색형"},
        "expect_relation_top": {"EXCEPT", "SCOPE_CL"},
        "expect_law_any_of": ["도시 및 주거환경정비법", "도시정비법"],
    },
    {
        "id": 8,
        "query": "건축법 시행령 별표1의 '공동주택'에 기숙사도 포함되나요?",
        "expect_question_type": {"단일조문형", "복수조문탐색형"},
        "expect_relation_top": {"DEF_EXP"},
        "expect_law_any_of": ["건축법 시행령 별표1"],
        "expect_def_any_of": ["공동주택"],
    },
    {
        "id": 9,
        "query": "장애인 편의시설 설치 의무 대상 건축물은 어떻게 되나요?",
        "expect_question_type": {"복수조문탐색형", "조건분기형"},
        "expect_relation_top": {"REQ_INT", "SCOPE_CL", "DEF_EXP"},
        "expect_law_any_of": ["장애인", "편의증진"],
    },
    {
        "id": 10,
        "query": "건축물 부설주차장 설치 기준에서 용도와 규모에 따른 설치 대수는?",
        "expect_question_type": {"조건분기형", "복수조문탐색형"},
        "expect_relation_top": {"REQ_INT"},
        "expect_law_any_of": ["주차장법"],
    },
    {
        # 개방형 열거('그 밖에 ~')의 외연 쟁점 — DEF_EXP가 주(主) 쟁점으로 잡혀야 함.
        # 법제처는 이 패턴 질의를 일관되게 DEF_EXP 논리로 처리한다.
        # 보강 전: SCOPE_CL(1.0)로 오분류 → 진짜 쟁점 회피
        # 보강 후: DEF_EXP(1.0) + '그 밖에 건축이 금지된 공지' definition_terms 포착
        "id": 11,
        "query": (
            "건축물이 있는 대지가 너비 25미터 미만인 도로에 20미터 이상 접하고 있고, "
            "그 도로가 해당 대지의 전면도로가 아닌 경우, "
            "해당 대지안의 건축물에 국토계획법 시행령 제85조제7항제1호 또는 제2호가 "
            "적용되어 용적률을 완화 받을 수 있는지?"
        ),
        "expect_question_type": {"단일조문형", "복수조문탐색형", "조건분기형"},
        "expect_relation_top": {"DEF_EXP"},
        "expect_law_any_of": [
            "국토의 계획 및 이용에 관한 법률 시행령 제85조",
            "국토의 계획 및 이용에 관한 법률 제78조",
        ],
        "expect_def_any_of": ["그 밖에 건축이 금지된 공지", "건축이 금지된 공지"],
    },
]


# ── 검증 로직 ────────────────────────────────────────────────

def _law_contains(actual_hint: str, expected_fragment: str) -> bool:
    """expected_fragment(예: '건축법 제2조')가 actual_hint에 포함되면 True."""
    a = actual_hint.replace(" ", "")
    e = expected_fragment.replace(" ", "")
    return e in a


def evaluate(test: dict, parsed: dict) -> dict:
    """단일 테스트 케이스 평가. 반환: {pass, failures}"""
    failures = []

    # question_type: any-of (set)
    qt_actual = parsed.get("question_type", "")
    qt_allowed = test["expect_question_type"]
    if qt_actual not in qt_allowed:
        failures.append(
            f"question_type: expected one_of={sorted(qt_allowed)}, actual={qt_actual}"
        )

    # relation_top: weight 최대 항목
    rels = parsed.get("relation_types", [])
    if not rels:
        failures.append("relation_types: 비어있음")
    else:
        top = max(rels, key=lambda r: r.get("weight", 0))
        top_type = top.get("type", "")
        if top_type not in test["expect_relation_top"]:
            failures.append(
                f"relation_top: expected one_of={sorted(test['expect_relation_top'])}, "
                f"actual_top={top_type}"
            )

    # law_hints: any-of 매칭
    hints = parsed.get("law_hints", [])
    expected_laws = test["expect_law_any_of"]
    if not any(
        _law_contains(h, exp) for h in hints for exp in expected_laws
    ):
        failures.append(
            f"law_hints: expected any_of={expected_laws}, actual={hints}"
        )

    # definition_terms: optional any-of
    if "expect_def_any_of" in test:
        terms = parsed.get("definition_terms", [])
        if not any(d in t or t in d for t in terms for d in test["expect_def_any_of"]):
            failures.append(
                f"definition_terms: expected any_of={test['expect_def_any_of']}, "
                f"actual={terms}"
            )

    return {"pass": len(failures) == 0, "failures": failures}


# ── 메인 ──────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true", help="실패 케이스 Pass 1 원문 표시")
    ap.add_argument("--case", type=int, help="단일 케이스 ID만 실행")
    args = ap.parse_args()

    client = gen.get_gemini_client()
    tests = [t for t in TESTS if (args.case is None or t["id"] == args.case)]
    if not tests:
        print(f"케이스 ID {args.case} 없음")
        sys.exit(1)

    print(f"=== Pass 1 회귀 테스트 ({len(tests)}건) ===\n")

    results = []
    for t in tests:
        print(f"[{t['id']:02d}] {t['query']}")
        pass1_text = gen.call_gemini(client, gen.PASS1_SYSTEM, t["query"], temperature=0.3)
        parsed = gen.parse_pass1(pass1_text)
        eval_result = evaluate(t, parsed)

        status = "✓ PASS" if eval_result["pass"] else "✗ FAIL"
        print(f"     {status}")
        if not eval_result["pass"]:
            for f in eval_result["failures"]:
                print(f"       - {f}")
            if args.verbose:
                print(f"\n     --- Pass 1 원문 ---")
                for ln in pass1_text.splitlines():
                    print(f"     {ln}")
                print()

        results.append({
            "id":           t["id"],
            "query":        t["query"],
            "pass":         eval_result["pass"],
            "failures":     eval_result["failures"],
            "parsed":       parsed,
            "pass1_text":   pass1_text if not eval_result["pass"] else None,
        })

    # 요약
    n_pass = sum(1 for r in results if r["pass"])
    n_total = len(results)
    print(f"\n{'='*50}")
    print(f"결과: {n_pass}/{n_total} PASS ({n_pass*100/n_total:.0f}%)")
    if n_pass < n_total:
        print(f"실패 케이스: {[r['id'] for r in results if not r['pass']]}")

    # 결과 저장
    out_path = Path(__file__).parent / f"pass1_results_{date.today().isoformat()}.json"
    out_path.write_text(
        json.dumps({"summary": {"pass": n_pass, "total": n_total},
                    "results": results},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n상세 로그: {out_path}")

    sys.exit(0 if n_pass == n_total else 1)


if __name__ == "__main__":
    main()
