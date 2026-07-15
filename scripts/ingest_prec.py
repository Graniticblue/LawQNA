#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest_prec.py -- 판례 학습 보조 도구 (국가법령정보센터 판례 API)

역할 구분 (운영 원칙):
  * 답변 파이프라인은 학습된 코퍼스(data/court_cases)만 검색한다.
  * 이 도구의 API 접근은 ① 학습 시 원문 스캐폴드 취득, ② 인용 실존 검증
    (--verify, 허위사실 판명)에 한정한다. 실시간 검색 용도가 아니다.

사용법:
  python scripts/ingest_prec.py --case 2009두8946 --scaffold
      # 기보유 가드 → API 취득 → 스캐폴드 JSON 출력 (큐레이션용)
      # 결정론 필드(사건번호·선고일·판시사항·참조조문·참조판례)는 채워지고
      # 큐레이션 필드(label_summary·facts·reasoning_summary·relation_types·
      # search_tags)는 TODO로 남는다.
  python scripts/ingest_prec.py --verify 2009두8946
      # 실존 검증: 존재 여부 + 법원/선고일/사건명 + 판시사항 첫 항목

스캐폴드 산출물: data/court_cases/_scaffold_{사건번호}.json
  큐레이션 완료 후 data/court_cases/대법원_{사건번호}.jsonl 로 저장하고
  `python ingest/ingest_court_cases.py --update` 로 인덱싱한다.
"""
import argparse
import glob
import html
import json
import re
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import requests

BASE_DIR = Path(__file__).parent.parent
CASES_DIR = BASE_DIR / "data" / "court_cases"
QA_DIR = BASE_DIR / "data" / "qa_precedents"
OC = "duncan9823"
SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"

# 정식 인용 표기: "대법원 2003. 4. 25. 선고 2002두3201 판결(공2003상, 1337)"
CITE_RE = re.compile(
    r"(대법원|[가-힣]+(?:고등|지방|행정|가정|회생)법원[가-힣]*)\s*"
    r"(\d{4}\.\s?\d{1,2}\.\s?\d{1,2}\.?)\s*선고\s*"
    r"(\d{2,4}[가-힣]+\d+(?:,\s?\d+)*)\s*(전원합의체\s*)?(판결|결정)")


def _clean(s: str) -> str:
    s = html.unescape(re.sub(r"<br\s*/?>", "\n", str(s or "")))
    return re.sub(r"[ \t]+", " ", s).strip()


def learned_codes() -> set:
    """기보유 가드: court_cases + qa_precedents의 학습 완료 코드."""
    codes = set()
    for p in glob.glob(str(CASES_DIR / "*.jsonl")):
        try:
            for line in open(p, encoding="utf-8"):
                if line.strip():
                    codes.add(json.loads(line).get("case_id", ""))
        except Exception:
            pass
    for p in glob.glob(str(QA_DIR / "**" / "*.jsonl"), recursive=True):
        m = re.search(r"법제처_(\d{2}-\d{4})", p)
        if m:
            codes.add(m.group(1))
    codes.discard("")
    return codes


def api_fetch(case_no: str) -> dict | None:
    """사건번호로 검색 → 상세(판시사항·판결요지·참조조문·참조판례·전문)."""
    r = requests.get(SEARCH_URL, params={
        "OC": OC, "target": "prec", "type": "JSON",
        "query": case_no, "display": 20}, timeout=25)
    root = r.json()
    items = root[list(root.keys())[0]].get("prec") or []
    if isinstance(items, dict):
        items = [items]
    hit = next((it for it in items
                if str(it.get("사건번호", "")).replace(" ", "") == case_no.replace(" ", "")), None)
    if not hit:
        return None
    r2 = requests.get(SERVICE_URL, params={
        "OC": OC, "target": "prec", "type": "JSON",
        "ID": hit["판례일련번호"]}, timeout=25)
    return r2.json().get("PrecService") or None


def split_numbered(field: str) -> list[str]:
    """'[1] ... [2] ...' → 항목 리스트 ([n] 없으면 통짜 1개)."""
    text = _clean(field)
    if not text:
        return []
    parts = re.split(r"\[\d+\]\s*", text)
    parts = [p.strip(" ,/") for p in parts if p.strip(" ,/")]
    return parts


def parse_citations(field: str) -> list[dict]:
    out, seen = [], set()
    for m in CITE_RE.finditer(_clean(field)):
        case = m.group(3).replace(" ", "")
        if case in seen:
            continue
        seen.add(case)
        out.append({"court": m.group(1), "date": m.group(2).strip(),
                    "case": case, "en_banc": bool(m.group(4))})
    return out


def build_scaffold(case_no: str, d: dict) -> dict:
    date = str(d.get("선고일자", ""))
    date_fmt = f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(date) == 8 else date
    holdings = split_numbered(d.get("판시사항"))
    gists = split_numbered(d.get("판결요지"))
    arts = []
    for grp in split_numbered(d.get("참조조문")):
        arts += [a.strip() for a in grp.split(",") if a.strip()]
    cites = parse_citations(d.get("참조판례"))
    body = _clean(d.get("판례내용"))
    return {
        "_스캐폴드": "결정론 필드는 API 원문. TODO 필드를 큐레이션 후 "
                    "대법원_{case_id}.jsonl 로 저장할 것.",
        "case_id": case_no,
        "court": _clean(d.get("법원명")) or "대법원",
        "decision_date": date_fmt,
        "case_name": _clean(d.get("사건명")),
        "holding_items": holdings,          # 판시사항 [n]
        "gist_items": gists,                # 판결요지 [n]
        "cited_articles": sorted(set(arts)),
        "related_cases_parsed": cites,      # 참조판례 (사건번호·전합 여부)
        "inline_cites": [c["case"] for c in parse_citations(body)],
        "body_excerpt": body[:3000],
        "TODO_label_summary": "",
        "TODO_facts": "",
        "TODO_reasoning_summary": "",
        "TODO_relation_types": "",
        "TODO_search_tags": "",
    }


def main():
    ap = argparse.ArgumentParser(description="판례 학습 스캐폴드 / 인용 검증")
    ap.add_argument("--case", help="학습 스캐폴드 생성할 사건번호")
    ap.add_argument("--scaffold", action="store_true", help="--case와 함께 사용")
    ap.add_argument("--verify", help="실존 검증할 사건번호 (허위사실 판명 전용)")
    args = ap.parse_args()

    if args.verify:
        d = api_fetch(args.verify)
        if not d:
            print(f"[미확인] '{args.verify}' — 판례 DB(16.9만건)에서 확인 불가. "
                  "미간행 가능성 있으므로 '존재하지 않음' 단정은 금지, 인용은 보류.")
            sys.exit(2)
        heads = split_numbered(d.get("판시사항"))
        print(f"[실존] {_clean(d.get('법원명'))} {args.verify} "
              f"({str(d.get('선고일자'))}) {_clean(d.get('사건명'))[:40]}")
        if heads:
            print("  판시사항[1]:", heads[0][:160])
        return

    if not args.case:
        ap.print_help()
        sys.exit(1)

    if args.case in learned_codes():
        print(f"[가드] {args.case} 는 이미 학습됨 — 중단. "
              "(data/court_cases 또는 qa_precedents 보유)")
        sys.exit(3)

    d = api_fetch(args.case)
    if not d:
        print(f"[실패] {args.case} — API에서 찾을 수 없음")
        sys.exit(2)

    sc = build_scaffold(args.case, d)
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    out = CASES_DIR / f"_scaffold_{args.case}.json"
    out.write_text(json.dumps(sc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[스캐폴드] {out}")
    print(f"  판시사항 {len(sc['holding_items'])}항 | 참조조문 {len(sc['cited_articles'])} | "
          f"참조판례 {len(sc['related_cases_parsed'])} | 본문 인라인 인용 {len(sc['inline_cites'])}")


if __name__ == "__main__":
    main()
