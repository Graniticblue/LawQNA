# -*- coding: utf-8 -*-
"""
recover_buried_seoul_qa.py — 서울시 자료집 PDF 파싱 때 앞 항목 answer에
흘러넘쳐 파묻힌 질의회신을 독립 레코드로 복원한다.

배경: seoul_qa_with_ref.jsonl 1,483건 중 38건의 answer에 다음 항목들이
통째로 딸려 있음(출처 마커 57개). 이 항목들은 독립 레코드가 없어 검색 불가.

자료집 항목 구조(반복):
    <제목 1~2줄>
    [기관 / 'YY.MM.DD]
    질 의
    <질문>
    회 신
    <답변>

사용:
    python scripts/misc/recover_buried_seoul_qa.py            # 검수 목록 출력만
    python scripts/misc/recover_buried_seoul_qa.py --write    # jsonl 생성 + 원 레코드 절단본 생성
출력(--write):
    data/seoul_qa_recovered.jsonl        복원된 신규 레코드
    data/seoul_qa_with_ref.cleaned.jsonl 오염 answer를 첫 회신까지로 절단한 전체본
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "seoul_qa_with_ref.jsonl"

# 출처 마커: [국토교통부 / '14.07.29 ] / [건축기획과-8841 / '13.02.07.]
MARKER = re.compile(
    r"\[\s*([가-힣A-Za-z0-9\- ]{2,20}?)\s*/\s*[‘’'`]*(\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?\s*\]"
)
Q_MARK = re.compile(r"^\s*질\s*의\s*$", re.M)
A_MARK = re.compile(r"^\s*회\s*신\s*$", re.M)

# 페이지·인쇄 잔재 및 장·조 헤더(자료집 러닝헤드) — 줄 단위 제거
JUNK_LINE = re.compile(
    r"^\s*(?:\S+\.indd\s+\d+.*|\d{1,4}|"
    r"제\d+[장절관]\.?\s+[^\n]{0,60}|"
    r"제\d+조\.?\s+[^\n]{0,60}\s*\d{3,4}|"
    r"20\d{2}\.\s*\d{1,2}\.\s*\d{1,2}\.\s*오[전후].*)\s*$"
)
# 답변 종결형 어미(제목과 구분용) — 제목은 보통 '~는지/~인지/~란?/?'로 끝남.
# 닫는 괄호·인용부호로 끝나는 줄도 앞 답변의 이어지는 산문으로 본다(제목 아님).
STMT_END = re.compile(
    r"(?:함|음|임|됨|다|니다|시오|랍니다|바람|것임|사료됨|참고|요망)[.\s]*$"
    r"|[)\]」』”\"]\s*$")


def _strip_junk(text: str) -> str:
    lines = [l for l in text.splitlines() if not JUNK_LINE.match(l)]
    text = "\n".join(lines).strip()
    # 줄 중간에 붙은 인쇄 잔재(페이지 넘김 지점 삽입): "2조-38조.indd 259 2015. 2. 10. 오후 3:20"
    text = re.sub(
        r"\s*\S+\.indd\s+\d+\s+20\d{2}\.\s*\d{1,2}\.\s*\d{1,2}\.\s*오[전후]\s*\d{1,2}:\d{2}\s*",
        " ", text)
    # 줄 중간에 붙은 러닝헤드: "제2조. 정의 0163", "제84조. 면적•높이 및 층수의 산정 0905"
    # (0패딩 4자리 페이지번호가 식별자 — 본문 속 진짜 조문 인용과 구분됨)
    text = re.sub(r"\s*제\d+조\.\s+[가-힣·•ㆍ,\s]{1,30}?\s+0\d{3}\s*", " ", text)
    return text.strip().lstrip("\\").strip()


def _pop_trailing_title(text: str) -> tuple[str, str]:
    """세그먼트 끝에서 다음 항목의 제목(1~2줄)을 떼어낸다.
    제목은 질문형 어미로 끝나고, 답변 본문은 종결형 어미로 끝나는 점을 이용."""
    lines = text.rstrip().splitlines()
    title: list[str] = []
    while lines and len(title) < 2:
        cand = lines[-1].strip()
        if not cand:
            lines.pop()
            continue
        if STMT_END.search(cand):
            break
        title.insert(0, lines.pop().strip())
    return "\n".join(lines).rstrip(), " ".join(title).strip()


def _parse_block(block: str) -> tuple[str, str] | None:
    """마커 이후 블록에서 (질문, 답변) 추출. 질 의/회 신 마커 필수."""
    qm = Q_MARK.search(block)
    am = A_MARK.search(block)
    if not qm or not am or am.start() < qm.end():
        return None
    q = _strip_junk(block[qm.end():am.start()])
    a = _strip_junk(block[am.end():])
    if len(q) < 10 or len(a) < 10:
        return None
    return q, a


def recover():
    rows = [json.loads(l) for l in SRC.read_text(encoding="utf-8").splitlines() if l.strip()]
    existing_q = {re.sub(r"\s+", "", str(r.get("question",""))[:40]) for r in rows}
    # 중복 판정은 '질문 텍스트' 기준 — 파묻힌 항목 다수가 enrich 데이터(labeled)에
    # 이미 별도 항목으로 존재함(자료집을 다른 경로로도 처리했던 것).
    # doc_code 기준으로만 걸면 같은 날짜의 서로 다른 국토교통부 회신 2건이
    # 날짜 기반 코드 충돌로 오폭됨('14.07.07 실측 사례) → 코드는 접미사로 유일화.
    existing_codes = {str(r.get("doc_code", "")) for r in rows if r.get("doc_code")}
    labeled = ROOT / "data" / "labeled_with_doc.jsonl"
    if labeled.exists():
        import ast
        for l in labeled.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            try:
                rec = json.loads(l)
                existing_codes.add(str(rec.get("doc_code", "")))
                c = rec.get("contents", "")
                c = ast.literal_eval(c) if isinstance(c, str) else c
                for turn in c:
                    if turn.get("role") == "user":
                        q = " ".join(p.get("text", "") for p in turn.get("parts", []))
                        existing_q.add(re.sub(r"\s+", "", q[:40]))
                        break
            except Exception:
                pass

    recovered: list[dict] = []
    cleaned_rows: list[dict] = []
    problems: list[str] = []

    for r in rows:
        ans = str(r.get("answer", ""))
        marks = list(MARKER.finditer(ans))
        if not marks:
            cleaned_rows.append(r)
            continue

        # ── 원 레코드: 첫 마커 앞까지 + 제목 절단 ──
        head, first_title = _pop_trailing_title(ans[:marks[0].start()])
        r2 = dict(r)
        r2["answer"] = _strip_junk(head)
        cleaned_rows.append(r2)

        # ── 파묻힌 항목들 복원 ──
        titles = [first_title]
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(ans)
            body, next_title = _pop_trailing_title(ans[m.end():end])
            if i + 1 < len(marks):
                titles.append(next_title)
            parsed = _parse_block(body)
            org = re.sub(r"\s+", " ", m.group(1)).strip()
            yy, mm, dd = m.group(2), int(m.group(3)), int(m.group(4))
            century = "19" if int(yy) >= 50 else "20"   # '97 등 90년대 건 방어
            date_iso = f"{century}{yy}-{mm:02d}-{dd:02d}"
            label = f"{org} / ‘{yy}.{mm:02d}.{dd:02d}."
            if not parsed:
                problems.append(f"[파싱실패] {label} (원 doc_code={r.get('doc_code')}) — 질의/회신 마커 불명")
                continue
            q, a = parsed
            title = _strip_junk(titles[i]) if titles[i] else ""
            full_q = (title + "\n" + q).strip() if title else q
            # 기존 레코드와 중복 방지 — 제목 포함/본문 단독 두 키 모두 비교
            # (labeled의 질문엔 자료집 제목 줄이 없어 본문 키로만 걸림)
            k_full = re.sub(r"\s+", "", full_q[:40])
            k_body = re.sub(r"\s+", "", q[:40])
            if k_full in existing_q or k_body in existing_q:
                problems.append(f"[중복스킵] {label} — 동일 질문 기존 레코드 존재")
                continue
            existing_q.update({k_full, k_body})
            # 기관/코드 분해 — 기존 doc_code 관례 유지:
            #   "법제처 11-0320"        → agency 법제처,     code 11-0320
            #   "건축기획과-8922"       → agency 건축기획과,  code 8922
            #   "서울시건지 58501-01363" → agency 서울시건지, code 58501-01363
            #   "국토교통부"            → 서울시질의회신 - 국토교통부 YYMMDD
            agency, doc_code = org, ""
            m2 = re.match(r"^법제처\s*(\d{2}-\d{4})$", org)
            m3 = re.match(r"^([가-힣]{2,12}(?:과|팀|국|실|담당관))-(\d{2,6})$", org)
            m4 = re.match(r"^([가-힣]{2,12})\s+([\d\-]{4,15})$", org)
            if m2:
                agency, doc_code = "법제처", m2.group(1)
            elif m3:
                agency, doc_code = m3.group(1), m3.group(2)
            elif m4:
                agency, doc_code = m4.group(1), m4.group(2)
            else:
                doc_code = f"서울시질의회신 - {org} {yy}{mm:02d}{dd:02d}"
            # 질문이 다른데 코드가 겹치면(같은 날짜 회신 2건 등) 접미사로 유일화
            if doc_code in existing_codes:
                base, n = doc_code, 2
                while f"{base}-{n}" in existing_codes:
                    n += 1
                doc_code = f"{base}-{n}"
            existing_codes.add(doc_code)
            recovered.append({
                "question": full_q,
                "answer": a,
                "doc_ref": f"[{org} / ‘{yy}.{mm:02d}.{dd:02d}.]",
                "doc_agency": agency,
                "doc_code": doc_code,
                "doc_date": date_iso,
                "recovered_from": str(r.get("doc_code", "")),
            })

    # ── 검수 목록 ──
    print(f"오염 레코드에서 복원된 질의회신: {len(recovered)}건 / 문제: {len(problems)}건\n")
    for i, rec in enumerate(recovered, 1):
        print(f"[{i:2d}] {rec['doc_ref']}  (원출처 레코드: {rec['recovered_from']})")
        print(f"     Q: {rec['question'][:90].replace(chr(10),' / ')}")
        print(f"     A: {rec['answer'][:90].replace(chr(10),' ')}")
    if problems:
        print("\n-- 문제 목록 --")
        for p in problems:
            print("  " + p)

    if "--write" in sys.argv:
        out1 = ROOT / "data" / "seoul_qa_recovered.jsonl"
        out2 = ROOT / "data" / "seoul_qa_with_ref.cleaned.jsonl"
        out1.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in recovered) + "\n", encoding="utf-8")
        out2.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in cleaned_rows) + "\n", encoding="utf-8")
        print(f"\n저장: {out1} ({len(recovered)}건)")
        print(f"저장: {out2} ({len(cleaned_rows)}건 — 오염 answer 절단본)")


if __name__ == "__main__":
    recover()
