"""
merge_unmatched.py

사용자가 수동으로 라벨을 추가한 labeled_unmatched.jsonl 을 파싱하여
labeled_with_doc.jsonl 의 해당 항목에 4개 doc 필드를 채워 넣는다.

unmatched 행 형식:
  [기관명 코드 / '날짜] {JSON}
  [기관명 / '날짜]     {JSON}
  [기관명-코드]        {JSON}   ← 날짜 없음
  날짜 형식 변형:
    '12.05.26.  /  ''97.12.31  /  14. 9. 23.  /  07.2.27.
"""

import json
import re
from pathlib import Path

UNMATCHED_PATH     = Path("data/labeled_unmatched.jsonl")
LABELED_WITH_DOC   = Path("data/labeled_with_doc.jsonl")


# ─── 헬퍼 ──────────────────────────────────────────────────────────

def expand_year(yy: str) -> int:
    y = int(yy)
    return 2000 + y if y <= 30 else 1900 + y


def parse_date(raw: str) -> str:
    """
    여러 형식의 날짜 문자열 → "YYYY-MM-DD"
    raw 예: "'12.05.26."  "''97.12.31"  "14. 9. 23."  "07.2.27."
    """
    # 앞의 따옴표 제거
    raw = raw.lstrip("\u2018\u2019\u0027\u0060'")
    # 공백 제거
    raw = re.sub(r'\s+', '', raw)
    # 마지막 점 제거
    raw = raw.rstrip('.')

    parts = raw.split('.')
    if len(parts) < 3:
        return ""

    yy, mm, dd = parts[0], parts[1].zfill(2), parts[2].zfill(2)
    try:
        year = expand_year(yy)
    except ValueError:
        return ""
    return f"{year:04d}-{mm}-{dd}"


def parse_ref_prefix(bracket_content: str) -> dict:
    """
    대괄호 안의 내용 → {doc_ref, doc_agency, doc_code, doc_date}
    예:
      "국토교통부 / '12.05.26."
      "서울시건지 58501-01363 / ''97.12.31"
      "건축기획과-692"
      "법제처 12-0202 / '12.04.27."
      "건축기획과-23281 / 14. 9. 23."
    """
    text = bracket_content.strip()

    # 날짜 구분자 "/" 기준 분리
    if '/' in text:
        body, date_raw = text.split('/', 1)
    else:
        body     = text
        date_raw = ""

    body     = body.strip()
    date_raw = date_raw.strip()

    # 기관명 / 코드 분리 (첫 번째 숫자 위치 기준)
    m = re.search(r'\d', body)
    if m:
        agency = body[:m.start()].rstrip('-').strip()
        code   = body[m.start():].strip()
    else:
        agency = body
        code   = ""

    doc_date = parse_date(date_raw) if date_raw else ""

    return {
        "doc_ref":    f"[{text}]",
        "doc_agency": agency,
        "doc_code":   code,
        "doc_date":   doc_date,
    }


# ─── 파싱: annotated unmatched ────────────────────────────────────

LINE_RE = re.compile(r'^\s*\[([^\]]+)\]\s*(\{.*)\s*$', re.DOTALL)


def load_annotated_unmatched(path: Path) -> dict:
    """orig_idx → doc_fields 딕셔너리 반환"""
    mapping = {}
    skipped = []

    with open(path, encoding='utf-8') as f:
        for lineno, raw in enumerate(f, 1):
            raw = raw.rstrip('\n')
            if not raw.strip():
                continue

            m = LINE_RE.match(raw)
            if not m:
                # [..] 프리픽스 없는 행 → 파싱 실패
                skipped.append(lineno)
                continue

            bracket_content = m.group(1)
            json_text       = m.group(2)

            try:
                rec = json.loads(json_text)
            except json.JSONDecodeError as e:
                skipped.append(lineno)
                continue

            orig_idx = rec.get("_orig_idx")
            if orig_idx is None:
                skipped.append(lineno)
                continue

            doc_fields = parse_ref_prefix(bracket_content)
            mapping[orig_idx] = doc_fields

    if skipped:
        print(f"  [WARN] 파싱 실패 행: {skipped}")

    return mapping


# ─── 병합 ────────────────────────────────────────────────────────

def merge(labeled_path: Path, doc_map: dict) -> tuple[list, int]:
    """labeled_with_doc.jsonl + doc_map → 업데이트된 레코드 리스트"""
    updated = 0
    records = []

    with open(labeled_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            orig_idx = rec.get("_orig_idx")

            if orig_idx in doc_map and not rec.get("doc_date"):
                rec.update(doc_map[orig_idx])
                updated += 1

            records.append(rec)

    return records, updated


# ─── 메인 ────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("unmatched 병합 → labeled_with_doc.jsonl")
    print("=" * 60)

    print(f"\n[1/3] annotated unmatched 파싱: {UNMATCHED_PATH}")
    doc_map = load_annotated_unmatched(UNMATCHED_PATH)
    print(f"  → {len(doc_map)}개 파싱 완료")

    # 파싱 결과 미리보기
    for i, (idx, doc) in enumerate(list(doc_map.items())[:3]):
        print(f"  orig_idx={idx} | {doc['doc_ref']} | date={doc['doc_date']}")

    print(f"\n[2/3] labeled_with_doc.jsonl 업데이트 중...")
    records, updated = merge(LABELED_WITH_DOC, doc_map)
    print(f"  → {updated}개 항목 업데이트")

    print(f"\n[3/3] 저장: {LABELED_WITH_DOC}")
    with open(LABELED_WITH_DOC, 'w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    # 최종 통계
    total    = len(records)
    has_date = sum(1 for r in records if r.get('doc_date'))
    has_code = sum(1 for r in records if r.get('doc_code'))
    no_date  = sum(1 for r in records if not r.get('doc_date'))

    print(f"\n  최종 통계:")
    print(f"    전체      : {total}")
    print(f"    날짜 있음 : {has_date} ({has_date/total*100:.1f}%)")
    print(f"    코드 있음 : {has_code} ({has_code/total*100:.1f}%)")
    print(f"    날짜 없음 : {no_date}  ← doc 미등록 잔여")
    print("\n  완료!")


if __name__ == "__main__":
    main()
