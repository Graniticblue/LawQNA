# -*- coding: utf-8 -*-
"""curate_lib.py — 학습 레코드 큐레이션의 '얇은 헬퍼'.

레코드를 생성하지 않는다(생성·판단은 매 사안마다 사람/LLM이 한다). 이 모듈은
반복되는 기계적 골격만 담당한다 — 문단 무결성, 스키마 검증, manifest 등재,
doctrine·시제 주석 린트. 2026-07-20 세션에서 실제로 발생한 실수를 정확히 막는
것이 목적:
  - legal_logic을 str로 넣어 make_ingest_report가 AttributeError로 깨짐(16-0128)
  - manifest count 손계산(매 트랙)
  - 시제 주석을 '시제 자구'로 써서 게이트 키워드 불일치로 재실행(20-0008)
  - 문단 분할 경계 오류(전 트랙 assert로 방어하던 것)

사용법(예):
    from scripts import curate_lib as cl
    parts = cl.split_paragraphs(이유, bounds)          # 무결성 assert 내장
    cl.validate_expc_record(rec)                        # 스키마 위반 시 raise
    cl.register_manifest(MANIFEST, "법제처_23-0538.jsonl", len(parts)+1)
"""
from __future__ import annotations
import json
import re
from pathlib import Path

# ── 다른 모듈과 동기화해야 하는 상수 (변경 시 함께 고칠 것) ──────────
# 06_Generator._DOCTRINE_STOP 과 동일해야 한다.
DOCTRINE_STOP = {"적용", "제한", "규정", "법률", "요건", "해석",
                 "금지", "판단", "기준", "경우", "여부"}
# check_temporal_drift.py 의 annotated 키워드와 동일해야 한다.
TEMPORAL_KEYWORDS = ("입법 후속", "시제 주의", "입법적 실현", "입법 실현",
                     "현행법 질의", "신설로 실현", "명문 허용", "개정으로 신설")
POSITIONS = set("RMABXL")           # 복합 표기(R+M, A+B) 허용 — 토큰 단위 검사
SCOPES = {"도메인", "횡단"}


class CurateError(ValueError):
    """스키마·무결성 위반 — 커밋 전에 반드시 고쳐야 하는 결함."""


# ── 1. 문단 분할 + 무결성 ────────────────────────────────────────
def split_paragraphs(body: str, bounds: list[str]) -> list[str]:
    """경계 문구 리스트로 body를 분할하고 무결성을 assert한다.

    bounds는 각 문단의 '시작 문구'(원문에 정확히 1회 등장). 반환 parts를
    이어붙이면 body와 정확히 일치해야 한다(누락·중복 없음)."""
    idx = [0]
    for b in bounds:
        pos = body.find(b)
        if pos < 0:
            raise CurateError(f"경계 문구 미발견: {b[:40]!r}")
        if body.find(b, pos + 1) >= 0:
            raise CurateError(f"경계 문구 중복 등장: {b[:40]!r}")
        idx.append(pos)
    idx.append(len(body))
    if idx != sorted(idx):
        raise CurateError(f"경계 순서 오류: {idx}")
    parts = [body[idx[i]:idx[i + 1]] for i in range(len(idx) - 1)]
    if "".join(parts) != body:
        raise CurateError("문단 무결성 실패 — 이어붙인 결과가 원문과 불일치")
    return parts


# ── 2. doctrine 린트 ────────────────────────────────────────────
def lint_doctrine(doctrine: dict) -> list[str]:
    """판례 doctrine 블록 검증. 치명 결함은 raise, 권고는 경고 리스트로 반환."""
    if not isinstance(doctrine, dict):
        raise CurateError("doctrine이 dict가 아님")
    for k in ("position", "series", "scope", "doctrine_terms"):
        if k not in doctrine:
            raise CurateError(f"doctrine 필수 키 누락: {k}")
    pos = str(doctrine["position"]).replace("+", "").replace(" ", "")
    if not pos or any(c not in POSITIONS for c in pos):
        raise CurateError(f"position 코드 오류: {doctrine['position']!r} (R/M/A/B/X/L 조합)")
    if doctrine["scope"] not in SCOPES:
        raise CurateError(f"scope 오류: {doctrine['scope']!r} (도메인|횡단)")
    terms = doctrine.get("doctrine_terms") or []
    if not isinstance(terms, list):
        raise CurateError("doctrine_terms가 list가 아님")
    warns: list[str] = []
    if doctrine["scope"] == "횡단":
        # 횡단인데 전 term이 불용어 토큰만이면 doctrine 경로가 오발화/미발화
        non_stop = [t for t in terms
                    if any(tok not in DOCTRINE_STOP
                           for tok in re.split(r"\s+", str(t)) if len(tok) >= 2)]
        if not non_stop:
            warns.append("scope=횡단인데 doctrine_terms가 전부 범용 토큰 — "
                         "법리 어휘 경로가 오발화하거나 안 걸린다")
        if not terms:
            warns.append("scope=횡단인데 doctrine_terms 비어 있음 — 법리 경로 미발화")
    return warns


# ── 3. 해석례 레코드 스키마 ──────────────────────────────────────
# doc_analysis는 구형 레코드(초기 학습분)엔 없어 필수에서 제외 — 있으면
# 형식만 강제(16-0128 방지), 없으면 신규 학습 리마인더로 경고.
_EXPC_REQUIRED = ("contents", "doc_code", "doc_date", "doc_ref",
                  "relation_type", "relation_name", "label_summary",
                  "paragraphs")


def validate_expc_record(rec: dict) -> list[str]:
    """해석례 레코드 검증. 치명 결함 raise, 권고 경고 반환."""
    for k in _EXPC_REQUIRED:
        if k not in rec:
            raise CurateError(f"해석례 필수 필드 누락: {k}")
    # contents 구조
    c = rec["contents"]
    if not (isinstance(c, list) and len(c) == 2
            and c[0].get("role") == "user" and c[1].get("role") == "model"):
        raise CurateError("contents는 [user, model] 2턴이어야 함")
    for turn in c:
        if not turn.get("parts") or "text" not in turn["parts"][0]:
            raise CurateError("contents parts[0].text 누락")
    # paragraphs
    for i, p in enumerate(rec["paragraphs"]):
        if "text" not in p or "gist" not in p:
            raise CurateError(f"paragraphs[{i}]에 text/gist 누락")
    # 날짜 형식 — 미상 자리표시(XX) 포함 시 데이터 결함
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(rec["doc_date"])):
        raise CurateError(f"doc_date 형식 오류: {rec['doc_date']!r} (YYYY-MM-DD)")
    warns: list[str] = []
    # doc_analysis.legal_logic 은 반드시 list[dict] (16-0128 AttributeError 방지)
    da = rec.get("doc_analysis")
    if da is None:
        warns.append("doc_analysis 없음 — 구형 스키마(신규 학습분엔 필요)")
    else:
        ll = da.get("legal_logic")
        if ll is not None:
            if not isinstance(ll, list):
                raise CurateError("doc_analysis.legal_logic은 list여야 함 "
                                  "(str이면 make_ingest_report가 깨짐 — 16-0128)")
            for i, step in enumerate(ll):
                if not isinstance(step, dict) or "title" not in step:
                    raise CurateError(f"legal_logic[{i}]는 dict(+title 키)여야 함")
        if "key_provisions" in da and not isinstance(da["key_provisions"], list):
            raise CurateError("doc_analysis.key_provisions는 list여야 함")
    if not rec.get("search_tags"):
        warns.append("search_tags 비어 있음")
    if not rec.get("logic_steps"):
        warns.append("logic_steps 비어 있음")
    # T3/T4(부처·지자체 회신)는 인용 표기 수동 지정 원칙(2026-07-21) —
    # 자동 생성 라벨이 비정형 doc_ref에서 깨지기 쉬움
    if str(rec.get("tier", "")) in ("T3", "T4") and not rec.get("cite_label"):
        warns.append("T3/T4 레코드에 cite_label 없음 — 인용 표기를 수동 지정할 것 "
                     "(예: '국토교통부 민원회신-서울특별시 2017.11.21.')")
    return warns


# ── 4. 판례 레코드 스키마 ────────────────────────────────────────
_CASE_REQUIRED = ("case_id", "court", "decision_date", "cited_laws_str",
                  "cited_articles", "relation_types", "relation_name",
                  "label_summary", "holding", "doctrine", "source_file")


def validate_case_record(rec: dict) -> list[str]:
    """판례 레코드 검증. 치명 결함 raise, 권고 경고 반환."""
    for k in _CASE_REQUIRED:
        if k not in rec:
            raise CurateError(f"판례 필수 필드 누락: {k}")
    if not isinstance(rec["cited_articles"], list):
        raise CurateError("cited_articles는 list여야 함")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(rec["decision_date"])):
        raise CurateError(f"decision_date 형식 오류: {rec['decision_date']!r}")
    exp_file = f"대법원_{rec['case_id']}.jsonl"
    # 전원합의체 등 court 접두 변형 허용 — case_id 포함만 확인
    if rec["case_id"] not in rec["source_file"]:
        raise CurateError(f"source_file에 case_id 불일치: {rec['source_file']!r}")
    return lint_doctrine(rec["doctrine"])


# (시제 주석 검증은 check_temporal_drift.py 게이트가 담당한다 — 인용 조문의
#  실제 드리프트 유무를 항·호 단위로 비교해 주석을 강제하므로, relation_name
#  텍스트만 보는 린트는 위양성이 많아 여기서 다루지 않는다.)


# ── 5. manifest 등재 ────────────────────────────────────────────
def register_manifest(manifest_path: str | Path, filename: str,
                      count: int, date: str = None) -> bool:
    """manifest.json의 indexed 목록에 파일을 등재(중복이면 skip). 등재 시 True."""
    manifest_path = Path(manifest_path)
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = m.setdefault("indexed", [])
    if any(e.get("file") == filename for e in entries):
        return False
    if date is None:
        from datetime import date as _d
        date = _d.today().isoformat()
    entries.append({"file": filename, "count": count, "date": date})
    manifest_path.write_text(json.dumps(m, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    return True


# ── self-test: 기존 코퍼스 전량 검증 (회귀 신뢰) ──────────────────
def _selftest() -> None:
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    base = Path(__file__).parent.parent / "data"
    expc_ok = case_ok = legacy = 0
    fails = []

    def _is_legacy_expc(rec: dict) -> bool:
        # 초기 학습분: doc_analysis 미도입 또는 doc_date 미채움
        return (rec.get("doc_analysis") is None
                or not str(rec.get("doc_date", "")).strip()
                or "X" in str(rec.get("doc_date", "")))

    for p in sorted((base / "qa_precedents" / "updates").glob("*.jsonl")):
        rec = json.loads(p.read_text(encoding="utf-8").strip().splitlines()[0])
        if _is_legacy_expc(rec):
            legacy += 1
            continue
        try:
            for msg in validate_expc_record(rec):
                print(f"  [warn] {p.name}: {msg}")
            expc_ok += 1
        except CurateError as e:
            fails.append((p.name, str(e)))
    for p in sorted((base / "court_cases").glob("*.jsonl")):
        rec = json.loads(p.read_text(encoding="utf-8").strip().splitlines()[0])
        try:
            for msg in validate_case_record(rec):
                print(f"  [warn] {p.name}: {msg}")
            case_ok += 1
        except CurateError as e:
            fails.append((p.name, str(e)))
    print(f"\n신규 스키마: 해석례 {expc_ok}건 / 판례 {case_ok}건 통과 · 레거시 {legacy}건 관용")
    if fails:
        print(f"\n★ 신규 스키마 위반 {len(fails)}건 (커밋 전 수정):")
        for name, err in fails:
            print(f"  - {name}: {err}")
    else:
        print("신규 스키마 위반 0 — 회귀 없음")


if __name__ == "__main__":
    _selftest()
