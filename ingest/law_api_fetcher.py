"""
law_api_fetcher.py -- 법제처 Open API 실시간 조회 + 파일 캐시

전략:
  - law_hints에서 DB 미수록 법령 조문을 실시간 조회
  - 법령 전체 조문을 법령 단위로 캐시 (data/law_cache/{law_name}.json)
  - 같은 법령의 다른 조문 요청 시 추가 API 호출 없이 캐시에서 반환
  - 캐시 TTL: 30일

필요 환경변수 (.env):
  LAW_API_KEY=your_key_here  (법제처 Open API 키: https://www.law.go.kr/LSW/openApiInfo.do)
"""

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import requests

BASE_DIR  = Path(__file__).parent
CACHE_DIR = BASE_DIR / "data" / "law_cache"
CACHE_TTL_DAYS = 30

LAW_SEARCH_URL  = "https://www.law.go.kr/DRF/lawSearch.do"
LAW_ARTICLE_URL = "https://www.law.go.kr/DRF/lawService.do"


# ============================================================
# 힌트 파싱
# ============================================================

def parse_hint(hint: str) -> tuple[str, str]:
    """
    "건축기본법 제2조"        → ("건축기본법", "제2조")
    "도시정비법 제81조제1항"  → ("도시정비법", "제81조")
    힌트에 조문번호 없으면    → (hint, "")
    """
    m = re.search(r'(제\d+조)', hint)
    if m:
        article = m.group(1)
        law_name = hint[:hint.index(article)].strip()
        return law_name, article
    return hint.strip(), ""


# ============================================================
# 캐시 관리
# ============================================================

def _cache_path(law_name: str) -> Path:
    safe = re.sub(r'[\\/:*?"<>|]', '_', law_name)
    return CACHE_DIR / f"{safe}.json"


def _load_cache(law_name: str) -> dict | None:
    """캐시 파일 로드. TTL 초과 시 None 반환."""
    p = _cache_path(law_name)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    cached_at = datetime.fromisoformat(data.get("cached_at", "2000-01-01"))
    if datetime.now() - cached_at > timedelta(days=CACHE_TTL_DAYS):
        return None
    return data


def _save_cache(law_name: str, articles: dict[str, str]) -> None:
    """법령 전체 조문 캐시 저장. articles = {"제2조": "...", "제3조": "..."}"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(law_name).write_text(
        json.dumps({"cached_at": datetime.now().isoformat(), "articles": articles},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ============================================================
# 법제처 API 호출
# ============================================================

def _get_api_key() -> str:
    return os.getenv("LAW_API_KEY", "")


def _fetch_law_id(law_name: str) -> str | None:
    """법령명으로 법령ID 조회"""
    key = _get_api_key()
    if not key:
        return None
    try:
        r = requests.get(
            LAW_SEARCH_URL,
            params={"OC": key, "target": "law", "type": "JSON",
                    "query": law_name, "display": "5"},
            timeout=5,
        )
        data = r.json()
        laws = data.get("LawSearch", {}).get("law", [])
        if isinstance(laws, dict):
            laws = [laws]
        # 완전 일치 우선 — MST는 법령ID가 아닌 법령일련번호
        for law in laws:
            if law.get("법령명한글", "").strip() == law_name.strip():
                return law.get("법령일련번호", "")
        return laws[0].get("법령일련번호", "") if laws else None
    except Exception:
        return None


def _as_list(v):
    """API가 단건일 때 dict, 복수일 때 list로 주는 필드를 항상 list로 통일."""
    if v is None:
        return []
    return [v] if isinstance(v, dict) else v


def _as_text(v) -> str:
    """*내용 필드값을 안전하게 문자열로. 보통은 str이지만, 개정 이력이 겹친
    항목은 (중첩)리스트로 오기도 해서(예: 조문참고자료처럼) 재귀적으로 펼쳐 합친다."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, list):
        return "\n".join(t for t in (_as_text(x) for x in v) if t)
    return str(v).strip()


def _build_article_text(unit: dict) -> str:
    """조문단위 하나 → 완전한 조문 텍스트(제목+본문).

    법제처 API는 항(①②③)이 여러 개인 조문일 경우 최상위 조문내용에는
    "제34조(직통계단의 설치)"처럼 제목만 담고, 실제 본문은 항[].항내용
    (중첩된 호[].호내용, 목[].목내용)에 따로 담아 내려준다. 조문내용만
    읽으면 다항 조문 본문이 통째로 누락되므로 항/호/목을 재귀적으로 이어붙인다.
    (단문 조문은 항 자체가 없고 조문내용에 전체가 들어있어 그대로 반환됨.)
    """
    lines = []
    head = _as_text(unit.get("조문내용"))
    if head:
        lines.append(head)
    for hang in _as_list(unit.get("항")):
        if not isinstance(hang, dict):
            continue
        hang_text = _as_text(hang.get("항내용"))
        if hang_text:
            lines.append(hang_text)
        for ho in _as_list(hang.get("호")):
            if not isinstance(ho, dict):
                continue
            ho_text = _as_text(ho.get("호내용"))
            if ho_text:
                lines.append(ho_text)
            for mok in _as_list(ho.get("목")):
                if not isinstance(mok, dict):
                    continue
                mok_text = _as_text(mok.get("목내용"))
                if mok_text:
                    lines.append(mok_text)
    return "\n".join(lines)


def _fetch_full_law(law_id: str) -> dict[str, str]:
    """
    법령ID(법령일련번호/MST)로 전체 조문 조회.
    반환: {"제1조": "제1조(목적) 이 법은...", "제2조": "...", ...}

    API 응답 구조:
      조문단위[].조문여부 == "조문"  →  실제 조항 (chapter heading은 "전문")
      조문단위[].조문내용  →  단문 조문은 전체 내용, 다항 조문은 제목만
      조문단위[].항[].항내용 / 항[].호[].호내용 / 호[].목[].목내용  →  다항 조문의 실제 본문
      (_build_article_text가 위 구조를 전부 이어붙여 완전한 텍스트를 만든다)
    """
    key = _get_api_key()
    articles: dict[str, str] = {}
    try:
        r = requests.get(
            LAW_ARTICLE_URL,
            params={"OC": key, "target": "law", "type": "JSON", "MST": law_id},
            timeout=15,
        )
        data = r.json()
        units = (
            data.get("법령", {})
                .get("조문", {})
                .get("조문단위", [])
        )
        if isinstance(units, dict):
            units = [units]
        for unit in units:
            if unit.get("조문여부") != "조문":
                continue
            content = _build_article_text(unit)
            if not content:
                continue
            # 조문내용 첫머리에서 "제N조" 또는 "제N조의N" 추출
            m = re.match(r'(제\d+조(?:의\d+)?)', content)
            if m:
                art_key = m.group(1)
                # 중복 조문(개정 전/후)은 첫 번째 우선
                if art_key not in articles:
                    articles[art_key] = content
    except Exception:
        pass
    return articles


# ============================================================
# Public API
# ============================================================

def fetch_article(law_name: str, article_no: str) -> str | None:
    """
    특정 법령의 특정 조문 내용 반환.
    - 캐시 있으면 즉시 반환
    - 캐시 없으면 API로 법령 전체 조회 후 캐시, 해당 조문 추출

    law_name  : "건축기본법"
    article_no: "제2조"
    """
    cached = _load_cache(law_name)
    if cached:
        return cached.get("articles", {}).get(article_no)

    # API 조회
    law_id = _fetch_law_id(law_name)
    if not law_id:
        return None

    articles = _fetch_full_law(law_id)
    if not articles:
        return None

    _save_cache(law_name, articles)
    return articles.get(article_no)


def fetch_hints(
    hints: list[str],
    known_law_names: set[str],
) -> tuple[list[dict], list[str]]:
    """
    law_hints에서 DB 미수록 법령 조문을 실시간 조회.

    Parameters
    ----------
    hints           : Pass 1 law_hints (e.g. ["건축기본법 제2조", "도시정비법 제81조"])
    known_law_names : law_articles DB에 있는 법령명 집합

    Returns
    -------
    (fetched, truly_missing)
    - fetched       : [{"law_name": ..., "article_no": ..., "content": ...}, ...]
    - truly_missing : API 조회도 실패한 법령명 리스트
    """
    if not _get_api_key():
        return [], []

    fetched: list[dict] = []
    truly_missing: list[str] = []

    for hint in hints:
        law_name, article_no = parse_hint(hint)
        if not law_name:
            continue
        # DB에 있는 법령이면 스킵
        if any(law_name in kl or kl in law_name for kl in known_law_names):
            continue
        if not article_no:
            truly_missing.append(hint)
            continue

        content = fetch_article(law_name, article_no)
        if content:
            fetched.append({
                "law_name":   law_name,
                "article_no": article_no,
                "content":    f"[{law_name}] {content}",
            })
        else:
            truly_missing.append(f"{law_name} {article_no}")

    return fetched, truly_missing
