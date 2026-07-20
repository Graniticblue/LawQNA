#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_ordinance_registry.py -- 법령체계도(lsStmd) 기반 지역→조례 레지스트리 스냅샷

지역 조례 스캔·캐싱은 키워드 제목검색(8주제) 기반이라 명칭이 주제 어휘를
벗어나는 조례를 놓친다. 법령체계도는 내장 법령 가족에 매달린 전국 자치법규를
공식 열거하므로(건축법 하나에 1,100건), 이를 빌드타임 스냅샷으로 구워
런타임 스캔이 '해당 지역 × 우리 법령 가족' 후보를 레지스트리에서 보강한다.

원칙: API는 빌드타임 전용. 런타임(chainlit 스캔)은 registry JSON 조회 +
필요한 조례 '본문'만 기존 ordin 캐싱 경로로 취득.

출력: data/ordinance_registry.json
  {"_meta": {...}, "regions": {"남양주시": [{"name","mst","families":[법률...]}]}}

사용법: python scripts/build_ordinance_registry.py   # 전체 재수집·재구축
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
RAW_DIR = BASE_DIR / "data" / "law_cache" / "lsstmd"
OUT_PATH = BASE_DIR / "data" / "ordinance_registry.json"

# 코퍼스 28개 법령이 속한 가족의 '법률' 루트 (lsStmd는 법률 단위 족보)
FAMILY_ROOTS = [
    "건축법", "국토의 계획 및 이용에 관한 법률", "주택법", "도시 및 주거환경정비법",
    "건설산업기본법", "건설기술 진흥법", "건축물관리법",
    "소방시설 설치 및 관리에 관한 법률",
    "장애인ㆍ노인ㆍ임산부 등의 편의증진 보장에 관한 법률",
    "도로교통법", "주차장법", "공공주택 특별법",
]

_REGION_PAT = re.compile(
    r"^([가-힣]{2,8}(?:특별시|광역시|특별자치시|특별자치도|시|군|구|도))\s")


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8", errors="replace")


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


def extract_ordinances(node) -> list[dict]:
    """체계도 트리 전체에서 자치법규 기본정보를 재귀 수집."""
    out = []
    if isinstance(node, dict):
        bi = node.get("기본정보")
        if isinstance(bi, dict) and bi.get("자치법규명"):
            out.append({"name": re.sub(r"\s+", " ", bi["자치법규명"]).strip(),
                        "mst": str(bi.get("자치법규일련번호", ""))})
        for v in node.values():
            out.extend(extract_ordinances(v))
    elif isinstance(node, list):
        for x in node:
            out.extend(extract_ordinances(x))
    return out


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    # (조례명, mst) → families
    agg: dict[tuple, dict] = {}
    for root in FAMILY_ROOTS:
        mst = find_mst(root)
        if not mst:
            print(f"[SKIP] {root} — MST 미확인")
            continue
        try:
            raw = _get(f"http://www.law.go.kr/DRF/lawService.do?OC={OC}&target=lsStmd&type=JSON&MST={mst}")
        except Exception as e:
            print(f"[FAIL] {root} — {e}")
            continue
        safe = re.sub(r"[\\/:*?\"<>| ]", "", root)
        (RAW_DIR / f"{safe}.json").write_text(raw, encoding="utf-8")
        try:
            d = json.loads(raw)
        except Exception:
            print(f"[FAIL] {root} — JSON 파싱 실패 ({len(raw)}b)")
            continue
        ords = extract_ordinances(d.get("법령체계도", {}).get("상하위법", {}))
        uniq = {}
        for o in ords:
            if o["mst"]:
                uniq[(o["name"], o["mst"])] = o
        for k in uniq:
            e = agg.setdefault(k, {"name": k[0], "mst": k[1], "families": []})
            if root not in e["families"]:
                e["families"].append(root)
        print(f"[OK] {root}: 자치법규 {len(uniq)}건")

    regions: dict[str, list] = {}
    no_region = 0
    for e in agg.values():
        m = _REGION_PAT.match(e["name"] + " ")
        if not m:
            no_region += 1
            continue
        regions.setdefault(m.group(1), []).append(e)
    for r in regions:
        regions[r].sort(key=lambda x: (-len(x["families"]), x["name"]))

    out = {
        "_meta": {
            "built": date.today().isoformat(),
            "source": "law.go.kr DRF target=lsStmd (빌드타임 스냅샷 — 런타임 API 접근 없음)",
            "family_roots": FAMILY_ROOTS,
            "note": "법령 재수집 시 이 레지스트리도 재구축할 것 (build_delegation_graph와 동일 주기)",
        },
        "regions": regions,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(len(v) for v in regions.values())
    print(f"\n[빌드 완료] {OUT_PATH.name}: 지역 {len(regions)}개, 조례 {total}건 "
          f"(지역명 미해석 {no_region}건 제외)")
    ex = regions.get("남양주시", [])
    print(f"예시 — 남양주시 {len(ex)}건:", ", ".join(e["name"].replace("남양주시 ", "") for e in ex[:8]))


if __name__ == "__main__":
    main()
