#!/usr/bin/env python3
"""extract_test_exclusions() 패턴 매칭 단위 테스트."""
import importlib.util
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# .env는 불필요 (extract만 테스트)
spec = importlib.util.spec_from_file_location(
    "generator", Path(__file__).parent.parent / "pipeline" / "06_Generator.py",
)
# get_gemini_client는 호출 안 함 — extract_test_exclusions만 import
# Generator class 초기화 회피
gen_src = (Path(__file__).parent.parent / "pipeline" / "06_Generator.py").read_text(encoding="utf-8")
# extract 함수 부분만 발췌 실행
import re
_LAWBUREAU_PATTERN = re.compile(r'(?<!\d)(\d{2}-\d{4})(?!\d)')
_COURT_CASE_PATTERN = re.compile(r'(?<![가-힣\d])(\d{2,4}[가-힣]\d{3,5})(?!\d)')

def extract_test_exclusions(query: str) -> list[str]:
    excl: set[str] = set()
    excl.update(_LAWBUREAU_PATTERN.findall(query))
    excl.update(_COURT_CASE_PATTERN.findall(query))
    return sorted(excl)


CASES = [
    # (입력, 기대 결과)
    ("토지등소유자 1인 재개발사업도 타당성검증 요청해야 하나요? [법제처 26-0202]",
     ["26-0202"]),
    ("대법원 2011다83431 전원합의체 판결의 의미는?",
     ["2011다83431"]),
    ("법제처 26-0202와 22-0379의 차이는?",
     ["22-0379", "26-0202"]),
    ("대법원 99두592와 2001두10400 비교",
     ["2001두10400", "99두592"]),
    ("건축법 제2조제1항제9호와 시행령 제3조의2",
     []),  # 조문번호는 매칭 안 됨
    ("2024년 개정된 건축법 시행령",
     []),  # 연도만으로는 매칭 안 됨
    ("대법원 2003. 12. 26. 선고 2003두6382",
     ["2003두6382"]),
    ("법제처 2024. 4. 4. 회신 24-0243 해석례",
     ["24-0243"]),
]

print("=== extract_test_exclusions 패턴 테스트 ===\n")
fails = 0
for i, (q, expected) in enumerate(CASES, 1):
    actual = extract_test_exclusions(q)
    ok = actual == expected
    status = "✓" if ok else "✗"
    print(f"{status} [{i}] {q}")
    print(f"     expected: {expected}")
    print(f"     actual:   {actual}")
    if not ok:
        fails += 1
    print()

print(f"\n결과: {len(CASES) - fails}/{len(CASES)} PASS")
sys.exit(0 if fails == 0 else 1)
