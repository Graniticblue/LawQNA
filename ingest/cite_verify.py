# -*- coding: utf-8 -*-
"""cite_verify.py -- 답변 속 판례·해석례 인용의 실존 검증 (허위사실 판명 전용)

운영 원칙:
  * 답변 생성은 학습 코퍼스만 사용한다. 이 모듈은 생성이 끝난 뒤(비차단)
    답변에 등장한 번호 중 '코퍼스 밖 잔여분'만 검증한다.
  * API 호출 최소화: 학습 대장 → 검증 캐시 → (미스만) API 순서.
    캐시는 chroma 볼륨(_cite_verify/)에 영속 — 같은 번호는 두 번 묻지 않는다.
  * '미확인'은 허위 단정이 아니다 — 판례 DB(약 17만건)는 전수가 아니므로
    미간행 가능성이 있고, 시맨틱은 '존재 보증 불가 → 인용 보류 권장'이다.
  * 실존하지만 미학습인 번호는 학습 후보 큐(queue.json)에 적재된다.
    큐는 서버 전역(전 사용자 공용)이며 UI에 노출하지 않는다 — 운영자가
    파일로 확인해 선별 학습 대상을 고른다.
"""
import json
import os
import re
import threading
from datetime import date
from pathlib import Path

import requests

BASE_DIR = Path(__file__).parent.parent
_CHROMA_PATH = Path(os.environ.get("CHROMA_DB_PATH", str(BASE_DIR / "data" / "chroma_db")))
VERIFY_DIR = _CHROMA_PATH / "_cite_verify"
CACHE_PATH = VERIFY_DIR / "cache.json"
QUEUE_PATH = VERIFY_DIR / "queue.json"

OC = "duncan9823"
SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
API_TIMEOUT = 8

_lock = threading.Lock()
_learned: set | None = None

# 판례 사건번호: 연도(2~4자리) + 사건부호 + 일련번호. 부호는 도메인에서 등장하는
# 것으로 한정해 오탐(연도 범위, 조문 번호 등)을 줄인다.
_PREC_RE = re.compile(
    r"\b(\d{2,4}(?:두|누|다|도|나|마|므|허|후|구합|구단|고단|고합|노|오|재다|재두)\d{1,7})\b")
# 해석례 안건번호: XX-XXXX — 숫자 범위 오탐 방지를 위해 주변 문맥 단어를 요구.
_EXPC_RE = re.compile(r"\b(\d{2}-\d{4})\b")
_EXPC_CTX = re.compile(r"법제처|해석례|안건|회신|질의")


def _load_learned() -> set:
    """학습 대장: court_cases의 case_id + qa_precedents의 해석례 안건번호."""
    global _learned
    if _learned is not None:
        return _learned
    codes = set()
    try:
        for p in (BASE_DIR / "data" / "court_cases").glob("*.jsonl"):
            for line in open(p, encoding="utf-8"):
                if line.strip():
                    codes.add(json.loads(line).get("case_id", ""))
    except Exception:
        pass
    try:
        for p in (BASE_DIR / "data" / "qa_precedents").rglob("*.jsonl"):
            m = re.search(r"법제처_(\d{2}-\d{4})", p.name)
            if m:
                codes.add(m.group(1))
    except Exception:
        pass
    codes.discard("")
    _learned = codes
    return codes


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def extract_citations(text: str) -> list[dict]:
    """답변 텍스트에서 판례·해석례 번호 추출 (중복 제거, 등장 순서 유지)."""
    out, seen = [], set()
    for m in _PREC_RE.finditer(text):
        num = m.group(1)
        if num not in seen:
            seen.add(num)
            out.append({"kind": "prec", "num": num})
    for m in _EXPC_RE.finditer(text):
        num = m.group(1)
        if num in seen:
            continue
        ctx = text[max(0, m.start() - 30): m.end() + 10]
        if _EXPC_CTX.search(ctx):
            seen.add(num)
            out.append({"kind": "expc", "num": num})
    return out


def _api_lookup(kind: str, num: str) -> dict:
    """단건 API 조회 → {status, name, date, court}. 실패 시 status='error'."""
    target = "prec" if kind == "prec" else "expc"
    try:
        r = requests.get(SEARCH_URL, params={
            "OC": OC, "target": target, "type": "JSON",
            "query": num, "display": 20}, timeout=API_TIMEOUT)
        root = r.json()
        items = root[list(root.keys())[0]].get(target) or []
        if isinstance(items, dict):
            items = [items]
        for it in items:
            key = "사건번호" if kind == "prec" else "안건번호"
            if str(it.get(key, "")).replace(" ", "").endswith(num):
                if kind == "prec":
                    return {"status": "exists",
                            "name": str(it.get("사건명", ""))[:60],
                            "date": str(it.get("선고일자", "")),
                            "court": str(it.get("법원명", ""))}
                return {"status": "exists",
                        "name": str(it.get("안건명", ""))[:60],
                        "date": str(it.get("회신일자", "")),
                        "court": "법제처"}
        return {"status": "unverified"}
    except Exception:
        return {"status": "error"}


def _enqueue(kind: str, num: str, meta: dict, snippet: str) -> None:
    """실존·미학습 번호를 학습 후보 큐에 적재 (전역, 등장 횟수 누적)."""
    with _lock:
        q = _read_json(QUEUE_PATH)
        ent = q.get(num) or {"kind": kind, "first": str(date.today()),
                             "count": 0, "name": meta.get("name", ""),
                             "date": meta.get("date", ""), "snippets": []}
        ent["count"] += 1
        ent["last"] = str(date.today())
        if snippet and snippet not in ent["snippets"]:
            ent["snippets"] = (ent["snippets"] + [snippet])[-3:]
        q[num] = ent
        _write_json(QUEUE_PATH, q)


def check_answer(answer_text: str, question_snippet: str = "") -> list[dict]:
    """답변 인용 검증 (동기 — 호출측에서 to_thread 권장).

    반환: 코퍼스 밖 잔여분의 검증 결과 리스트.
      {kind, num, status: exists|unverified|error, name?, date?, court?, queued?}
    코퍼스(학습 대장) 인용만 있으면 빈 리스트 — 배지 표시 불필요.
    """
    cites = extract_citations(answer_text)
    if not cites:
        return []
    learned = _load_learned()
    residual = [c for c in cites if c["num"] not in learned]
    if not residual:
        return []

    snippet = (question_snippet or "").strip().replace("\n", " ")[:60]
    with _lock:
        cache = _read_json(CACHE_PATH)
    results, dirty = [], False
    for c in residual:
        num = c["num"]
        hit = cache.get(num)
        if hit and hit.get("status") in ("exists", "unverified"):
            meta = dict(hit)
        else:
            meta = _api_lookup(c["kind"], num)
            if meta["status"] in ("exists", "unverified"):
                cache[num] = {**meta, "kind": c["kind"], "checked": str(date.today())}
                dirty = True
        entry = {"kind": c["kind"], "num": num, **meta}
        if meta.get("status") == "exists":
            _enqueue(c["kind"], num, meta, snippet)
            entry["queued"] = True
        results.append(entry)
    if dirty:
        with _lock:
            merged = _read_json(CACHE_PATH)
            merged.update(cache)
            _write_json(CACHE_PATH, merged)
    return results


def format_badge(results: list[dict]) -> str:
    """검증 결과 → 배지 메시지 본문 (⚠ 포함 여부와 무관하게 전체 렌더)."""
    lines = ["🔎 **인용 검증** — 학습 자료 밖 인용 %d건" % len(results)]
    for r in results:
        num, kind = r["num"], r["kind"]
        label = "판례" if kind == "prec" else "법제처 해석례"
        if r["status"] == "exists":
            d = r.get("date", "")
            d = f"{d[:4]}.{d[4:6]}.{d[6:8]}." if len(d) == 8 else d
            lines.append(f"- `{num}` ✓ 실존 확인 — {r.get('court','')} {d} {r.get('name','')}"
                         f" *(학습 후보 등록)*")
        elif r["status"] == "unverified":
            lines.append(f"- `{num}` ⚠ {label} DB에서 미확인 — 미간행 가능성이 있어 존재를 "
                         f"보증할 수 없습니다. **인용 보류 권장** (재생성 시 자동 제외)")
        else:
            lines.append(f"- `{num}` ⏳ 일시 검증 불가(API) — 다음 답변에서 재시도")
    return "\n".join(lines)


def regen_block(results: list[dict]) -> str:
    """⚠ 미확인 번호 → 재생성 주입 블록 (없으면 빈 문자열)."""
    bad = [r["num"] for r in results if r["status"] == "unverified"]
    if not bad:
        return ""
    return ("=== [인용 검증 결과 — 재생성 지시] ===\n"
            "다음 번호는 실존이 확인되지 않았다. 재생성 답변에서 이 번호를 인용하지 말 것. "
            "해당 논지는 번호 인용 없이 법리로만 서술하거나 삭제할 것:\n- "
            + "\n- ".join(bad))
