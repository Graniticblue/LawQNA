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
    "건축기본법 제5조의2"     → ("건축기본법", "제5조의2")
    힌트에 조문번호 없으면    → (hint, "")

    의M(가지조문)을 보존해야 캐시 키(제N조의M)와 정확히 매칭된다 —
    잘라먹으면 제5조의2 요청에 제5조(다른 조문)를 반환하는 버그가 됨.
    """
    m = re.search(r'(제\d+조(?:의\d+)?)', hint)
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


def _save_cache(
    law_name: str,
    articles: dict[str, str],
    delegations: dict[str, list] | None = None,
    cached_at: str | None = None,
) -> None:
    """법령 전체 조문 캐시 저장. articles = {"제2조": "...", "제3조": "..."}
    delegations = {"제2조": [{"law": "건축법 시행령", "art": "제3조"}, ...]}
    (조문 속 '대통령령/부령으로 정하는'이 가리키는 하위법령 조문 — lsDelegated)"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(law_name).write_text(
        json.dumps({"cached_at": cached_at or datetime.now().isoformat(),
                    "articles": articles,
                    "delegations": delegations or {}},
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
        # 별표 전문도 같은 dict에 동봉 ("별표1"·"별표5의2" 키 — 서식 제외)
        for k, v in _parse_byeolpyo_units(data.get("법령", {}).get("별표", {})).items():
            articles.setdefault(k, v)
    except Exception:
        pass
    return articles


def _fetch_delegations(law_id: str) -> dict[str, list[dict]]:
    """
    위임법령 조회(target=lsDelegated) — 법제처 웹 조문의 '대통령령으로 정하는'
    하이퍼링크 원천 데이터. 조번호 없는 위임을 하위법령 조문으로 해소한다.

    반환: {"제2조": [{"law": "건축법 시행령", "art": "제3조"}, ...], ...}

    응답 구조:
      위임조문정보[].조정보.조문번호/조문가지번호        → 출발 조문 (제N조[의M])
      위임조문정보[].위임정보[].위임구분                → 시행령/시행규칙만 채택
        (인용법령·위임행정규칙·위임자치법규는 제외 — 인용은 crossref 확장이 커버)
      위임정보[].위임법령제목 + 위임법령조문정보[].위임법령조문번호/가지번호 → 대상 조문
    """
    key = _get_api_key()
    out: dict[str, list[dict]] = {}
    if not key:
        return out
    try:
        r = requests.get(
            LAW_ARTICLE_URL,
            params={"OC": key, "target": "lsDelegated", "type": "JSON", "MST": law_id},
            timeout=15,
        )
        infos = _as_list(
            r.json().get("lsDelegated", {}).get("법령", {}).get("위임조문정보")
        )
        for info in infos:
            if not isinstance(info, dict):
                continue
            jo = info.get("조정보") or {}
            no = _as_text(jo.get("조문번호"))
            if not no:
                continue
            src = f"제{no.lstrip('0') or no}조"
            branch = _as_text(jo.get("조문가지번호"))
            if branch and branch != "0":
                src += f"의{branch}"
            for w in _as_list(info.get("위임정보")):
                if not isinstance(w, dict):
                    continue
                gubun = _as_text(w.get("위임구분"))
                if "시행령" not in gubun and "시행규칙" not in gubun:
                    continue
                law = _as_text(w.get("위임법령제목"))
                if not law:
                    continue
                for j in _as_list(w.get("위임법령조문정보")):
                    if not isinstance(j, dict):
                        continue
                    tno = _as_text(j.get("위임법령조문번호"))
                    if not tno:
                        continue
                    art = f"제{tno.lstrip('0') or tno}조"
                    tbr = _as_text(j.get("위임법령조문가지번호"))
                    if tbr and tbr != "0":
                        art += f"의{tbr}"
                    tgt = {"law": law, "art": art,
                           "title": _as_text(j.get("위임법령조문제목"))}
                    if all(t["law"] != law or t["art"] != art
                           for t in out.setdefault(src, [])):
                        out[src].append(tgt)
    except Exception:
        pass
    return out


# ============================================================
# Public API
# ============================================================

def fetch_article(law_name: str, article_no: str) -> str | None:
    """
    특정 법령의 특정 조문 내용 반환.
    - 캐시 있으면 즉시 반환
    - 캐시 없으면 API로 법령 전체 조회 후 캐시, 해당 조문 추출

    law_name  : "건축기본법" / "남양주시 주택 조례" (자치법규는 ordin 타겟으로 자동 라우팅)
    article_no: "제2조"
    """
    cached = _load_cache(law_name)
    if cached:
        arts = cached.get("articles", {})
        hit = _get_article(arts, article_no)
        # 별표 요청인데 별표가 하나도 없는 구버전 캐시면 무시하고 재패치
        stale_byeolpyo = (hit is None
                          and str(article_no).replace(" ", "").startswith("별표")
                          and not any(str(k).startswith("별표") for k in arts))
        if not stale_byeolpyo:
            return hit

    if _is_ordinance(law_name):
        articles = fetch_ordinance(law_name, force=True) if cached else fetch_ordinance(law_name)
        return _get_article(articles or {}, article_no)

    # API 조회 — 조문과 함께 위임 링크(lsDelegated)도 같은 캐시에 동봉
    law_id = _fetch_law_id(law_name)
    if not law_id:
        return None

    articles = _fetch_full_law(law_id)
    if not articles:
        return None

    _save_cache(law_name, articles, _fetch_delegations(law_id))
    return _get_article(articles, article_no)


# ============================================================
# 별표 — 법령·자치법규 공통 파싱
#   별표내용이 중첩 문자열 리스트로 오므로 평탄화해 전문 텍스트로 만든다.
#   서식(신청서 양식)은 제외. 키는 "별표1"·"별표5의2" 형태로 정규화.
# ============================================================

def _flatten_strs(x) -> list:
    if isinstance(x, str):
        return [x]
    out = []
    for i in (x or []):
        out.extend(_flatten_strs(i))
    return out


def _parse_byeolpyo_units(units) -> dict[str, str]:
    """별표단위[] → {"별표1": 전문, "별표5의2": 전문}."""
    if isinstance(units, dict):
        units = units.get("별표단위", units)
    if isinstance(units, dict):
        units = [units]
    out: dict[str, str] = {}
    for u in (units or []):
        if not isinstance(u, dict):
            continue
        if u.get("별표구분", "별표") == "서식":
            continue
        try:
            no = int(str(u.get("별표번호", "0")).lstrip("0") or "0")
        except ValueError:
            continue
        if no <= 0:
            continue
        gaji = str(u.get("별표가지번호", "") or "").lstrip("0")
        key = f"별표{no}" + (f"의{gaji}" if gaji else "")
        text = "\n".join(
            l.rstrip() for l in _flatten_strs(u.get("별표내용")) if str(l).strip())
        if text and key not in out:
            out[key] = text
    return out


def _get_article(articles: dict, article_no: str):
    """조문번호 조회 — 공백 변주('별표 1' vs '별표1') 무시 매칭."""
    if not articles:
        return None
    if article_no in articles:
        return articles[article_no]
    key = re.sub(r"\s+", "", str(article_no or ""))
    for k, v in articles.items():
        if re.sub(r"\s+", "", k) == key:
            return v
    return None


# ============================================================
# 자치법규(조례) — target=ordin
#   국가법령과 같은 DRF 엔드포인트를 쓰되 타겟만 다르다.
#   본문 구조가 단순: LawService → 조문 → 조[] 의 '조내용'에
#   항·호·목이 이미 합쳐진 완전한 조 텍스트가 들어 있다.
# ============================================================

def _is_ordinance(name: str) -> bool:
    """자치법규 판별 — '조례'가 들어가면 ordin 타겟 ('...조례 시행규칙' 포함)."""
    return "조례" in (name or "")


def _fetch_ordin_mst(name: str) -> str | None:
    """자치법규명으로 일련번호(MST) 조회 — 정확 명칭 일치만 인정.

    동명 조례가 지자체마다 있으므로('주택 조례') 질의에 지자체명이 포함된
    정확 명칭이어야 한다. 복수 매칭 시 시행일자 최신본."""
    key = _get_api_key()
    if not key:
        return None

    def norm(s):
        return re.sub(r"\s+", "", str(s or ""))

    # 흔한 명칭('주택 조례')은 동명 지자체가 수백 건이라 상위 페이지에 정확 일치가
    # 안 들어올 수 있다 → 몇 페이지 넘겨 가며 정확 일치를 찾는다.
    cands = []
    try:
        for page in range(1, 6):
            r = requests.get(
                LAW_SEARCH_URL,
                params={"OC": key, "target": "ordin", "type": "JSON",
                        "query": name, "display": 100, "page": page},
                timeout=15,
            )
            root = r.json().get("OrdinSearch", {})
            laws = root.get("law") or []
            if isinstance(laws, dict):
                laws = [laws]
            if not laws:
                break
            cands += [l for l in laws if norm(l.get("자치법규명")) == norm(name)]
            if cands or page * 100 >= int(root.get("totalCnt", 0)):
                break
    except Exception:
        return None
    if not cands:
        return None
    cands.sort(key=lambda l: str(l.get("시행일자", "")), reverse=True)
    return str(cands[0].get("자치법규일련번호") or "") or None


def _fetch_full_ordin(mst: str) -> dict[str, str]:
    """자치법규 전체 조문 조회. 반환: {"제5조": "제5조(주민공동시설)① ...", ...}"""
    key = _get_api_key()
    articles: dict[str, str] = {}
    try:
        r = requests.get(
            LAW_ARTICLE_URL,
            params={"OC": key, "target": "ordin", "type": "JSON", "MST": mst},
            timeout=15,
        )
        svc = r.json().get("LawService", {})
        units = svc.get("조문", {}).get("조", [])
        if isinstance(units, dict):
            units = [units]
        for u in units:
            content = u.get("조내용", "")
            if isinstance(content, list):
                content = "\n".join(str(x) for x in content)
            content = str(content).strip()
            m = re.match(r'(제\d+조(?:의\d+)?)', content)
            if m and m.group(1) not in articles:   # 개정 전/후 중복은 첫 번째 우선
                articles[m.group(1)] = content
        # 자치법규 별표 — 응답 최상위 '별표단위' (법령과 위치가 다름)
        for k, v in _parse_byeolpyo_units(svc.get("별표단위") or svc.get("별표") or []).items():
            articles.setdefault(k, v)
    except Exception:
        return {}
    return articles


def search_ordinances(query: str, display: int = 30, page: int = 1) -> list[dict]:
    """자치법규 제목 검색 원시 결과 — 지역 조례 스캔(미보유 지역 캐싱 버튼)용."""
    key = _get_api_key()
    if not key:
        return []
    try:
        r = requests.get(
            LAW_SEARCH_URL,
            params={"OC": key, "target": "ordin", "type": "JSON",
                    "query": query, "display": display, "page": page},
            timeout=15,
        )
        laws = r.json().get("OrdinSearch", {}).get("law") or []
        return [laws] if isinstance(laws, dict) else list(laws)
    except Exception:
        return []


def fetch_ordinance(name: str, force: bool = False) -> dict[str, str] | None:
    """자치법규(조례) 전체 조문+별표 반환 + 캐시. 위임 링크는 자치법규엔 미제공.
    force=True면 캐시를 무시하고 재패치(구버전 캐시에 별표가 없을 때)."""
    if not force:
        cached = _load_cache(name)
        if cached:
            return cached.get("articles") or None
    mst = _fetch_ordin_mst(name)
    if not mst:
        return None
    articles = _fetch_full_ordin(mst)
    if not articles:
        return None
    _save_cache(name, articles, {})
    return articles


def fetch_delegations(law_name: str, article_no: str) -> list[dict]:
    """
    캐시된 법령에서 특정 조문의 위임 대상 조문 목록 반환.
    반환: [{"law": "건축법 시행령", "art": "제3조"}, ...] (없으면 [])

    구형 캐시(articles만 있고 delegations 키 자체가 없음)는 위임 정보만
    한 번 보강해 파일을 갱신한다(cached_at 유지 — 조문은 그대로이므로).
    """
    cached = _load_cache(law_name)
    if cached is None:
        return []
    if "delegations" not in cached:
        law_id = _fetch_law_id(law_name)
        deleg = _fetch_delegations(law_id) if law_id else {}
        _save_cache(law_name, cached.get("articles", {}), deleg,
                    cached_at=cached.get("cached_at"))
        cached["delegations"] = deleg
    return cached.get("delegations", {}).get(article_no, [])


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
