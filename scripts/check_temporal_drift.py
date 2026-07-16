#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_temporal_drift.py -- 해석례 학습 레코드의 시제 드리프트 게이트/스캐너

문제: 학습 사이클의 큐레이션(gist·label_summary·article_roles)은 '회신 당시
문언 ≈ 현행 문언'을 암묵 전제하는데, 이 전제가 깨진 사례가 누적 3건이다
(건축법 제60조④ 2022 신설 — 18-0283·21-0849, 국토계획법 영 제25조③ 저촉
한정 괄호 2019. 8. 6. 신설 — 16-0506). 전부 사후 우연 발견이었다.

동작: 레코드의 key_provisions 각각에 대해
  ① 현행 문언 = data/raw_laws/all_articles.jsonl (검색 코퍼스와 동일 소스)
  ② 당시 문언 = 회신일(doc_date) 시행판 (법제처 연혁 API — 빌드타임 전용,
     data/law_cache/temporal/ 에 캐시)
을 정규화 대조한다. 인용 항이 특정되면 그 항만, 아니면 조문 전체를 비교.

게이트 규칙(--code): '인용 항 차이'가 있는데 레코드에 '입법 후속' 주석이
없으면 exit 2 — 주석 없이는 커밋하지 말 것.

사용법:
  python scripts/check_temporal_drift.py --code 16-0506     # 빌드 게이트
  python scripts/check_temporal_drift.py --all              # 소급 전수 스캔
"""
import argparse
import glob
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

OC = "duncan9823"
BASE_DIR = Path(__file__).parent.parent
ARTICLES = BASE_DIR / "data" / "raw_laws" / "all_articles.jsonl"
CACHE_DIR = BASE_DIR / "data" / "law_cache" / "temporal"
REPORT_DIR = BASE_DIR / "data" / "ingest_reports"

_ALIASES = {
    "국토계획법": "국토의 계획 및 이용에 관한 법률",
    "도시정비법": "도시 및 주거환경정비법",
    "녹색건축법": "녹색건축물 조성 지원법",
    "소방시설법": "소방시설 설치 및 관리에 관한 법률",
    "주택건설기준규정": "주택건설기준 등에 관한 규정",
}

_HANG_CHARS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚"


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8", errors="replace")


def _norm(s: str) -> str:
    """대조용 정규화 — 법적 실질이 아닌 표기 차이를 전부 제거한다:
    개정 꼬리표(장문 포함)·[본조신설] 류 대괄호 꼬리표·조문 제목 헤딩·
    한자 병기·공백·따옴표·가운뎃점·중복 마커."""
    s = str(s or "")
    s = re.sub(r"<[^<>]{1,400}>", "", s)                     # <개정 2009.6.9., ...> 장문 허용
    s = re.sub(r"\[(?:본조신설|전문개정|제목개정|시행일)[^\[\]]{0,100}\]", "", s)
    s = re.sub(r"제\d+조(?:의\d+)?\([^()]{1,60}\)", "", s)   # 헤딩 '제N조(제목)' 혼입 제거
    s = re.sub(r"[\s​﻿]+", "", s)
    for q in "\"“”〝〞'‘’*`_":
        s = s.replace(q, "")
    s = s.replace("ㆍ", "").replace("·", "").replace("・", "")
    s = s.replace("（", "(").replace("）", ")")
    s = re.sub(r"\([一-鿿]{1,20}\)", "", s)                  # 한자 병기 (日照)(正北方向)
    s = re.sub(rf"([{_HANG_CHARS}])\1", r"\1", s)            # "①①" → "①"
    s = re.sub(r"(\d{1,2}\.)\1", r"\1", s)                   # "1.1." → "1."
    return s


# ── 현행 코퍼스 ──────────────────────────────────────────

_corpus: dict | None = None


def _load_corpus() -> dict:
    global _corpus
    if _corpus is not None:
        return _corpus
    c: dict = {}
    with open(ARTICLES, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            art = str(r.get("article_no", "")).replace(" ", "")
            if not re.fullmatch(r"제\d+조(의\d+)?", art):
                continue
            key = (re.sub(r"\s+", "", r["law_name"]), art)
            c[key] = c.get(key, "") + r.get("content", "")
    _corpus = c
    return c


# ── 당시판 (연혁 API + 캐시) ─────────────────────────────

def _versions(law_name: str) -> list[tuple[str, str]]:
    """법령의 연혁 [(시행일자, MST)] — 캐시."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[\\/:*?\"<>| ]", "", law_name)
    p = CACHE_DIR / f"versions_{safe}.json"
    if p.exists():
        return [tuple(x) for x in json.loads(p.read_text(encoding="utf-8"))]
    q = urllib.parse.quote(law_name)
    js = json.loads(_get(
        f"http://www.law.go.kr/DRF/lawSearch.do?OC={OC}&target=eflaw&type=JSON&query={q}&display=100"))
    items = js.get("LawSearch", {}).get("law", [])
    if isinstance(items, dict):
        items = [items]
    out = sorted({(str(it.get("시행일자", "")), str(it.get("법령일련번호", "")))
                  for it in items
                  if re.sub(r"\s+", "", it.get("법령명한글", "")) == re.sub(r"\s+", "", law_name)
                  and it.get("시행일자")})
    p.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def _historical_article(law_name: str, art: str, as_of: str) -> str | None:
    """as_of(YYYY-MM-DD) 시행판의 조문 텍스트. 실패/범위 밖은 None."""
    vers = [v for v in _versions(law_name) if v[0] <= as_of.replace("-", "")]
    if not vers:
        return None
    mst = vers[-1][1]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = CACHE_DIR / f"law_{mst}.json"
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
    else:
        raw = _get(f"http://www.law.go.kr/DRF/lawService.do?OC={OC}&target=law&type=JSON&MST={mst}")
        if len(raw) < 10:
            return None
        p.write_text(raw, encoding="utf-8")
        d = json.loads(raw)
    arts = d.get("법령", {}).get("조문", {}).get("조문단위", [])
    if isinstance(arts, dict):
        arts = [arts]
    m = re.fullmatch(r"제(\d+)조(?:의(\d+))?", art)
    if not m:
        return None
    no, branch = m.group(1), m.group(2)

    def collect(x):
        """조문내용 → 항내용 → 호 → 목 고정 순서로 수집 (버전별 JSON 키 순서 차이 중화)."""
        if isinstance(x, str):
            return x + "\n"
        if isinstance(x, list):
            return "".join(collect(i) for i in x)
        if isinstance(x, dict):
            out = ""
            for k in ("조문내용", "항내용", "호내용", "목내용", "항", "호", "목"):
                if k in x:
                    out += collect(x[k])
            return out
        return ""

    for a in arts:
        if str(a.get("조문번호")) == no and str(a.get("조문여부")) == "조문":
            ab = str(a.get("조문가지번호") or "").strip()
            if (branch or "") == (ab if ab and ab != "0" else ""):
                return collect(a)
    return None


# ── 비교 ─────────────────────────────────────────────────

def _split_hangs(text: str) -> dict[str, str]:
    """조문 텍스트 → {항마커: 본문}. 마커 없으면 {'', 전체}."""
    idxs = [(m.start(), m.group(0)) for m in re.finditer(rf"[{_HANG_CHARS}]", text)]
    # 같은 마커 연쇄("① ①")는 첫 등장만
    seen, marks = set(), []
    for pos, ch in idxs:
        if ch not in seen:
            seen.add(ch)
            marks.append((pos, ch))
    if not marks:
        return {"": text}
    out = {"": text[:marks[0][0]]}
    for i, (pos, ch) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        out[ch] = text[pos:end]
    return out


def _first_diff(a: str, b: str, ctx: int = 45) -> str:
    n = min(len(a), len(b))
    i = next((k for k in range(n) if a[k] != b[k]), n)
    return (f"당시…{a[max(0, i - ctx):i + ctx]}… ↔ 현행…{b[max(0, i - ctx):i + ctx]}…")


def _extract_ho(text: str, ho: str) -> str | None:
    """정규화 텍스트에서 'N.' 호 블록 추출 (다음 호 또는 끝까지)."""
    n = _norm(text)
    m = re.search(rf"(?<![0-9]){ho}\.", n)
    if not m:
        return None
    nxt = re.search(rf"(?<![0-9]){int(ho) + 1}\.", n[m.end():])
    return n[m.start(): m.end() + nxt.start()] if nxt else n[m.start():]


def compare_provision(law_name: str, art: str, hang_no: str | None,
                      ho_no: str | None, doc_date: str) -> dict:
    """반환: {verdict, detail}. verdict: 동일|인용부분차이|타부분차이|비교불가(사유)."""
    corpus = _load_corpus()
    cur = corpus.get((re.sub(r"\s+", "", law_name), art))
    if not cur:
        return {"verdict": "비교불가", "detail": "현행 코퍼스에 없음"}
    old = _historical_article(law_name, art, doc_date)
    if old is None:
        return {"verdict": "비교불가", "detail": "연혁 API에서 당시판 미확보"}
    if _norm(old) == _norm(cur):
        return {"verdict": "동일", "detail": ""}
    # 항 없이 호만 특정된 인용('제46조제4호'): 그 호 블록만 대조 — 조문 재편·
    # 서식 차이(헤딩·수집 순서)로 인한 전체 비교 노이즈를 피한다.
    if ho_no and not hang_no:
        o_ho, c_ho = _extract_ho(old, ho_no), _extract_ho(cur, ho_no)
        if o_ho and c_ho:
            if o_ho == c_ho:
                return {"verdict": "타부분차이", "detail": f"인용 제{ho_no}호는 동일, 조문 내 다른 부분만 변경"}
            return {"verdict": "인용부분차이",
                    "detail": f"제{ho_no}호 변경 — " + _first_diff(o_ho, c_ho)}
        if (o_ho is None) != (c_ho is None):
            return {"verdict": "인용부분차이", "detail": f"제{ho_no}호가 한쪽에만 존재 (신설·삭제·재편)"}
    oh, ch = _split_hangs(old), _split_hangs(cur)
    if hang_no:
        mark = _HANG_CHARS[int(hang_no) - 1] if hang_no.isdigit() and int(hang_no) <= len(_HANG_CHARS) else None
        if mark and mark in oh and mark in ch:
            if _norm(oh[mark]) == _norm(ch[mark]):
                return {"verdict": "타부분차이", "detail": f"인용 {mark}항은 동일, 조문 내 다른 부분만 변경"}
            # 항은 다르지만 인용이 호까지 특정('제119조제1항제9호')이면 그 호만 대조
            if ho_no:
                o_ho, c_ho = _extract_ho(oh[mark], ho_no), _extract_ho(ch[mark], ho_no)
                if o_ho and c_ho:
                    if o_ho == c_ho:
                        return {"verdict": "타부분차이",
                                "detail": f"인용 {mark}항제{ho_no}호는 동일, 항 내 다른 부분만 변경"}
                    return {"verdict": "인용부분차이",
                            "detail": f"{mark}항제{ho_no}호 변경 — " + _first_diff(o_ho, c_ho)}
                if (o_ho is None) != (c_ho is None):
                    return {"verdict": "인용부분차이", "detail": f"{mark}항제{ho_no}호가 한쪽에만 존재"}
            return {"verdict": "인용부분차이",
                    "detail": f"{mark}항 변경 — " + _first_diff(_norm(oh[mark]), _norm(ch[mark]))}
        if mark and (mark in oh) != (mark in ch):
            return {"verdict": "인용부분차이", "detail": f"{mark}항이 한쪽에만 존재 (신설·삭제)"}
    # 인용 단위 미특정 시에만 포함 관계 완화 적용: 전후 문장 추가(진짜 개정)
    # 또는 구판 JSON의 도입부 수집 누락(형식) — 중간 삽입형 개정(16-0506
    # 괄호)이나 특정 항·호의 변경은 위 분기에서 이미 잡힌다.
    if _norm(old) in _norm(cur) or _norm(cur) in _norm(old):
        return {"verdict": "포함차이", "detail": "한쪽 텍스트가 다른 쪽에 통째로 포함 — 전후 추가 개정 또는 구판 수집 누락(검토 권장, 게이트 비차단)"}
    # 항 미특정: 어느 항이 다른지 요약
    diffs = [k or "(본문)" for k in set(oh) | set(ch)
             if _norm(oh.get(k, "")) != _norm(ch.get(k, ""))]
    return {"verdict": "인용부분차이",
            "detail": "변경 부분: " + ", ".join(sorted(diffs)[:6]) + " — " + _first_diff(_norm(old), _norm(cur))}


# ── 레코드 처리 ──────────────────────────────────────────

_PROV_PAT = re.compile(r"^(.*?)(제\d+조(?:의\d+)?)(?:제(\d+)항)?(?:제(\d+)호)?")


def _parse_provision(p: str):
    p = p.strip().strip("「」")
    m = _PROV_PAT.match(p)
    if not m or not m.group(1).strip():
        return None
    law = m.group(1).strip()
    law = _ALIASES.get(law.replace(" ", ""), law)
    return law, m.group(2), m.group(3), m.group(4)


def check_record(path: str) -> list[dict]:
    rec = json.loads(open(path, encoding="utf-8").readline())
    code = rec.get("doc_code", Path(path).stem)
    doc_date = rec.get("doc_date", "")
    provs = (rec.get("doc_analysis") or {}).get("key_provisions") or []
    blob = json.dumps(rec, ensure_ascii=False)
    annotated = any(k in blob for k in
                    ("입법 후속", "시제 주의", "입법적 실현", "입법 실현", "현행법 질의",
                     "신설로 실현", "명문 허용", "개정으로 신설"))
    rows = []
    seen = set()
    for p in provs:
        parsed = _parse_provision(p)
        if not parsed:
            rows.append({"code": code, "prov": p, "verdict": "비교불가", "detail": "파싱 불가", "annotated": annotated})
            continue
        law, art, hang, ho = parsed
        if (law, art, hang, ho) in seen:
            continue
        seen.add((law, art, hang, ho))
        try:
            r = compare_provision(law, art, hang, ho, doc_date)
        except Exception as e:
            r = {"verdict": "비교불가", "detail": f"오류: {e}"}
        rows.append({"code": code, "prov": p, "verdict": r["verdict"],
                     "detail": r["detail"], "annotated": annotated, "doc_date": doc_date})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", help="해석례 안건번호 (빌드 게이트)")
    ap.add_argument("--all", action="store_true", help="qa_precedents 전수 스캔")
    args = ap.parse_args()

    if args.code:
        paths = glob.glob(str(BASE_DIR / "data" / "qa_precedents" / "**" / f"법제처_{args.code}.jsonl"),
                          recursive=True)
    elif args.all:
        paths = sorted(glob.glob(str(BASE_DIR / "data" / "qa_precedents" / "**" / "법제처_*.jsonl"),
                                 recursive=True))
    else:
        ap.error("--code 또는 --all 필요")
    if not paths:
        print("레코드 없음")
        sys.exit(1)

    all_rows = []
    for p in paths:
        rows = check_record(p)
        all_rows.extend(rows)
        drift = [r for r in rows if r["verdict"] == "인용부분차이"]
        mark = "⚠" if drift else "·"
        print(f"{mark} {Path(p).stem}: " + ", ".join(
            f"{r['verdict']}×{sum(1 for x in rows if x['verdict'] == r['verdict'])}"
            for r in {x['verdict']: x for x in rows}.values()))
        for r in drift:
            note = " [주석 있음]" if r["annotated"] else " [★ 주석 없음 — 검토 필요]"
            print(f"    - {r['prov']}: {r['detail'][:140]}{note}")

    if args.all:
        REPORT_DIR.mkdir(exist_ok=True)
        out = REPORT_DIR / f"시제드리프트_스캔_{date.today().isoformat()}.md"
        lines = [f"# 시제 드리프트 전수 스캔 ({date.today().isoformat()})",
                 "",
                 "레코드 key_provisions의 '회신 당시 시행판 vs 현행 코퍼스' 대조 결과.",
                 "`인용부분차이`이면서 주석 없음(★)이 검토 대상 — 16-0506형 시제 반전 후보.",
                 "",
                 "| 코드 | 회신일 | 조문 | 판정 | 상세 | 주석 |",
                 "|---|---|---|---|---|---|"]
        for r in all_rows:
            if r["verdict"] == "동일":
                continue
            lines.append(f"| {r['code']} | {r.get('doc_date','')} | {r['prov']} | {r['verdict']} "
                         f"| {r['detail'][:160].replace('|', '¦')} | {'있음' if r['annotated'] else '★없음'} |")
        n_same = sum(1 for r in all_rows if r["verdict"] == "동일")
        lines.append(f"\n(동일 판정 {n_same}건은 생략, 전체 대조 {len(all_rows)}건)")
        out.write_text("\n".join(lines), encoding="utf-8")
        print(f"\n[보고서] {out}")

    # 게이트: 인용부분차이 + 주석 없음 → exit 2
    bad = [r for r in all_rows if r["verdict"] == "인용부분차이" and not r["annotated"]]
    if args.code and bad:
        print(f"\n[게이트 실패] 인용 조문의 시제 드리프트 {len(bad)}건 — 레코드에 '입법 후속' 주석을 달기 전에는 커밋 금지")
        sys.exit(2)


if __name__ == "__main__":
    main()
