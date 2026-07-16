#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_delegation_graph.py -- 위임 그래프 구축 (법제처 lsDelegated 스냅샷)

위임 문구("대통령령으로 정하는", "국토교통부령으로 정하는")에는 조번호가 없어
텍스트 기반 crossref가 법→영→규칙 하향 체인을 따라갈 수 없다(16-0506 실증:
영 제25조③7호 → 규칙 제3조 누락). 법제처 DRF lsDelegated는 이 위임 링크를
조문 단위로 구조화해 제공하므로, 내장 법령 전체의 스냅샷을 받아
data/delegation_graph.json 으로 굽는다.

원칙: API는 빌드타임 전용. 런타임(05_Retriever)은 이 JSON과 로컬 DB만 사용.
원본 응답은 검수용으로 data/law_cache/delegation/ 에 보존한다.

사용법:
  python scripts/build_delegation_graph.py            # 전체 재수집·재구축
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
RAW_DIR = BASE_DIR / "data" / "law_cache" / "delegation"
OUT_PATH = BASE_DIR / "data" / "delegation_graph.json"


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def _first(v):
    """lsDelegated는 일부 필드를 병렬 리스트로 준다 — 대표값 하나로 축약."""
    if isinstance(v, list):
        return v[0] if v else ""
    return v or ""


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s or ""))


def _art_no(raw: str) -> str | None:
    """조문번호 '4' → '제4조', '25의2' → '제25조의2'. 미해석은 None."""
    raw = str(raw or "").strip()
    m = re.fullmatch(r"(\d+)(?:의(\d+))?", raw)
    if not m:
        return None
    return f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")


def corpus_laws() -> list[str]:
    laws = []
    with open(ARTICLES, encoding="utf-8") as f:
        for line in f:
            n = json.loads(line).get("law_name", "")
            if n and n not in laws:
                laws.append(n)
    return sorted(laws)


def find_mst(law_name: str) -> tuple[str, str] | None:
    """현행 법령의 (법령ID, MST). 법령명 정확 일치(공백 무시)."""
    q = urllib.parse.quote(law_name)
    js = json.loads(_get(
        f"http://www.law.go.kr/DRF/lawSearch.do?OC={OC}&target=law&type=JSON&query={q}&display=50"))
    items = js.get("LawSearch", {}).get("law", [])
    if isinstance(items, dict):
        items = [items]
    for it in items:
        if _norm(it.get("법령명한글")) == _norm(law_name):
            return it.get("법령ID", ""), it.get("법령일련번호", "")
    return None


def _family(law_name: str) -> dict[str, str] | None:
    """'OO법 (시행령)' → 같은 가족의 시행령·시행규칙 명칭. 법/법률 계열만."""
    base = re.sub(r"\s*시행(령|규칙)$", "", law_name).strip()
    if not (base.endswith("법") or base.endswith("법률")):
        return None
    return {"시행령": f"{base} 시행령", "시행규칙": f"{base} 시행규칙"}


def collect(law_name: str, lid: str, mst: str) -> list[dict]:
    """한 법령의 lsDelegated → 에지 리스트 (인용법령 제외, 제0조 제거).

    데이터 품질 폴백: 일부 행은 위임구분·위임법령제목이 null로 온다
    (예: 도시정비법 제50조① → 영 제46조). 라인텍스트의 '대통령령'/'부령'으로
    같은 가족의 시행령·시행규칙을 추론해 복원한다."""
    raw = _get(f"http://www.law.go.kr/DRF/lawService.do?OC={OC}&target=lsDelegated&type=JSON&MST={mst}")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[\\/:*?\"<>| ]", "", law_name)
    (RAW_DIR / f"{lid}_{safe}.json").write_text(raw, encoding="utf-8")

    d = json.loads(raw)
    node = d.get("lsDelegated", {}).get("법령", {})
    items = node.get("위임조문정보") or []
    if isinstance(items, dict):
        items = [items]

    edges = []
    for it in items:
        infos = it.get("위임정보") or []
        if isinstance(infos, dict):
            infos = [infos]
        for inf in infos:
            base_kind = _first(inf.get("위임구분"))
            base_law = re.sub(r"\s+", " ", str(_first(inf.get("위임법령제목")) or "")).strip()
            if base_kind == "인용법령":
                continue  # 인용 에지는 기존 텍스트 crossref가 담당 — 위임 하향만 수집
            arts = inf.get("위임법령조문정보") or []
            if isinstance(arts, dict):
                arts = [arts]
            for a in arts:
                dst_art = _art_no(a.get("위임법령조문번호"))
                if not dst_art:
                    continue  # '제0조' 등 링크 미해소 노이즈
                pos = str(a.get("조항호목") or "").strip()
                m = re.match(r"(제\d+조(의\d+)?)", pos)
                if not m:
                    continue
                phrase = str(a.get("라인텍스트") or "").strip()
                kind, dst_law = base_kind, base_law
                if not dst_law or not kind:
                    fam = _family(law_name)
                    if fam and "대통령령" in phrase:
                        kind, dst_law = "시행령", fam["시행령"]
                    elif fam and re.search(r"부령|총리령", phrase):
                        kind, dst_law = "시행규칙", fam["시행규칙"]
                    else:
                        continue  # 추론 불가 — 보수적으로 버림
                edges.append({
                    "src_article": m.group(1),
                    "src_pos": pos,
                    "dst_law": dst_law,
                    "dst_article": dst_art,
                    "kind": kind,
                    "phrase": phrase,
                })
    return edges


def main():
    laws = corpus_laws()
    corpus_norm = {_norm(l) for l in laws}
    graph: dict[str, list[dict]] = {}
    stats = []
    for law in laws:
        found = find_mst(law)
        if not found:
            print(f"[SKIP] {law} — 법령ID 미확인")
            continue
        lid, mst = found
        try:
            edges = collect(law, lid, mst)
        except Exception as e:
            print(f"[FAIL] {law} — {e}")
            continue
        # (src조, dst법령, dst조) 단위로 집계 — src_pos·phrase는 목록으로 보존
        agg: dict[tuple, dict] = {}
        for e in edges:
            k = (e["src_article"], e["dst_law"], e["dst_article"])
            g = agg.setdefault(k, {
                "dst_law": e["dst_law"], "dst_article": e["dst_article"],
                "kind": e["kind"], "in_corpus": _norm(e["dst_law"]) in corpus_norm,
                "src_pos": [], "phrase": [],
            })
            if e["src_pos"] not in g["src_pos"]:
                g["src_pos"].append(e["src_pos"])
            if e["phrase"] and e["phrase"] not in g["phrase"]:
                g["phrase"].append(e["phrase"])
        n_in = 0
        for (src_art, _, _), g in agg.items():
            graph.setdefault(f"{law}::{src_art}", []).append(g)
            n_in += g["in_corpus"]
        stats.append((law, len(agg), n_in))
        print(f"[OK] {law}: 에지 {len(agg)} (코퍼스 내 {n_in})")

    out = {
        "_meta": {
            "built": date.today().isoformat(),
            "source": "law.go.kr DRF target=lsDelegated (빌드타임 스냅샷 — 런타임 API 접근 없음)",
            "laws": [s[0] for s in stats],
            "note": "법령 재수집(개정) 시 이 스크립트로 위임 그래프도 재구축할 것",
        },
        "edges": graph,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(s[1] for s in stats)
    total_in = sum(s[2] for s in stats)
    print(f"\n[빌드 완료] {OUT_PATH.name}: 발원 조문 {len(graph)}개, 에지 {total}개 (코퍼스 내 {total_in})")


if __name__ == "__main__":
    main()
