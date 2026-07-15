#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_ingest_report.py -- 학습 검수 보고서 생성 (data/ingest_reports/)

API 소싱 학습(해석례·판례)의 내용을 사람이 검수할 수 있게 레코드·문단/gist
대조·article_roles 추가 내역·eval 결과를 마크다운 한 파일로 묶는다.
학습 사이클의 마지막 단계로 실행한다 (빌드 → eval → 보고서 → 커밋).

사용법:
  python scripts/make_ingest_report.py --code 16-0506      # 법제처 해석례
  python scripts/make_ingest_report.py --case 2009두8946   # 판례
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).parent.parent
REPORT_DIR = BASE_DIR / "data" / "ingest_reports"
ROLES_DIR = BASE_DIR / "data" / "article_roles"


def _load_jsonl(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8").strip().split("\n")[0])
    except Exception:
        return None


def _roles_for(code: str) -> list[dict]:
    """article_roles 중 last_updated_by에 이 안건/사건 번호가 언급된 파일."""
    out = []
    for p in sorted(ROLES_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if code in str(d.get("last_updated_by", "")):
            d["_file"] = p.name
            out.append(d)
    return out


def _render_roles(roles: list[dict]) -> list[str]:
    if not roles:
        return ["*(이 학습에서 추가·갱신된 조문 프레임 없음 — 기존 파일 보존)*"]
    L = []
    for r in roles:
        L.append(f"### `{r['_file']}` — {r.get('law', '')} {r.get('article_no', '')}")
        L.append(f"- **요약**: {r.get('article_summary', '')}")
        L.append(f"- **유형**: {r.get('article_type', '')} | 갱신 {r.get('last_updated', '')}")
        for req in r.get("requirements", []):
            L.append(f"- **[{req.get('항호', '')}]** ({req.get('role', '')}) {req.get('text', '')}")
            L.append(f"  - 판단 근거: {req.get('role_reason', '')}")
        if r.get("interpretation_logic"):
            L.append(f"- **해석 원칙**: {r['interpretation_logic']}")
        L.append("")
    return L


def _render_eval(code: str) -> list[str]:
    ev = None
    for p in (BASE_DIR / "data" / "eval_results").glob(f"{code}_eval.json"):
        try:
            ev = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    if not ev:
        return ["*(eval 결과 파일 없음)*"]
    s = ev.get("scores", {})
    L = [f"- **Correctness {s.get('correctness')}** / Coverage {s.get('coverage')} / "
         f"거짓인용 {'있음' if s.get('spurious_cite') else '없음'} / 갭 `{s.get('gap_type')}`",
         f"- 컷오프: {ev.get('doc_date')} (선고·회신일 기준, leave-one-out 자기 제외)",
         f"- 채점 근거(정오): {str(s.get('correctness_reason', ''))}",
         f"- 채점 근거(논거): {str(s.get('coverage_reason', ''))[:400]}"]
    if s.get("gap_detail"):
        L.append(f"- 갭 상세: {str(s.get('gap_detail'))[:400]}")
    if s.get("missing_articles"):
        L.append(f"- 누락 조문: {', '.join(s['missing_articles'][:8])}")
    return L


def report_expc(code: str) -> Path:
    rec_path = BASE_DIR / "data" / "qa_precedents" / "updates" / f"법제처_{code}.jsonl"
    rec = _load_jsonl(rec_path)
    if not rec:
        sys.exit(f"[오류] 레코드 없음: {rec_path}")
    q = rec["contents"][0]["parts"][0]["text"]
    a = rec["contents"][1]["parts"][0]["text"]
    ans_head = a.split("【이유】")[0].replace("【회답】", "").strip()

    L = [f"# 학습 검수 보고 — 법제처 해석례 {code}",
         "",
         f"| 항목 | 내용 |", "|---|---|",
         f"| 문서 | {rec.get('doc_ref', '')} |",
         f"| 회신일 | {rec.get('doc_date', '')} |",
         f"| 관계 유형 | `{rec.get('relation_type', '')}` |",
         f"| 보고서 생성 | {date.today()} |",
         "",
         "## 1. 관계 유형 해설", rec.get("relation_name", ""), "",
         "## 2. 질의요지", q, "",
         "## 3. 회답", ans_head, "",
         "## 4. 핵심 요지 (label_summary — 검색 문서의 대표 요약)",
         rec.get("label_summary", ""), "",
         "## 5. 문단 · 논지(gist) 대조 — *gist가 원문을 왜곡하지 않는지 검수*", ""]
    for i, p in enumerate(rec.get("paragraphs", []), 1):
        L.append(f"### P{i}")
        L.append(f"> {p.get('text', '')}")
        L.append("")
        L.append(f"**논지(검색 청크)**: {p.get('gist', '')}")
        L.append("")
    L += ["## 6. 논리 전개 (logic_steps)"]
    for s in rec.get("logic_steps", []):
        L.append(f"{s.get('seq')}. **[{s.get('role')}]** {s.get('title')}")
    da = rec.get("doc_analysis") or {}
    L += ["", "## 7. 심층 분석 (doc_analysis)",
          f"- **원인 분석**: {da.get('cause_analysis', '')}"]
    for ll in da.get("legal_logic", []):
        L.append(f"- [{ll.get('role')}] **{ll.get('title')}** — {ll.get('content')}")
        if ll.get("provisions"):
            L.append(f"  - 근거 조문: {', '.join(ll['provisions'])}")
    L += ["- **핵심 조문**: " + ", ".join(da.get("key_provisions", [])), "",
          "## 8. 검색 태그", rec.get("search_tags", ""), "",
          "## 9. 조문 프레임(article_roles) 추가 내역"]
    L += _render_roles(_roles_for(code))
    L += ["## 10. eval 결과 (날짜 컷오프 + leave-one-out)"]
    L += _render_eval(code)
    out = REPORT_DIR / f"법제처_{code}_학습보고.md"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")
    return out


def report_prec(case: str) -> Path:
    rec = None
    for p in (BASE_DIR / "data" / "court_cases").glob(f"*{case}.jsonl"):
        rec = _load_jsonl(p)
    if not rec:
        sys.exit(f"[오류] 판례 레코드 없음: {case}")
    L = [f"# 학습 검수 보고 — {rec.get('court', '')} {case}",
         "",
         f"| 항목 | 내용 |", "|---|---|",
         f"| 사건명 | {rec.get('case_name', '')} |",
         f"| 선고일 | {rec.get('decision_date', '')} |",
         f"| 관계 유형 | `{rec.get('relation_types', '')}` |",
         f"| 인용 법령 | {rec.get('cited_laws_str', '')} |",
         f"| 보고서 생성 | {date.today()} |",
         "",
         "## 1. 관계 유형 해설", rec.get("relation_name", ""), "",
         "## 2. 핵심 결론 (label_summary)", rec.get("label_summary", ""), "",
         "## 3. 판시사항 (holding)", rec.get("holding", ""), "",
         "## 4. 사실관계 (facts)", rec.get("facts", ""), "",
         "## 5. 이유 요약 (reasoning_summary)", rec.get("reasoning_summary", ""), "",
         "## 6. 인용 조문 · 선례",
         "- 조문: " + ", ".join(rec.get("cited_articles", [])),
         "- 선례: " + ", ".join(rec.get("related_cases", [])), "",
         "## 7. 검색 태그", rec.get("search_tags", ""), "",
         "## 8. 조문 프레임(article_roles) 추가 내역"]
    L += _render_roles(_roles_for(case))
    out = REPORT_DIR / f"{rec.get('court', '법원')}_{case}_학습보고.md"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser(description="학습 검수 보고서 생성")
    ap.add_argument("--code", help="법제처 해석례 안건번호 (예: 16-0506)")
    ap.add_argument("--case", help="판례 사건번호 (예: 2009두8946)")
    args = ap.parse_args()
    if args.code:
        out = report_expc(args.code)
    elif args.case:
        out = report_prec(args.case)
    else:
        ap.print_help()
        sys.exit(1)
    print(f"[보고서] {out}")


if __name__ == "__main__":
    main()
