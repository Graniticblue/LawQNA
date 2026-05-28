#!/usr/bin/env python3
"""
split_multi_question.py
=======================
seoul_reasoning_v6_with_original.jsonl에서
한 질의 안에 여러 쟁점이 열거된 '다중질문' 레코드를 분리한다.

출력:
  data/clean_single.jsonl      ← 단일 질문 (정상 처리 대상)
  data/aside_multi.jsonl       ← 다중 질문 (보류)

다중질문 판정 기준:
  A) 열거 패턴 등장
     - 나./다./라. ... (가. 이후 나. 이상이 있어야 다중)
     - 2. /3.  (문두에 등장하는 번호 목록)
     - 2) /3)
     - ②③④⑤ (원문자)
  B) 단, OR형 단일질문은 제외
     - "? 아니면" / "? 또는" 패턴으로만 물음표가 여럿인 경우
       → 하나의 쟁점에 대한 양자택일이므로 단일로 분류
"""

import json
import re
from pathlib import Path

# ── 경로 설정 ──────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
INPUT_PATH = BASE_DIR / "seoul_reasoning_v6_with_original.jsonl"
DATA_DIR   = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
CLEAN_PATH = DATA_DIR / "clean_single.jsonl"
ASIDE_PATH = DATA_DIR / "aside_multi.jsonl"

# ── 패턴 정의 ──────────────────────────────────────────────────────

# 열거형 다중 패턴
# 가. 이후 나./다. 이상이 줄 첫머리에 등장
MULTI_GA_NA = re.compile(
    r'가[\.\)].+?나[\.\)]',          # 가. ... 나.
    re.DOTALL
)
# 줄 첫머리(또는 공백 후)에 2. 또는 2) 등장
MULTI_2DOT = re.compile(
    r'(?:^|[\n\s])2[\.\)]\s',
    re.MULTILINE
)
# 줄 첫머리 또는 공백 후 3. 이상 (2.가 없더라도 3.이 있으면 다중)
MULTI_3DOT = re.compile(
    r'(?:^|[\n\s])3[\.\)]\s',
    re.MULTILINE
)
# 원문자 ②이상
MULTI_CIRCLE = re.compile(r'[②③④⑤]')

# OR형 단일질문 (물음표 바로 뒤 아니면/또는)
OR_SINGLE = re.compile(r'\?\s{0,4}(?:아니면|또는|혹은)')


def is_multi_question(question: str) -> bool:
    """
    True  → 다중 쟁점 열거형 (aside로 분리)
    False → 단일 질문 (clean으로 유지)
    """
    has_enum = (
        MULTI_GA_NA.search(question)
        or MULTI_2DOT.search(question)
        or MULTI_3DOT.search(question)
        or MULTI_CIRCLE.search(question)
    )

    if not has_enum:
        return False

    # 열거가 있더라도, 패턴 전체가 OR형이면 단일로 취급
    # OR 패턴 수가 물음표 수와 같다면 → 모두 OR형 단일
    q_count  = question.count('?')
    or_count = len(OR_SINGLE.findall(question))

    if q_count > 0 and or_count >= q_count:
        return False  # 모든 ? 가 OR형

    return True


def extract_question(record: dict) -> str:
    for turn in record.get('contents', []):
        if turn.get('role') == 'user':
            parts = turn.get('parts', [{}])
            return parts[0].get('text', '') if parts else ''
    return ''


def main():
    with open(INPUT_PATH, encoding='utf-8') as f:
        records = [json.loads(l) for l in f if l.strip()]

    clean  = []
    aside  = []

    for i, rec in enumerate(records):
        q = extract_question(rec)
        if is_multi_question(q):
            aside.append((i, rec))
        else:
            clean.append((i, rec))

    # 저장 (원본 레코드에 index 필드 추가)
    with open(CLEAN_PATH, 'w', encoding='utf-8') as f:
        for idx, rec in clean:
            rec['_orig_idx'] = idx
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')

    with open(ASIDE_PATH, 'w', encoding='utf-8') as f:
        for idx, rec in aside:
            rec['_orig_idx'] = idx
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')

    print(f"전체   : {len(records):,}건")
    print(f"단일   : {len(clean):,}건  → {CLEAN_PATH.name}")
    print(f"다중   : {len(aside):,}건  → {ASIDE_PATH.name}")

    # 분리된 다중질문 샘플 출력
    print("\n[다중질문 샘플 5건]")
    for idx, rec in aside[:5]:
        q = extract_question(rec)
        print(f"  [{idx:04d}] {q[:120].replace(chr(10), ' ')}")


if __name__ == '__main__':
    main()
