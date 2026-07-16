# -*- coding: utf-8 -*-
"""statute_quote.py -- 답변 속 '조문 직접 인용'의 원문 대조 검증 (로컬 전용)

16-0506 실증: 정답에 필요한 조문·해석 원칙이 전부 컨텍스트에 있어도, 생성
모델이 자기 추론에 맞춰 조문 문언을 재작성해 따옴표 인용으로 제시할 수 있다
— 영 제25조③ 각 호 외 부분에 "(다른 호에 저촉되지 않는 경우로 한정한다)"라는
존재하지 않는 괄호를 날조해 반대 결론을 정당화. 번호 인용 검증(cite_verify)은
해석례·판례 '번호'만 다루므로, 이 모듈이 조문 '문언' 층을 맡는다.

원칙:
  * 로컬 코퍼스(data/raw_laws/all_articles.jsonl)만 대조 — API 접근 없음.
  * 보수적 판정: (a) 인용 뒤 문맥이 '~라고 규정/명시'처럼 법문임을 주장하고,
    (b) 법령·조문이 특정되며, (c) 그 조문이 코퍼스에 실재할 때만 mismatch를
    낸다. 특정 불가·코퍼스 외 조문·짧은 인용은 판정 보류(반환 안 함).
  * 생략 부호(…, 중략)로 끊긴 인용은 분절별로 각각 원문 부분일치를 요구.
"""
import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
ARTICLES_PATH = BASE_DIR / "data" / "raw_laws" / "all_articles.jsonl"

# 약칭 → 코퍼스 법령명 (공백 제거 기준으로 비교)
_ALIASES = {
    "국토계획법": "국토의 계획 및 이용에 관한 법률",
    "도시정비법": "도시 및 주거환경정비법",
    "녹색건축법": "녹색건축물 조성 지원법",
    "소방시설법": "소방시설 설치 및 관리에 관한 법률",
    "장애인등편의법": "장애인ㆍ노인ㆍ임산부 등의 편의증진 보장에 관한 법률",
    "주택건설기준규정": "주택건설기준 등에 관한 규정",
    "공공주택특별법": "공공주택 특별법",
    "건설기술진흥법": "건설기술 진흥법",
}

_index: dict | None = None          # norm_law → {article_no → norm_content}
_law_names: dict | None = None      # norm_law → 원 법령명


def _norm(s: str) -> str:
    """대조용 정규화: 공백·마크다운 장식·가운뎃점·따옴표 표기차 제거.

    따옴표류를 지우는 이유: 원문의 “소유자등” 같은 내부 인용이 답변에서
    "소유자등"·〝소유자등〞(약칭 마스킹 잔재)으로 바뀌어도 같게 대조되도록."""
    s = str(s or "")
    s = re.sub(r"[\s​﻿]+", "", s)
    s = s.replace("*", "").replace("`", "").replace("_", "")
    s = s.replace("ㆍ", "").replace("·", "").replace("・", "")
    s = s.replace("（", "(").replace("）", ")")
    for q in "\"“”〝〞'‘’":
        s = s.replace(q, "")
    return s


def _load_index() -> dict:
    global _index, _law_names
    if _index is not None:
        return _index
    idx: dict = {}
    names: dict = {}
    try:
        with open(ARTICLES_PATH, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                law = r.get("law_name", "")
                art = str(r.get("article_no", "")).replace(" ", "")
                if not law or not re.fullmatch(r"제\d+조(의\d+)?", art):
                    continue
                nk = _norm(law)
                names[nk] = law
                idx.setdefault(nk, {})
                # 같은 조문이 여러 레코드로 나뉘어 있어도 이어붙여 대조
                idx[nk][art] = idx[nk].get(art, "") + _norm(r.get("content", ""))
    except Exception:
        idx = {}
    _index = idx
    _law_names = names
    return idx


def _resolve_law(raw: str) -> str | None:
    """법령명 표기(약칭 포함) → 코퍼스 norm 키. 미보유면 None."""
    idx = _load_index()
    nk = _norm(raw.strip().strip("「」"))
    if nk in idx:
        return nk
    for abbr, full in _ALIASES.items():
        a = _norm(abbr)
        if nk == a or nk.startswith(a):
            cand = _norm(full) + nk[len(a):]
            if cand in idx:
                return cand
    return None


# 법령+조문 언급 패턴 (인용 귀속 탐색용)
_LAWREF_PAT = re.compile(
    r"「([^」]{2,45})」\s*(?:\([^)]{0,40}\))?\s*(제\d+조(?:의\d+)?)"          # 「전체명」 제N조
    r"|(?<![가-힣])([가-힣]{2,15}(?:특별)?(?:법|법률)(?:\s?시행령|\s?시행규칙)?)\s*(제\d+조(?:의\d+)?)"  # 약칭 제N조
    r"|(?<![가-힣])(같은\s*법\s*시행령|같은\s*법\s*시행규칙|같은\s*법|같은\s*영|같은\s*규칙"
    r"|이\s*법|이\s*영|이\s*규칙|법|영|규칙)\s*(제\d+조(?:의\d+)?)"           # 상대참조
)

# 따옴표 인용 (겹따옴표만 — 홑따옴표는 용어 강조로 오탐 많음)
_QUOTE_PAT = re.compile(r'["“]([^"“”]{12,700})["”]')

# 약칭 정의: (이하 "국토계획법 시행령"이라 함) — 이 따옴표가 짝짓기에 끼면
# 따옴표 '사이'의 일반 산문이 인용으로 오인된다. 스캔 전에 마스킹한다.
_ABBR_DEF_PAT = re.compile(r'이하\s*["“][^"“”]{1,40}["”]\s*(?:이?라)\s*(?:한다|함|합니다)')


def _mask_abbrev_defs(text: str) -> str:
    """약칭 정의 속 따옴표를 같은 길이의 비따옴표 문자로 치환 (오프셋 보존)."""
    return _ABBR_DEF_PAT.sub(
        lambda m: m.group(0).replace('"', "〝").replace("“", "〝").replace("”", "〞"),
        text)

# 인용 직후 '법문 주장' 문맥 — 해석례·판례 인용("~라고 회신/판시")과 구별
_STATUTE_CTX = re.compile(r"규정|명시|정하고\s*있")
_NON_STATUTE_CTX = re.compile(r"회신|해석하|판시|판결|판단하")


def _family(base_norm: str) -> dict:
    """norm 법령 키 → 가족(법/영/규칙) norm 키 후보."""
    b = re.sub(r"시행(령|규칙)$", "", base_norm)
    return {"법": b, "영": b + "시행령", "규칙": b + "시행규칙"}


def _find_attribution(text: str, quote_start: int):
    """인용 앞 문맥에서 (법령 norm 키, 조문번호)를 찾는다.

    답변 전체에서 인용 이전의 '마지막' 법령+조문 언급을 귀속 대상으로 본다
    (한 문단이 한 조문을 다루는 통상 구조 반영). 상대참조('같은 영'·'법')는
    마지막 명시 법령의 가족(법/영/규칙)으로 해소한다."""
    last_explicit: str | None = None      # norm 키
    best = None                           # (norm_law, art, pos)
    for m in _LAWREF_PAT.finditer(text[:quote_start]):
        if m.group(1):                    # 「전체명」
            law_raw, art = m.group(1), m.group(2)
            nk = _resolve_law(law_raw)
            if nk:
                last_explicit = nk
        elif m.group(3):                  # 약칭
            law_raw, art = m.group(3), m.group(4)
            nk = _resolve_law(law_raw)
            if nk:
                last_explicit = nk
        else:                             # 상대참조
            token, art = re.sub(r"\s+", "", m.group(5)), m.group(6)
            if not last_explicit:
                continue
            fam = _family(last_explicit)
            if token in ("같은법시행령", "영", "이영"):
                nk = fam["영"]
            elif token in ("같은법시행규칙", "규칙", "이규칙"):
                nk = fam["규칙"]
            elif token in ("같은법", "법", "이법"):
                nk = fam["법"]
            else:
                continue
            if nk not in _load_index():
                continue
        if nk:
            best = (nk, art.replace(" ", ""), m.start())
    if best is None:
        return None
    # 창 밖(300자 초과 이전)의 언급이라도 '인용 이전 마지막 언급'이면 채택
    return best[0], best[1]


def _segments(quote: str) -> list[str]:
    parts = re.split(r"\.{2,}|…|⋯|‥|\(중략\)|중략|\(생\s*략\)|<생략>", quote)
    return [p for p in (s.strip(" ,.;:~-") for s in parts) if p]


def _strip_parens(s: str) -> str:
    """중첩 괄호 스팬 제거 — '괄호 생략 인용' 허용 매칭용 (원문 쪽에만 적용)."""
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"\([^()]*\)", "", s)
    return s


def verify_answer_quotes(answer: str) -> list[dict]:
    """답변 속 조문 직접 인용을 코퍼스 원문과 대조.

    반환: [{law, article, quote, status, missing}]
      status: "ok" | "mismatch"  (판정 보류 건은 반환하지 않음)
      missing: 원문에서 찾지 못한 인용 분절들 (mismatch일 때)
    """
    idx = _load_index()
    if not idx:
        return []
    answer = _mask_abbrev_defs(answer)
    findings: list[dict] = []
    seen: set = set()
    for qm in _QUOTE_PAT.finditer(answer):
        quote = qm.group(1)
        if "\n" in quote:
            continue                      # 법문 인용은 문단을 넘지 않는다 — 짝 밀림 방지
        if re.search(r"(합니다|입니다|습니다)\s*$", quote.strip()):
            continue                      # 법문은 경어체로 끝나지 않는다 — 취지·설명 인용 보류
        after = answer[qm.end(): qm.end() + 45]
        if not _STATUTE_CTX.search(after) or _NON_STATUTE_CTX.search(after):
            continue                      # 법문 주장 인용이 아님 — 보류
        attr = _find_attribution(answer, qm.start())
        if not attr:
            continue                      # 귀속 불가 — 보류
        nk, art = attr
        art_text = idx.get(nk, {}).get(art)
        if not art_text:
            continue                      # 코퍼스에 그 조문 없음 — 보류
        segs = [s for s in _segments(quote) if len(_norm(s)) >= 10]
        if not segs:
            continue                      # 판정할 만큼 긴 분절 없음 — 보류
        # 매칭 3단: ① 원문 그대로 ② 원문에서 괄호 스팬을 뺀 판(원문 괄호를
        # 생략한 압축 인용 허용) ③ 인용의 괄호를 벗긴 본줄기가 ②와 일치하고
        # 인용에 '남은' 괄호 내용이 각각 원문에 실재(괄호 일부 생략+일부 유지
        # 혼합 인용 허용). 어느 단계에서도 인용 쪽에 원문에 없는 괄호가 있으면
        # 통과하지 못하므로, 괄호 '삽입' 날조는 여전히 mismatch로 잡힌다.
        art_noparen = _strip_parens(art_text)

        def _seg_ok(seg: str) -> bool:
            n = _norm(seg)
            if n in art_text or n in art_noparen:
                return True
            trunk = _norm(_strip_parens(seg))
            if trunk and trunk in art_noparen:
                return all(_norm(p) in art_text
                           for p in re.findall(r"\(([^()]*)\)", seg) if _norm(p))
            return False

        missing = [s for s in segs if not _seg_ok(s)]
        law_disp = (_law_names or {}).get(nk, nk)
        key = (nk, art, _norm(quote))
        if key in seen:
            continue
        seen.add(key)
        findings.append({
            "law": law_disp,
            "article": art,
            "quote": quote if len(quote) <= 220 else quote[:220] + "…",
            "status": "mismatch" if missing else "ok",
            "missing": [s if len(s) <= 120 else s[:120] + "…" for s in missing],
        })
    return findings


def article_text(law_display: str, article: str, cap: int = 2800) -> str:
    """교정 재료용 조문 원문 (원 표기, 캡 적용)."""
    try:
        out = []
        with open(ARTICLES_PATH, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if (r.get("law_name") == law_display
                        and str(r.get("article_no", "")).replace(" ", "") == article):
                    out.append(r.get("content", ""))
        text = "\n".join(out)
        return text[:cap] + ("…(이하 생략)" if len(text) > cap else "")
    except Exception:
        return ""


def corrective_block(mismatches: list[dict]) -> str:
    """원문 불일치 인용 → 교정 재료 주입 재생성 블록.

    단순 '그 인용 쓰지 마'가 아니라 실제 원문 전문을 제시한다 — 오답을
    떠받치던 날조 문언을 무너뜨리는 동시에 올바른 재료를 같은 자리에 준다."""
    if not mismatches:
        return ""
    lines = ["=== [조문 인용 검증 결과 — 재생성 지시] ===",
             "직전 답변 초안의 아래 조문 인용은 실제 원문과 대조한 결과 원문에 없는 문구를 포함한다. "
             "법령 데이터베이스 원문 기준의 검증이므로 이 지시가 우선한다."]
    done = set()
    for i, f in enumerate(mismatches, 1):
        lines.append(f"\n{i}. 「{f['law']}」 {f['article']}")
        for s in f.get("missing", [])[:3]:
            lines.append(f"   - 원문에 없는 인용 문구: \"{s}\"")
        k = (f["law"], f["article"])
        if k not in done:
            done.add(k)
            src = article_text(f["law"], f["article"])
            if src:
                lines.append(f"   - 이 조문의 실제 원문 전문:\n{src}")
    lines.append(
        "\n지시:\n"
        "- 조문 문언을 따옴표로 인용할 때는 위 실제 원문(또는 [관련 법령 조문]의 원문)에 "
        "있는 문자열 그대로만 쓸 것. 원문에 없는 괄호·단서·한정 문구를 삽입해 요건을 "
        "창설하지 말 것.\n"
        "- 위 실제 원문과 [참조 자료 목록]의 해석 원칙(특히 '각 호의 어느 하나' 등 문형 "
        "원칙 해석례)만으로 논증을 다시 구성할 것. 실제 원문이 직전 결론을 지지하지 "
        "않으면 결론을 바꿀 것.\n"
        "- 원문에 없는 내용을 말하려면 인용부호 밖에서 해석 의견임을 밝히고 서술할 것.")
    return "\n".join(lines)


def format_badge(findings: list[dict]) -> str:
    """조문 인용 검증 배지 (mismatch가 있을 때만 호출 권장)."""
    bad = [f for f in findings if f["status"] == "mismatch"]
    lines = [f"📜 **조문 인용 검증** — 원문 불일치 {len(bad)}건"]
    for f in bad:
        seg = f["missing"][0] if f.get("missing") else f["quote"]
        lines.append(f"- 「{f['law']}」 {f['article']}: 인용문 일부가 원문에 없습니다 — "
                     f"\"{seg}\" **원문 대조 필요** (재생성 시 실제 원문 자동 주입)")
    return "\n".join(lines)
