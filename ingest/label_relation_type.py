#!/usr/bin/env python3
"""
label_relation_type.py
======================
clean_single.jsonl 각 레코드에 판례-법령 관계 유형 라벨을 추가한다.

[질문 원인 분석] 카테고리 → relation_type 매핑

직접 매핑 (1:1):
  행정 재량권의 확인       → PROC_DISC
  시점 및 적용 범위의 혼선  → SCOPE_CL
  법적 공백 및 정의 미비   → DEF_EXP
  법령 간의 상충 및 경합   → INTER_ART

세분류 필요:
  용어 및 기준의 추상성    → DEF_EXP | REQ_INT
    DEF_EXP: 법적 개념·용어가 특정 대상에 해당하는지 (범주 귀속)
    REQ_INT: 수치·조건 기준의 충족 여부 (요건 해석)

보류 유형 (미출현):
  EXCEPT   (예외인정형)
  SANC_SC  (벌칙·제재 범위형)

출력:
  data/labeled.jsonl  ← 원본 레코드 + 라벨 필드
    relation_type  : 유형 코드 (DEF_EXP 등)
    relation_name  : 유형 한글명 (정의확장형 등)
    label_summary  : [검토 결과] 첫 문장 — 이 질의에서 어떤 결론이 내려졌는지
    logic_steps    : [법리적 판단 로직] 스텝 배열
                     [{seq, role, title}]
                     role: ANCHOR | ANALYSIS | PREREQUISITE | RESOLUTION
"""

import json
import re
from pathlib import Path

# ── 경로 ──────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
INPUT_PATH = BASE_DIR / "data" / "clean_single.jsonl"
OUTPUT_PATH = BASE_DIR / "data" / "labeled.jsonl"

# ── 섹션 파싱 ─────────────────────────────────────────────────────
SECTION_PAT = re.compile(r'###\s*\[([^\]]+)\](.*?)(?=###\s*\[|\Z)', re.DOTALL)

def parse_sections(text: str) -> dict:
    return {m.group(1).strip(): m.group(2).strip() for m in SECTION_PAT.finditer(text)}


# ── [질문 원인 분석] 카테고리 추출 ───────────────────────────────
CAT_PAT = re.compile(r'\d+\.\s+([^\(\n]+?)(?:\s*[\(\（])')

def extract_origin_category(origin_text: str) -> str:
    m = CAT_PAT.search(origin_text)
    return m.group(1).strip() if m else ''


# ── [검토 결과] 첫 문장 추출 → label_summary ─────────────────────
BOLD_PAT = re.compile(r'\*{1,2}([^\*]+)\*{1,2}')  # **bold** 제거

def extract_label_summary(result_text: str) -> str:
    """[검토 결과] 첫 의미 있는 문장. 마크다운 제거 후 반환."""
    text = BOLD_PAT.sub(r'\1', result_text).strip()
    # 첫 문장: 마침표+공백 또는 개행 기준
    sentences = re.split(r'(?<=[\.다음])\s*\n|(?<=[\.다])\s{2,}', text)
    first = sentences[0].strip() if sentences else text
    # 너무 길면 자름 (200자)
    return first[:200] if len(first) > 200 else first


# ── [법리적 판단 로직] 스텝 추출 및 역할 태깅 ───────────────────
STEP_PAT       = re.compile(r'^\d+\.\s+\*{0,2}([^\*\n]+)', re.MULTILINE)
PREREQ_SIGNALS = re.compile(r'선행|선결|먼저\s*(?:확인|해결|검토)|우선적으로\s*(?:확인|해결)')

def tag_step_role(title: str, seq: int, total: int) -> str:
    """
    스텝 역할 결정:
      - 선결과제 키워드 있으면 PREREQUISITE (위치 무관)
      - 1번 스텝 → ANCHOR
      - 마지막 스텝 → RESOLUTION
      - 나머지 → ANALYSIS
    """
    if PREREQ_SIGNALS.search(title):
        return 'PREREQUISITE'
    if seq == 1:
        return 'ANCHOR'
    if seq == total:
        return 'RESOLUTION'
    return 'ANALYSIS'

def extract_logic_steps(logic_text: str) -> list:
    """[법리적 판단 로직] → [{seq, role, title}, ...]"""
    bold_clean = re.compile(r'\*{1,2}([^\*]+)\*{1,2}')
    titles = [bold_clean.sub(r'\1', t).strip().rstrip(':').strip()
              for t in STEP_PAT.findall(logic_text)]
    if not titles:
        return []
    total = len(titles)
    return [
        {'seq': i + 1, 'role': tag_step_role(t, i + 1, total), 'title': t}
        for i, t in enumerate(titles)
    ]


# ── Semantic Ambiguity 세분류: DEF_EXP vs REQ_INT ────────────────
# REQ_INT 강신호: 수치 단위, 기준/요건 관련 핵심어
REQ_INT_STRONG = re.compile(
    r'㎡|제곱미터|m\s*이상|m\s*미만|층\s*이상|층수|이격|산입|'
    r'연면적|건축면적|바닥면적|건폐율|용적률|'
    r'요건|충족|기준\s*(?:적용|확인|검토)|합병\s*(?:의무|조건)|'
    r'조건부\s*허가|허가\s*요건'
)

# DEF_EXP 강신호: 법적 범주 귀속 ("X에 해당", "X로 보")
DEF_EXP_STRONG = re.compile(
    r'건축물에\s*해당|건축물로\s*보|공작물로\s*보|'
    r'대지(?:로\s*인정|에\s*해당|의\s*정의)|'
    r'정의\s*(?:확인|충족|적용)|개념\s*(?:확인|해석)|'
    r'에\s*해당하는\s*것으로|로\s*볼\s*수\s*있'
)

def classify_semantic_ambiguity(sections: dict) -> str:
    result = sections.get('검토 결과', '')
    logic  = sections.get('법리적 판단 로직', '')
    text   = result + '\n' + logic

    req_score = len(REQ_INT_STRONG.findall(text))
    def_score = len(DEF_EXP_STRONG.findall(text))

    # 수치 기준이 명시적으로 등장하면 REQ_INT 우선
    if req_score > 0 and req_score >= def_score:
        return 'REQ_INT'
    return 'DEF_EXP'


# ── 유형 코드 → 한글 이름 ────────────────────────────────────────
RELATION_NAMES = {
    'DEF_EXP':   '정의확장형',
    'REQ_INT':   '요건해석형',
    'PROC_DISC': '절차·재량확인형',
    'SCOPE_CL':  '적용범위확정형',
    'INTER_ART': '조문간관계해석형',
    'UNKNOWN':   '미분류',
}

# ── 카테고리 → relation_type 매핑 ────────────────────────────────
DIRECT_MAP = {
    '행정 재량권의 확인':      'PROC_DISC',
    '시점 및 적용 범위의 혼선': 'SCOPE_CL',
    '법적 공백 및 정의 미비':  'DEF_EXP',
    '법령 간의 상충 및 경합':  'INTER_ART',
}

def assign_relation_type(sections: dict) -> tuple[str, str, str]:
    """
    Returns (relation_type, relation_name, label_summary)
    """
    origin  = sections.get('질문 원인 분석', '')
    cat     = extract_origin_category(origin)
    summary = extract_label_summary(sections.get('검토 결과', ''))

    # 직접 매핑 시도
    for key, rtype in DIRECT_MAP.items():
        if key in cat:
            return rtype, RELATION_NAMES[rtype], summary

    # Semantic Ambiguity 세분류
    if '용어 및 기준의 추상성' in cat:
        rtype = classify_semantic_ambiguity(sections)
        return rtype, RELATION_NAMES[rtype], summary

    # 미인식 카테고리
    return 'UNKNOWN', RELATION_NAMES['UNKNOWN'], summary


# ── 메인 ──────────────────────────────────────────────────────────
def main():
    records = [json.loads(l) for l in open(INPUT_PATH, encoding='utf-8') if l.strip()]

    stats = {}
    out_records = []

    for rec in records:
        answer = ''
        for turn in rec['contents']:
            if turn['role'] == 'model':
                answer = turn['parts'][0]['text']

        sections = parse_sections(answer)
        rtype, rname, summary = assign_relation_type(sections)
        steps = extract_logic_steps(sections.get('법리적 판단 로직', ''))

        rec['relation_type']  = rtype
        rec['relation_name']  = rname
        rec['label_summary']  = summary
        rec['logic_steps']    = steps
        out_records.append(rec)
        stats[rtype] = stats.get(rtype, 0) + 1

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        for rec in out_records:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')

    print(f"라벨링 완료: {len(out_records):,}건 → {OUTPUT_PATH.name}")
    print()
    print("=== relation_type 분포 ===")
    total = len(out_records)
    for rtype, cnt in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {rtype:<12} {cnt:4d}건  ({cnt/total*100:.1f}%)")


if __name__ == '__main__':
    main()
