"""
00_PDF_QA_Extractor.py

서울특별시 건축법·건축조례 질의회신집 PDF에서
Q&A 쌍을 추출하고, 각 질의의 참조코드(기관, 문서번호, 날짜)를
별도 필드로 파싱하여 JSONL로 저장한다.

출력 필드:
  question    : 질문 원문
  answer      : 회답 원문
  doc_ref     : 원본 참조 문자열  예) "[서울시건지 58550-3142 / '02.08.01]"
  doc_agency  : 발신 기관명       예) "서울시건지"
  doc_code    : 문서 번호         예) "58550-3142"
  doc_date    : 날짜 (YYYY-MM-DD) 예) "2002-08-01"
"""

import re
import json
from pathlib import Path

import pdfplumber

# ──────────────────────────────────────────────
# 경로 설정
# ──────────────────────────────────────────────

BASE_DIR   = Path(__file__).parent
PDF_PATH   = BASE_DIR / "data" / "raw_laws" / "서울특별시 건축법건축조례 질의회신집.pdf"
OUTPUT_DIR = BASE_DIR / "data"
OUTPUT_DIR.mkdir(exist_ok=True)
OUTPUT_PATH = OUTPUT_DIR / "seoul_qa_with_ref.jsonl"


# ──────────────────────────────────────────────
# 정규식
# ──────────────────────────────────────────────

# 참조 패턴: [기관명(코드) / '연.월.일] — U+2018('), U+0027('), U+0060(`) 모두 허용
REF_RE = re.compile(
    r'\[([^\]/\n]{1,40}?)\s*/\s*[\u2018\u0027\u0060\u2019]'
    r'(\d{2}\.\d{2}\.\d{2})\.?\]'
)

# 페이지 헤더/푸터 제거용 패턴
PAGE_HEADER_RE = re.compile(
    r'^\d{4}\s*:\s*질의회신집[^\n]*\n|'
    r'^질의회신집\s+제\d+편[^\n]*\n|'
    r'^제\d+편\.[^\n]*\n|'
    r'^\d{4}\s*:\s*[^\n]*\n',
    re.MULTILINE
)

# 인쇄 정보 행 제거 (예: "2판-38판.indd 14  2015. 2. 10. 오후 3:20")
PRINT_INFO_RE = re.compile(r'\d판-\d+판\.indd[^\n]*\n', re.MULTILINE)

# 질문 / 답변 구분자
# PDF 원본: "질 의" (U+C9C8 + space + U+C758), "회 신" (U+D68C + space + U+C2E0)
Q_MARKER_RE = re.compile(r'\uC9C8\s+\uC758\s*\n')   # 질 의
A_MARKER_RE = re.compile(r'\uD68C\s+\uC2E0\s*\n')   # 회 신


# ──────────────────────────────────────────────
# 헬퍼: 2자리 연도 → 4자리
# ──────────────────────────────────────────────

def expand_year(yy: str) -> int:
    y = int(yy)
    return 2000 + y if y <= 30 else 1900 + y


# ──────────────────────────────────────────────
# 헬퍼: 참조 본문에서 기관명 / 문서번호 분리
# ──────────────────────────────────────────────

def parse_agency_code(ref_body: str) -> tuple[str, str]:
    """
    "서울시건지 58550-3142"  → ("서울시건지", "58550-3142")
    "건교부 13-0313"         → ("건교부", "13-0313")
    "건축기획팀-11698"        → ("건축기획팀", "11698")
    "건교부"                  → ("건교부", "")
    """
    ref_body = ref_body.strip()
    # 첫 번째 숫자 위치 탐색
    m = re.search(r'\d', ref_body)
    if not m:
        return ref_body, ""

    pre = ref_body[:m.start()].rstrip('-').rstrip().strip()
    code = ref_body[m.start():].strip()
    return pre, code


# ──────────────────────────────────────────────
# PDF 전체 텍스트 추출
# ──────────────────────────────────────────────

def extract_full_text(pdf_path: Path) -> str:
    pages = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        print(f"[PDF] 총 {len(pdf.pages)}페이지")
        for page in pdf.pages:
            t = page.extract_text() or ""
            pages.append(t)
    full = "\n".join(pages)

    # 노이즈 제거
    full = PAGE_HEADER_RE.sub("", full)
    full = PRINT_INFO_RE.sub("", full)
    return full


# ──────────────────────────────────────────────
# 텍스트 → Q&A 블록 파싱
# ──────────────────────────────────────────────

def parse_qa_blocks(text: str) -> list[dict]:
    # 참조 패턴 전체 검색
    ref_matches = list(REF_RE.finditer(text))
    print(f"[PARSE] 참조 패턴 {len(ref_matches)}개 발견")

    records = []
    for i, ref_m in enumerate(ref_matches):
        ref_body = ref_m.group(1).strip()
        date_raw = ref_m.group(2)          # "02.08.01"
        doc_ref  = ref_m.group(0)          # 원본 전체 문자열

        # 이 참조 이후 ~ 다음 참조 이전 구간
        block_start = ref_m.end()
        block_end   = ref_matches[i + 1].start() if i + 1 < len(ref_matches) else len(text)
        block = text[block_start:block_end]

        # 질 문 / 회 답 위치 탐색
        q_m = Q_MARKER_RE.search(block)
        a_m = A_MARKER_RE.search(block)
        if not q_m or not a_m:
            continue  # 구분자 없으면 스킵

        question = block[q_m.end():a_m.start()].strip()
        # 답변: 회 답 이후 ~ 블록 끝 (다음 항목 제목 포함될 수 있으나 정리)
        answer_raw = block[a_m.end():].strip()

        # 답변 끝에 붙은 다음 항목 제목 제거 (빈 줄 이전까지 or 전체)
        # 다음 참조 직전에 제목 1~2줄이 오는 경우가 많으므로, 우선 전체 보존
        answer = answer_raw

        if not question or not answer:
            continue

        # 날짜 변환
        parts = date_raw.split('.')
        yy, mm, dd = parts[0], parts[1], parts[2]
        doc_date = f"{expand_year(yy):04d}-{mm}-{dd}"

        # 기관명 / 코드 분리
        doc_agency, doc_code = parse_agency_code(ref_body)

        records.append({
            "question":   question,
            "answer":     answer,
            "doc_ref":    doc_ref,
            "doc_agency": doc_agency,
            "doc_code":   doc_code,
            "doc_date":   doc_date,
        })

    return records


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Seoul QA PDF Extractor")
    print("=" * 60)

    if not PDF_PATH.exists():
        print(f"[ERROR] PDF not found: {PDF_PATH}")
        return

    print(f"\n[1/3] PDF 텍스트 추출 중: {PDF_PATH.name}")
    text = extract_full_text(PDF_PATH)
    print(f"  -> 총 {len(text):,}자 추출")

    print("\n[2/3] Q&A 블록 파싱 중...")
    records = parse_qa_blocks(text)
    print(f"  -> {len(records):,}개 Q&A 추출")

    print(f"\n[3/3] JSONL 저장: {OUTPUT_PATH}")
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(f"  -> 완료!")

    # 샘플 출력
    print("\n--- 샘플 (첫 3건) ---")
    for r in records[:3]:
        print(f"  doc_ref    : {r['doc_ref']}")
        print(f"  doc_agency : {r['doc_agency']}")
        print(f"  doc_code   : {r['doc_code']}")
        print(f"  doc_date   : {r['doc_date']}")
        print(f"  question   : {r['question'][:60]}...")
        print(f"  answer     : {r['answer'][:60]}...")
        print()


if __name__ == "__main__":
    main()
