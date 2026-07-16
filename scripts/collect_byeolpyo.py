#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
collect_byeolpyo.py -- 내장 법령 별표 전량 수집 + 유형 서베이 (파싱 전 단계)

별표는 유형이 이질적(분류표·기준표·서술형·서식)이라 일괄 인젝션 대신
유형별 파싱 전략을 사람과 컨펌한 뒤 인덱싱한다. 이 스크립트는 그 1라운드:
  ① 현행판 법령 JSON에서 별표 노드 전량 추출 → data/law_cache/byeolpyo/ 보존
  ② 유형 추정·크기·인용 우선순위 서베이 → data/ingest_reports/별표_서베이_*.md

사용법: python scripts/collect_byeolpyo.py
"""
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
RAW_DIR = BASE_DIR / "data" / "law_cache" / "byeolpyo"
REPORT_DIR = BASE_DIR / "data" / "ingest_reports"

# eval·드리프트 스캔이 누락으로 지목한 별표 (우선순위 표기용)
PRIORITY = {
    ("건축법 시행령", "별표1"): "20-0156·21-0347·25-0061·25-0853 (4건)",
    ("국토의 계획 및 이용에 관한 법률 시행령", "별표5"): "17-0129",
    ("국토의 계획 및 이용에 관한 법률 시행령", "별표10"): "25-0853, 12-0442(후보)",
    ("주택법 시행령", "별표3"): "14-0405",
    ("건설기술 진흥법 시행령", "별표1"): "14-0498",
    ("건설기술 진흥법 시행규칙", "별표2"): "14-0498",
    ("건축법 시행령", "별표1의2"): "19-0365 (용도 분류 연관)",
}


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8", errors="replace")


def corpus_laws() -> list[str]:
    laws = []
    with open(ARTICLES, encoding="utf-8") as f:
        for line in f:
            n = json.loads(line).get("law_name", "")
            if n and n not in laws:
                laws.append(n)
    return sorted(laws)


def find_mst(law_name: str) -> str | None:
    q = urllib.parse.quote(law_name)
    js = json.loads(_get(
        f"http://www.law.go.kr/DRF/lawSearch.do?OC={OC}&target=law&type=JSON&query={q}&display=50"))
    items = js.get("LawSearch", {}).get("law", [])
    if isinstance(items, dict):
        items = [items]
    for it in items:
        if re.sub(r"\s+", "", it.get("법령명한글", "")) == re.sub(r"\s+", "", law_name):
            return it.get("법령일련번호")
    return None


def _flat_text(x) -> str:
    if isinstance(x, str):
        return x + "\n"
    if isinstance(x, list):
        return "".join(_flat_text(i) for i in x)
    if isinstance(x, dict):
        return "".join(_flat_text(v) for v in x.values())
    return ""


def guess_type(title: str, text: str) -> str:
    """유형 추정 휴리스틱 — 논의용 1차 분류일 뿐, 컨펌 대상."""
    t = title.replace(" ", "")
    if re.search(r"서식|신청서|신고서|통지서|확인서|대장|증명|표지", t):
        return "서식(양식)"
    if re.search(r"과태료|수수료|이행강제금", t):
        return "제재·요율표"
    body = text[:4000]
    num_items = len(re.findall(r"(?m)^\s*\d{1,2}\.", body))
    depth = len(re.findall(r"(?m)^\s*[가-하]\.", body))
    pipes = body.count("|") + body.count("│") + body.count("┃")
    if pipes > 20:
        return "매트릭스표"
    if num_items >= 5 and depth >= 3:
        return "분류목록형"
    if num_items >= 3:
        return "기준목록형"
    return "서술형"


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for law in corpus_laws():
        mst = find_mst(law)
        if not mst:
            print(f"[SKIP] {law} — MST 미확인")
            continue
        raw = _get(f"http://www.law.go.kr/DRF/lawService.do?OC={OC}&target=law&type=JSON&MST={mst}")
        d = json.loads(raw)
        node = d.get("법령", {}).get("별표", {})
        units = node.get("별표단위") or []
        if isinstance(units, dict):
            units = [units]
        safe = re.sub(r"[\\/:*?\"<>| ]", "", law)
        if units:
            (RAW_DIR / f"{safe}.json").write_text(
                json.dumps(units, ensure_ascii=False, indent=1), encoding="utf-8")
        for u in units:
            no = str(u.get("별표번호", "")).lstrip("0") or "?"
            branch = str(u.get("별표가지번호", "") or "").lstrip("0")
            label = f"별표{no}" + (f"의{branch}" if branch else "")
            title = str(u.get("별표제목") or "").strip()
            content = _flat_text(u.get("별표내용", ""))
            hwp = bool(u.get("별표서식파일링크") or u.get("별표HWP파일명"))
            kind = str(u.get("별표구분") or "")
            rows.append({
                "law": law, "label": label, "title": title, "kind": kind,
                "len": len(content), "lines": content.count("\n"),
                "type": guess_type(title, content), "hwp": hwp,
                "priority": PRIORITY.get((law, label), ""),
            })
        print(f"[OK] {law}: 별표 {len(units)}개")

    rows.sort(key=lambda r: (r["priority"] == "", r["law"], r["label"]))
    REPORT_DIR.mkdir(exist_ok=True)
    out = REPORT_DIR / f"별표_서베이_{date.today().isoformat()}.md"
    lines = [f"# 별표 서베이 ({date.today().isoformat()}) — 파싱 전략 논의용",
             "",
             "원본: data/law_cache/byeolpyo/ (법령별 JSON). 유형은 휴리스틱 1차 추정 — 컨펌 대상.",
             "",
             "| 우선순위(누락 지목) | 법령 | 별표 | 제목 | 유형 추정 | 크기 | 구분 |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['priority']} | {r['law']} | {r['label']} | {r['title'][:40]} "
                     f"| {r['type']} | {r['len']:,}자/{r['lines']}줄 | {r['kind']} |")
    from collections import Counter
    dist = Counter(r["type"] for r in rows)
    lines.append("\n## 유형 분포\n")
    for k, v in dist.most_common():
        lines.append(f"- {k}: {v}개")
    lines.append(f"\n총 {len(rows)}개 별표 / {sum(r['len'] for r in rows):,}자")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[서베이] {out}")
    print("유형 분포:", dict(dist))


if __name__ == "__main__":
    main()
