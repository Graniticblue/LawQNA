"""
enrich_labeled.py

seoul_qa_with_ref.jsonl의 참조 코드/날짜를
labeled.jsonl의 해당 질의 항목에 추가한다.

매칭 전략:
  1. 두 파일 모두 PDF 순서와 같으므로 Two-pointer 순차 탐색
  2. 질문 텍스트 정규화(공백·인쇄정보 제거) 후 exact match
  3. exact 실패 시 labeled 질문이 ref 질문의 앞부분인지 확인 (prefix match)
  4. 윈도우 50 내에서 매칭 시도 → 실패하면 해당 labeled 항목 스킵

추가 필드:
  doc_ref, doc_agency, doc_code, doc_date
"""

import json
import re
from pathlib import Path

LABELED_PATH  = Path("data/labeled.jsonl")
REF_PATH      = Path("data/seoul_qa_with_ref.jsonl")
OUTPUT_PATH        = Path("data/labeled_with_doc.jsonl")
UNMATCHED_PATH     = Path("data/labeled_unmatched.jsonl")

# 인쇄 정보 잔재 제거: "2판-38판.indd 14  2015. ..." 형태
PRINT_RE = re.compile(r'\d판-\d+판\.indd.*', re.DOTALL)

def norm(s: str) -> str:
    """공백 정규화 + 인쇄정보 제거"""
    s = PRINT_RE.sub('', s)
    return re.sub(r'\s+', ' ', s).strip()


def is_match(labeled_q: str, ref_q: str) -> bool:
    """
    정규화된 labeled 질문이 ref 질문과 일치하는지 판단.
    - exact match
    - labeled_q가 ref_q의 맨 앞부분과 같은 경우 (ref에 노이즈 있는 경우)
    """
    if labeled_q == ref_q:
        return True
    # ref_q가 더 길고 labeled_q가 ref_q의 앞부분인 경우
    if len(labeled_q) >= 20 and ref_q.startswith(labeled_q):
        return True
    # labeled_q가 더 길고 ref_q가 labeled_q의 앞부분인 경우 (역방향)
    if len(ref_q) >= 20 and labeled_q.startswith(ref_q):
        return True
    return False


def load_labeled(path: Path) -> list[dict]:
    records = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_ref(path: Path) -> list[tuple[str, dict]]:
    """(norm_question, doc_fields) 리스트 반환"""
    items = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            nq = norm(r['question'])
            doc = {
                'doc_ref':    r.get('doc_ref', ''),
                'doc_agency': r.get('doc_agency', ''),
                'doc_code':   r.get('doc_code', ''),
                'doc_date':   r.get('doc_date', ''),
            }
            items.append((nq, doc))
    return items


def main():
    print("=" * 60)
    print("labeled.jsonl 질의 참조코드 보강")
    print("=" * 60)

    labeled = load_labeled(LABELED_PATH)
    ref     = load_ref(REF_PATH)

    print(f"  labeled    : {len(labeled):,}개")
    print(f"  qa_with_ref: {len(ref):,}개")

    WINDOW = 50          # 한 번에 앞에서 탐색할 최대 거리
    ref_ptr  = 0         # qa_with_ref 포인터
    matched  = 0
    skipped  = 0

    enriched = []
    for lrec in labeled:
        lq = norm(lrec['contents'][0]['parts'][0]['text'])

        # 윈도우 내에서 매칭 탐색
        found_at = None
        for offset in range(min(WINDOW, len(ref) - ref_ptr)):
            rq, doc = ref[ref_ptr + offset]
            if is_match(lq, rq):
                found_at = ref_ptr + offset
                break

        if found_at is not None:
            # 매칭 성공: doc 필드 추가
            rq, doc = ref[found_at]
            lrec.update(doc)
            ref_ptr = found_at + 1   # 다음 탐색은 여기부터
            matched += 1
        else:
            # 매칭 실패: 빈 값으로 채움 (누락 표시)
            lrec.update({
                'doc_ref':    '',
                'doc_agency': '',
                'doc_code':   '',
                'doc_date':   '',
            })
            skipped += 1

        enriched.append(lrec)

    print(f"\n  매칭 성공: {matched:,}개")
    print(f"  매칭 실패: {skipped:,}개")
    print(f"  매칭률   : {matched/len(labeled)*100:.1f}%")

    # 저장 -- 전체 (매칭 포함)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        for r in enriched:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(f"\n  저장 완료: {OUTPUT_PATH}")

    # 저장 -- 미매칭만 (doc 필드 제거하고 원본 형태로)
    unmatched = []
    for r in enriched:
        if not r.get('doc_date'):
            rec = {k: v for k, v in r.items()
                   if k not in ('doc_ref', 'doc_agency', 'doc_code', 'doc_date')}
            unmatched.append(rec)

    with open(UNMATCHED_PATH, 'w', encoding='utf-8') as f:
        for r in unmatched:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(f"  미매칭 저장: {UNMATCHED_PATH}  ({len(unmatched)}개)")

    # 샘플 출력
    print("\n--- 매칭 성공 샘플 ---")
    shown = 0
    for r in enriched:
        if r.get('doc_date'):
            q = r['contents'][0]['parts'][0]['text']
            print(f"  doc_ref   : {r['doc_ref']}")
            print(f"  doc_agency: {r['doc_agency']}")
            print(f"  doc_code  : {r['doc_code']}")
            print(f"  doc_date  : {r['doc_date']}")
            print(f"  question  : {q[:60]}...")
            print()
            shown += 1
            if shown >= 3:
                break

    print("--- 매칭 실패 샘플 ---")
    shown = 0
    for r in enriched:
        if not r.get('doc_date'):
            q = r['contents'][0]['parts'][0]['text']
            print(f"  question  : {q[:80]}...")
            shown += 1
            if shown >= 3:
                break


if __name__ == "__main__":
    main()
