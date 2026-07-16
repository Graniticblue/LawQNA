#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
convert_matrix_byeolpyo.py -- 매트릭스(박스 문자 표) 별표의 산문 변환 등재

박스 표는 임베딩·생성 양쪽에 독이라 build_byeolpyo_chunks가 보류한다
(matrix_보류목록.md). 이 스크립트는 사람과 컨펌한 변환(표 → 계층 산문)을
별표 단위로 등록해 두고, 원문에 적용한 뒤 확정 스플리터(호 단위)로 잘라
byeolpyo_chunks.jsonl에 등재한다.

변환 원칙 (2026-07-16 컨펌):
  * 표는 소속 위치(호·목)에 '인라인' — 예: 별표3 표1은 제3호 나목 아래
    1)·2)로 들어가 제3호가 한 청크로 유지된다 (소속 연결 보존).
  * 셀의 '-'는 해석하지 않고 '- (표 원문에 기간 미기재)'로 중립 표기.
  * 산문화 청크 끝에 '※ 원문은 표 형식(산문 변환본)' 표시 — 원문 아님 명시.
  * 표 이외 부분은 API 원문 그대로 (드리프트 안전).

사용법: python scripts/convert_matrix_byeolpyo.py          # 등록분 전체 적용
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).parent.parent
CACHE_DIR = BASE_DIR / "data" / "law_cache" / "byeolpyo"
ARTICLES = BASE_DIR / "data" / "raw_laws" / "all_articles.jsonl"
OUT_PATH = BASE_DIR / "data" / "raw_laws" / "byeolpyo" / "byeolpyo_chunks.jsonl"

spec = importlib.util.spec_from_file_location(
    "laf_ing", BASE_DIR / "ingest" / "ingest_law_from_api.py")
_m = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(BASE_DIR / "ingest"))
spec.loader.exec_module(_m)
split_byeolpyo = _m._split_byeolpyo

_BOX_BLOCK = re.compile(r"(?:^[ \t]*[┌├└─│┬┴┼┐┤┘][^\n]*\n?)+", re.M)
_MARK = "※ 원문은 표 형식(검색용 산문 변환본)"


def _flat(x) -> str:
    if isinstance(x, str):
        return x + "\n"
    if isinstance(x, list):
        return "".join(_flat(i) for i in x)
    if isinstance(x, dict):
        return "".join(_flat(v) for v in x.values())
    return ""


# ── 변환 레지스트리 ──────────────────────────────────────
# (법령명, 별표번호) → [(앵커 정규식, 산문 대체 텍스트), ...]
# 앵커는 '표 직전 문맥 + 박스 블록'을 통째로 잡아 소속 위치를 보존한다.

CONVERSIONS: dict[tuple[str, str], list[tuple[str, str]]] = {
    ("주택법 시행령", "3"): [
        # 표1 — 제3호 나목(위축지역) 소속: 나목 문장에 이어 1)·2)로 인라인
        (r"나\.\s*위축지역\(법 제63조의2제1항제2호에 해당하는 조정대상지역을 말한다\)\s*\n" +
         _BOX_BLOCK.pattern,
         "나. 위축지역(법 제63조의2제1항제2호에 해당하는 조정대상지역을 말한다): 다음의 구분에 따른 기간\n"
         " 1) 공공택지에서 건설ㆍ공급되는 주택: 6개월\n"
         " 2) 공공택지 외의 택지에서 건설ㆍ공급되는 주택: - (표 원문에 기간 미기재)\n"),
        # 표2 — 제5호 소속: 호 도입문에 이어 가·나목 계층으로 인라인
        (_BOX_BLOCK.pattern,
         "가. 수도권: 다음의 구분에 따른 기간\n"
         " 1) 「수도권정비계획법」 제6조제1항제1호에 따른 과밀억제권역: 1년\n"
         " 2) 「수도권정비계획법」 제6조제1항제2호 및 제3호에 따른 성장관리권역 및 자연보전권역: 6개월\n"
         "나. 수도권 외의 지역: 다음의 구분에 따른 기간\n"
         " 1) 광역시 중 「국토의 계획 및 이용에 관한 법률」 제36조제1항제1호에 따른 도시지역: 6개월\n"
         " 2) 그 밖의 지역: - (표 원문에 기간 미기재)\n"),
    ],
    ("건설기술 진흥법 시행령", "1"): [
        # 제3호 표 — 직무분야(가~차) → 전문분야 매핑: 행 단위 산문 (원문 번호체계 보존,
        # 고정폭 렌더링으로 붙은 항목 경계·'용 접' 패딩 공백 복원)
        (r"3\.\s*건설기술인의 직무분야 및 전문분야\s*\n" +
         r"(?:^[ \t]*[┌├└─│┬┴┼┐┤┘][^\n]*\n?)+",
         "3. 건설기술인의 직무분야 및 전문분야: 직무분야별 전문분야는 다음의 구분에 따른다.\n"
         " 가. 기계: 1) 공조냉동 및 설비 2) 건설기계 3) 용접 4) 승강기 5) 일반기계\n"
         " 나. 전기ㆍ전자: 1) 철도신호 2) 건축전기설비 3) 산업계측제어\n"
         " 다. 토목: 1) 토질ㆍ지질 2) 토목구조 3) 항만 및 해안 4) 도로 및 공항 5) 철도ㆍ삭도"
         " 6) 수자원개발 7) 상하수도 8) 농어업토목 9) 토목시공 10) 토목품질관리"
         " 11) 측량 및 지형공간정보 12) 지적\n"
         " 라. 건축: 1) 건축구조 2) 건축기계설비 3) 건축시공 4) 실내건축 5) 건축품질관리 6) 건축계획ㆍ설계\n"
         " 마. 광업: 1) 화약류관리 2) 광산보안\n"
         " 바. 도시ㆍ교통: 1) 도시계획 2) 교통\n"
         " 사. 조경: 1) 조경계획 2) 조경시공관리\n"
         " 아. 안전관리: 1) 건설안전 2) 소방 3) 가스 4) 비파괴검사\n"
         " 자. 환경: 1) 대기관리 2) 수질관리 3) 소음진동 4) 폐기물처리 5) 자연환경 6) 토양환경 7) 해양\n"
         " 차. 건설지원: 1) 건설금융ㆍ재무 2) 건설기획 3) 건설마케팅 4) 건설정보처리\n"),
    ],
}


def law_meta() -> dict:
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


def convert_one(law_name: str, byeolpyo_no: str) -> list[dict]:
    metas = law_meta()
    basic = metas[law_name]
    safe = re.sub(r"[\\/:*?\"<>| ]", "", law_name)
    units = json.loads((CACHE_DIR / f"{safe}.json").read_text(encoding="utf-8"))
    unit = None
    for u in units:
        no = str(u.get("별표번호", "")).lstrip("0") or "0"
        gaji = str(u.get("별표가지번호", "") or "").lstrip("0")
        if (f"{no}의{gaji}" if gaji else no) == byeolpyo_no:
            unit = u
            break
    assert unit, f"{law_name} 별표{byeolpyo_no} 캐시에 없음"

    title = _flat(unit.get("별표제목")).strip()
    raw = _flat(unit.get("별표내용"))
    text = re.sub(r"[ \t]{2,}", " ", raw)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    for pat, repl in CONVERSIONS[(law_name, byeolpyo_no)]:
        new_text, n = re.subn(pat, repl, text, count=1, flags=re.M)
        assert n == 1, f"앵커 미적중: {pat[:60]}"
        text = new_text
    assert not _BOX_BLOCK.search(text), "박스 문자 잔존 — 변환 미완"

    m = re.search(r"\((제\d+조[^)]*)\s*관련\)", title)
    related = m.group(1).strip() if m else ""
    title_clean = re.sub(r"\([^)]*관련\)", "", title).strip()
    spaceless = re.sub(r"[\s·ㆍ]+", "", law_name)

    def _norm(s):
        return re.sub(r"\s+", "", s)

    raw_norm = _norm(raw)
    records = []
    for seq, (section, chunk) in enumerate(split_byeolpyo(text), 1):
        # 변환 내용이 포함된 청크(원문에 없는 텍스트)에만 산문 변환 표시 부착
        converted = _norm(chunk) not in raw_norm
        body = chunk + ("\n" + _MARK if converted else "")
        records.append({
            "law_id":           f"{basic['law_id']}_별표{byeolpyo_no}",
            "law_name":         law_name,
            "law_type":         basic["law_type"],
            "article_no":       f"별표{byeolpyo_no}",
            "article_title":    title_clean,
            "content":          body,
            "enforcement_date": basic["enforcement_date"],
            "source_url":       f"https://www.law.go.kr/법령/{spaceless}/별표{byeolpyo_no}",
            "is_byeolpyo":      True,
            "byeolpyo_no":      byeolpyo_no,
            "related_article":  related,
            "chunk_seq":        seq,
            "section_title":    section,
            "matrix_converted": True,
        })
    return records


def main():
    all_new = []
    for (law, no) in CONVERSIONS:
        recs = convert_one(law, no)
        all_new.append(((law, no), recs))
        print(f"[변환] {law} 별표{no} → {len(recs)}청크")
        for r in recs:
            print(f"   - [{r['section_title'][:44]}] {len(r['content'])}자")

    # 기존 파일에서 동일 (법령, 별표) 행 제거 후 추가
    rows = [json.loads(l) for l in open(OUT_PATH, encoding="utf-8") if l.strip()]
    keys = {(law, f"별표{no}") for (law, no), _ in all_new}
    rows = [r for r in rows if (r["law_name"], r["article_no"]) not in keys]
    for _, recs in all_new:
        rows.extend(recs)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[등재] byeolpyo_chunks.jsonl 총 {len(rows)}청크")


if __name__ == "__main__":
    main()
