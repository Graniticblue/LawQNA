#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_byeolpyo_chunks.py -- 별표 청크 일괄 재생성 (컨펌된 전략, 2026-07-16)

전략(사용자 컨펌): 호 단위 개별 청크 + 1,200자 초과 호는 목 경계 하위 분할
+ 인덱서 헤더 프리픽스(기존 02_Indexer_BASE가 부착). 매트릭스표(박스 문자)는
이번 라운드 보류 — 별도 로그로 남겨 다음 라운드에 개별 협의.

입력: data/law_cache/byeolpyo/*.json (collect_byeolpyo.py 산출 — 현행판)
출력: data/raw_laws/byeolpyo/byeolpyo_chunks.jsonl (전량 교체)
부수: data/raw_laws/all_articles.jsonl에서 별표 유사-조문 행 제거
      (구 스크립트들이 넣은 109행 — 인덱서 조문 분기가 is_byeolpyo=false로
      하드코딩해 별표 exact-fetch에 안 걸리던 버그의 근본 정리)

사용법: python scripts/build_byeolpyo_chunks.py
"""
import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).parent.parent
CACHE_DIR = BASE_DIR / "data" / "law_cache" / "byeolpyo"
ARTICLES = BASE_DIR / "data" / "raw_laws" / "all_articles.jsonl"
OUT_PATH = BASE_DIR / "data" / "raw_laws" / "byeolpyo" / "byeolpyo_chunks.jsonl"
SKIP_LOG = BASE_DIR / "data" / "raw_laws" / "byeolpyo" / "matrix_보류목록.md"

_BOX = "─│┼┬┴├┤┌┐└┘═║"

# 스플리터는 API 인제스트 파이프라인과 단일 소스 공유
spec = importlib.util.spec_from_file_location(
    "laf_ing", BASE_DIR / "ingest" / "ingest_law_from_api.py")
_m = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(BASE_DIR / "ingest"))
spec.loader.exec_module(_m)
split_byeolpyo = _m._split_byeolpyo


def _flat(x) -> str:
    if isinstance(x, str):
        return x + "\n"
    if isinstance(x, list):
        return "".join(_flat(i) for i in x)
    if isinstance(x, dict):
        return "".join(_flat(v) for v in x.values())
    return ""


def law_meta() -> dict:
    """all_articles에서 법령별 (law_id, law_type, enforcement_date) 회수."""
    meta = {}
    with open(ARTICLES, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            n = r.get("law_name")
            if n and n not in meta:
                meta[n] = {"law_id": r.get("law_id", ""),
                           "law_type": r.get("law_type", ""),
                           "enforcement_date": r.get("enforcement_date", "")}
    return meta


def main():
    metas = law_meta()
    records, skipped_matrix, skipped_img = [], [], 0
    per_law = Counter()
    for fp in sorted(CACHE_DIR.glob("*.json")):
        units = json.loads(fp.read_text(encoding="utf-8"))
        law_name = None
        for u in units:
            # 법령명은 캐시 파일명(무공백)으로 역추적하지 않고 meta 대조로 확정
            pass
        # 파일명 → 법령명 매칭 (무공백 비교)
        stem = fp.stem
        for n in metas:
            if re.sub(r"[\s·ㆍ]+", "", n) == re.sub(r"[\s·ㆍ]+", "", stem):
                law_name = n
                break
        if not law_name:
            print(f"[SKIP] {fp.name} — 코퍼스 법령 매칭 실패")
            continue
        basic = metas[law_name]
        spaceless = re.sub(r"[\s·ㆍ]+", "", law_name)
        for u in units:
            if u.get("별표구분") != "별표":
                continue  # 서식 등 제외 (별표구분 필드가 권위 있는 분류)
            no = str(u.get("별표번호", "")).lstrip("0") or "0"
            gaji = str(u.get("별표가지번호", "") or "").lstrip("0")
            byeolpyo_no = f"{no}의{gaji}" if gaji else no
            title = _flat(u.get("별표제목")).strip()
            raw = _flat(u.get("별표내용"))
            text = re.sub(r"[ \t]{2,}", " ", raw)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            if len(text) < 30:
                skipped_img += 1
                continue
            if sum(text.count(ch) for ch in _BOX) > 30:
                skipped_matrix.append((law_name, f"별표{byeolpyo_no}", title[:50], len(text)))
                continue  # 매트릭스표 — 다음 라운드 개별 협의
            m = re.search(r"\((제\d+조[^)]*)\s*관련\)", title)
            related = m.group(1).strip() if m else ""
            title_clean = re.sub(r"\([^)]*관련\)", "", title).strip()
            for seq, (section, chunk) in enumerate(split_byeolpyo(text), 1):
                records.append({
                    "law_id":           f"{basic['law_id']}_별표{byeolpyo_no}",
                    "law_name":         law_name,
                    "law_type":         basic["law_type"],
                    "article_no":       f"별표{byeolpyo_no}",
                    "article_title":    title_clean,
                    "content":          chunk,
                    "enforcement_date": basic["enforcement_date"],
                    "source_url":       f"https://www.law.go.kr/법령/{spaceless}/별표{byeolpyo_no}",
                    "is_byeolpyo":      True,
                    "byeolpyo_no":      byeolpyo_no,
                    "related_article":  related,
                    "chunk_seq":        seq,
                    "section_title":    section,
                })
            per_law[law_name] += 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # all_articles의 별표 유사-조문 행 제거
    kept, removed = [], 0
    with open(ARTICLES, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            if "별표" in str(json.loads(line).get("article_no", "")):
                removed += 1
                continue
            kept.append(line.rstrip("\n"))
    if removed:
        ARTICLES.write_text("\n".join(kept) + "\n", encoding="utf-8")

    lines = ["# 매트릭스표 보류 목록 (박스 문자 표 — 다음 라운드 개별 협의)", ""]
    for law, no, t, ln in skipped_matrix:
        lines.append(f"- {law} {no}: {t} ({ln:,}자)")
    SKIP_LOG.write_text("\n".join(lines), encoding="utf-8")

    lens = [len(r["content"]) for r in records]
    print(f"[완료] 별표 {sum(per_law.values())}개 → 청크 {len(records)}개 "
          f"(길이 중앙 {sorted(lens)[len(lens)//2]} / 최대 {max(lens)})")
    for k, v in per_law.most_common():
        print(f"  {v:>3}별표  {k}")
    print(f"[보류] 매트릭스표 {len(skipped_matrix)}개 → {SKIP_LOG.name} / 이미지 전용 {skipped_img}개 스킵")
    print(f"[정리] all_articles 별표 유사-조문 {removed}행 제거")


if __name__ == "__main__":
    main()
