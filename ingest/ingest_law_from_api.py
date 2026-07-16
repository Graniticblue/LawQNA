"""
ingest_law_from_api.py -- 법제처 API 기반 법령 인제스트 파이프라인

법령명 하나로 본문·별표·개정이력을 API에서 수집해 기존 jsonl 스키마로 반영한다.
(PDF/txt 수동 업로드 대체 — 하드랩·목차오염 등 PDF 파싱 함정이 없음)

  본문     lawService(law)       → data/raw_laws/all_articles.jsonl        (해당 법령 교체)
  별표     동일 응답의 별표단위    → data/raw_laws/byeolpyo/byeolpyo_chunks.jsonl (해당 법령 교체)
  개정이력  lawSearch(eflaw) 연혁 → 각 버전 lawService(eflaw)의 제개정이유·개정문
           → gemini enrich       → data/law_amendments/amendments.jsonl    (해당 법령 교체)

사용:
  python ingest/ingest_law_from_api.py --law "건축법 시행령" --dry-run
  python ingest/ingest_law_from_api.py --law "건축법 시행령"                 # 전체
  python ingest/ingest_law_from_api.py --law "..." --skip-amendments        # 본문+별표만
  python ingest/ingest_law_from_api.py --law "..." --amendments-only --limit 3

반영 후: 로컬 검증 → 커밋/push → 배포는 REINDEX_AUX(개정이력만) 또는
FORCE_REINDEX(본문·별표 포함) 플래그로 재인덱싱.

필요 환경변수(.env): LAW_API_KEY, (개정이력 enrich 시) GOOGLE_API_KEY
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import law_api_fetcher as laf   # _fetch_law_id, _build_article_text, _as_list, _as_text

BASE_DIR        = Path(__file__).parent.parent
ARTICLES_PATH   = BASE_DIR / "data" / "raw_laws" / "all_articles.jsonl"
BYEOLPYO_PATH   = BASE_DIR / "data" / "raw_laws" / "byeolpyo" / "byeolpyo_chunks.jsonl"
AMENDMENTS_PATH = BASE_DIR / "data" / "law_amendments" / "amendments.jsonl"
CKPT_DIR        = BASE_DIR / "tmp"

LAW_SEARCH_URL  = "https://www.law.go.kr/DRF/lawSearch.do"
LAW_SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"

API_SLEEP = 0.3   # 법제처 API 예의상 호출 간격(초)


def _get(params: dict, timeout: int = 20) -> dict:
    params = {"OC": os.getenv("LAW_API_KEY", ""), "type": "JSON", **params}
    r = requests.get(
        LAW_SEARCH_URL if params.get("_search") else LAW_SERVICE_URL,
        params={k: v for k, v in params.items() if k != "_search"},
        timeout=timeout,
    )
    time.sleep(API_SLEEP)
    return r.json()


def _flat(v) -> str:
    """API의 (중첩 리스트/딕트) 텍스트 필드를 문자열로 평탄화."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return "\n".join(_flat(x) for x in v)
    if isinstance(v, dict):
        return "\n".join(_flat(x) for x in v.values())
    return str(v)


def _load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _write_jsonl(p: Path, recs: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n",
                 encoding="utf-8")


# ============================================================
# 1) 본문 + 별표 수집
# ============================================================

def fetch_law_bundle(law_name: str) -> dict:
    """현행 법령 전체(기본정보·조문·별표) 조회."""
    mst = laf._fetch_law_id(law_name)
    if not mst:
        raise RuntimeError(f"법령ID 조회 실패: {law_name}")
    law = _get({"target": "law", "MST": mst}).get("법령", {})
    if not law:
        raise RuntimeError(f"법령 본문 조회 실패: {law_name} (MST={mst})")
    return law


def _basic_info(law: dict) -> dict:
    b = law.get("기본정보", {})
    kind = b.get("법종구분")
    kind = kind.get("content", "") if isinstance(kind, dict) else _flat(kind)
    prom_no = str(b.get("공포번호", "")).strip()
    return {
        "law_id":           str(b.get("법령ID", "")).strip(),
        "law_name":         _flat(b.get("법령명_한글") or b.get("법령명한글")).strip(),
        "law_type":         kind.strip(),
        "enforcement_date": str(b.get("시행일자", "")).strip(),
        "promulgation_no":  f"{kind.strip()} 제{int(prom_no)}호" if prom_no.isdigit() else "",
    }


def build_article_records(law: dict, law_name: str) -> list[dict]:
    """조문단위 → all_articles.jsonl 레코드. 기존 DB 관례에 맞춰
    content에서 '제N조(제목)' 헤드는 제거하고, 삭제 조문은 제외한다."""
    basic = _basic_info(law)
    spaceless = re.sub(r"[\s·ㆍ]+", "", law_name)
    src_url = f"https://www.law.go.kr/법령/{spaceless}"

    units = laf._as_list(law.get("조문", {}).get("조문단위"))
    records, seen = [], set()
    for unit in units:
        if unit.get("조문여부") != "조문":
            continue
        full = laf._build_article_text(unit)
        m = re.match(r"(제\d+조(?:의\d+)?)", full)
        if not m or m.group(1) in seen:
            continue
        art_key = m.group(1)
        # 삭제 조문은 DB 관례상 제외
        if re.match(rf"{re.escape(art_key)}\s*삭제", full):
            continue
        seen.add(art_key)

        # content: 헤드 라인에서 '제N조(제목)' 접두만 벗겨냄 (단문은 같은 줄에 본문이 이어짐)
        lines = full.split("\n")
        head = re.sub(rf"^{re.escape(art_key)}\s*(\([^)]*\))?\s*", "", lines[0]).strip()
        body_lines = ([head] if head else []) + lines[1:]
        # 조문참고자료([전문개정 ...])를 기존 DB처럼 본문 끝에 부기
        ref = _flat(unit.get("조문참고자료")).strip()
        if ref:
            body_lines.append(ref)
        content = "\n".join(body_lines).strip()
        if not content:
            continue

        records.append({
            "law_id":           basic["law_id"],
            "law_name":         law_name,
            "law_type":         basic["law_type"],
            "article_no":       art_key,
            "article_title":    _flat(unit.get("조문제목")).strip(),
            "content":          content,
            "enforcement_date": basic["enforcement_date"],
            "promulgation_no":  basic["promulgation_no"],
            "source_url":       src_url,
        })
    return records


def _section_title(chunk: str) -> str:
    """청크 첫 줄에서 섹션 제목 추출 — 괄호가 열리면 그 앞에서 자른다
    ('1. 건축할 수 있는 건축물(경관관리 등을…' 절단 방지)."""
    m = re.search(r"^\s*(\d{1,2}\.\s*[^\n]{2,60})", chunk.strip())
    if not m:
        return "전체"
    t = m.group(1).strip()
    if "(" in t and ")" not in t[t.index("("):]:
        t = t[: t.index("(")].strip()
    return t[:40].strip()


def _split_byeolpyo(text: str, mok_threshold: int = 1200) -> list[tuple[str, str]]:
    """별표를 호(1. 2. …) 단위 '개별' 청크로 분할하고, 호가 mok_threshold를
    넘으면 목(가. 나. …) 경계로 하위 분할한다. 반환: [(section_title, chunk)].

    구 방식(호 경계 greedy 묶음 ≤2,000자)은 임베딩(128토큰)이 묶음 앞부분만
    보는 사각을 만들었다 — 호 단위 개별 + 인덱서의 헤더 프리픽스 조합이
    '용도지역 × 개별 용도' 류 질의의 벡터 리콜을 살린다 (2026-07-16 컨펌)."""
    hos = [p.strip() for p in re.split(r"(?m)^(?=\s{0,4}\d{1,2}\.\s)", text) if p.strip()]
    if not hos:
        return [("전체", text.strip())] if text.strip() else []
    out: list[tuple[str, str]] = []
    for ho in hos:
        title = _section_title(ho)
        if len(ho) <= mok_threshold:
            out.append((title, ho))
            continue
        parts = re.split(r"(?m)^(?=\s{0,6}[가-힣]\.\s)", ho)
        subs, buf = [], ""
        for p in parts:
            if buf and len(buf) + len(p) > mok_threshold:
                subs.append(buf.strip())
                buf = p
            else:
                buf += p
        if buf.strip():
            subs.append(buf.strip())
        if len(subs) == 1:
            out.append((title, subs[0]))
        else:
            for i, s in enumerate(subs, 1):
                out.append((f"{title} (분할 {i})", s))
    return out


def build_byeolpyo_records(law: dict, law_name: str) -> list[dict]:
    """별표단위 → byeolpyo_chunks.jsonl 레코드 (별표만, 서식은 제외)."""
    basic = _basic_info(law)
    spaceless = re.sub(r"[\s·ㆍ]+", "", law_name)
    units = laf._as_list(law.get("별표", {}).get("별표단위"))
    records = []
    for u in units:
        if u.get("별표구분") != "별표":
            continue
        no = str(u.get("별표번호", "")).lstrip("0") or "0"
        gaji = str(u.get("별표가지번호", "")).lstrip("0")
        byeolpyo_no = f"{no}의{gaji}" if gaji else no
        title = _flat(u.get("별표제목")).strip()
        raw = _flat(u.get("별표내용"))
        # API 별표 텍스트는 고정폭 패딩이 심함 — 연속 공백 축약 + 빈 줄 정리
        text = re.sub(r"[ \t]{2,}", " ", raw)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(text) < 30:   # 이미지 전용 별표(텍스트 없음)는 스킵
            continue
        m = re.search(r"\((제\d+조[^)]*)\s*관련\)", title)
        related = m.group(1) if m else ""
        for seq, (section, chunk) in enumerate(_split_byeolpyo(text), 1):
            records.append({
                "law_id":           f"{basic['law_id']}_별표{byeolpyo_no}",
                "law_name":         law_name,
                "law_type":         basic["law_type"],
                "article_no":       f"별표{byeolpyo_no}",
                "article_title":    re.sub(r"\([^)]*관련\)", "", title).strip(),
                "content":          chunk,
                "enforcement_date": basic["enforcement_date"],
                "source_url":       f"https://www.law.go.kr/법령/{spaceless}/별표{byeolpyo_no}",
                "is_byeolpyo":      True,
                "byeolpyo_no":      byeolpyo_no,
                "related_article":  related,
                "chunk_seq":        seq,
                "section_title":    section,
            })
    return records


# ============================================================
# 2) 개정이력 수집 + enrich
# ============================================================

def fetch_history(law_name: str) -> list[dict]:
    """eflaw(시행일 법령) 연혁 전체 → 일부·전부개정만, 공포번호 단위로 dedupe.
    (타법개정·제정 제외는 기존 enrich 정책과 동일)"""
    entries, page = [], 1
    while True:
        data = _get({"_search": True, "target": "eflaw", "query": law_name,
                     "display": "100", "page": str(page)})
        root = data.get("LawSearch", data)
        laws = laf._as_list(root.get("law"))
        if not laws:
            break
        entries.extend(laws)
        total = int(root.get("totalCnt", 0) or 0)
        if page * 100 >= total:
            break
        page += 1

    by_num: dict[str, dict] = {}
    for l in entries:
        if l.get("법령명한글", "").strip() != law_name.strip():
            continue
        if l.get("제개정구분명") not in ("일부개정", "전부개정"):
            continue
        num = str(l.get("공포번호", "")).strip()
        cur = by_num.get(num)
        # 같은 공포번호가 시행일별로 여러 건 → 최초 시행일 채택
        if cur is None or str(l.get("시행일자", "")) < str(cur.get("시행일자", "")):
            by_num[num] = l
    return sorted(by_num.values(), key=lambda x: str(x.get("공포일자", "")), reverse=True)


def fetch_revision_docs(mst: str, ef_yd: str, prom_num: str) -> tuple[str, str, str, str]:
    """과거 버전의 (제개정이유, 개정문, 법종구분명, 해당 개정분 부칙) 조회.
    부칙단위는 역대 부칙이 누적돼 있으므로 부칙공포번호로 해당 개정분만 필터."""
    law = _get({"target": "eflaw", "MST": mst, "efYd": ef_yd}).get("법령", {})
    reason = _flat(law.get("제개정이유")).strip()
    moon   = _flat(law.get("개정문")).strip()
    kind   = _basic_info(law).get("law_type", "")
    buchik = ""
    units = law.get("부칙", {})
    units = laf._as_list(units.get("부칙단위", units) if isinstance(units, dict) else units)
    for u in units:
        if isinstance(u, dict) and str(u.get("부칙공포번호", "")).lstrip("0") == prom_num.lstrip("0"):
            buchik = _flat(u.get("부칙내용")).strip()
            break
    return reason, moon, kind, buchik


def _amend_prefix(law_name: str) -> str:
    """amendment_id 접두 — 기존 amendments.jsonl의 관례(축약형)를 재사용하고,
    처음 보는 법령은 공백 제거한 전체명(chainlit 조회 폴백과 일치)을 쓴다."""
    for r in _load_jsonl(AMENDMENTS_PATH):
        if r.get("law_name") == law_name:
            m = re.match(r"^(.+?)_\d{8}_", r.get("amendment_id", ""))
            if m:
                return m.group(1)
    return re.sub(r"[\s·ㆍ]+", "", law_name)


ENRICH_PROMPT = """{law} 개정의 [개정이유]·[개정문]·[부칙]이다. 아래 JSON으로만 구조화하라.
{{"개정이유":"핵심 2~3문장","주요내용":[{{"항목":"...","조문":["제N조"],"내용":"..."}}],
"개정조문":["제N조","제N조의M"],
"조문_변경":[{{"조문":"제N조","변경":"신설/개정 — 한 줄"}}],
"목적론적_키포인트":"입법목적·해석핵심 1~2문장",
"부칙_시행일_특이사항":{{"원칙":"...","예외":"조문별 다른 시행일 (없으면 빈문자열)"}},
"부칙_적용례_요약":"적용례·경과조치 핵심 (없으면 빈문자열)",
"부칙_상세":{{"제N조_제목":"내용 요약"}}}}
JSON만. 개정조문/조문_변경은 개정문에서 실제 바뀐 조문번호를 정확히.
부칙_* 필드는 [부칙]에서만 추출하고, 부칙이 비어있으면 빈 값으로.

[개정이유]
{reason}

[개정문]
{moon}

[부칙]
{buchik}"""


def _gemini_enrich(law_name: str, reason: str, moon: str, buchik: str) -> dict:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    try:
        resp = client.models.generate_content(
            model=model,
            contents=ENRICH_PROMPT.format(law=law_name, reason=reason[:5000],
                                          moon=moon[:7000], buchik=buchik[:4000]),
            config=types.GenerateContentConfig(
                max_output_tokens=8000, temperature=0.2,
                thinking_config=types.ThinkingConfig(thinking_budget=0)),
        )
        m = re.search(r"\{.*\}", resp.text or "", re.DOTALL)
        return json.loads(m.group()) if m else {}
    except Exception as e:
        print(f"    [WARN] enrich 실패: {e}", flush=True)
        return {}


def _iso(d: str) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 and d.isdigit() else d


def build_amendment_records(law_name: str, history: list[dict], limit: int = 0) -> list[dict]:
    """연혁 각 건의 제개정이유·개정문을 API로 받아 gemini로 구조화.
    체크포인트(tmp/_api_enrich_*.jsonl)로 중단 후 재개 가능."""
    prefix = _amend_prefix(law_name)
    ckpt_path = CKPT_DIR / f"_api_enrich_{prefix}.jsonl"
    done = {r["amendment_id"]: r for r in _load_jsonl(ckpt_path)}

    if limit:
        history = history[:limit]
    records = []
    CKPT_DIR.mkdir(parents=True, exist_ok=True)
    with open(ckpt_path, "a", encoding="utf-8") as fout:
        for i, h in enumerate(history, 1):
            num = str(h.get("공포번호", "")).strip()
            enf = str(h.get("시행일자", "")).strip()
            aid = f"{prefix}_{enf}_{num}호"
            if aid in done:
                records.append(done[aid])
                continue
            reason, moon, kind, buchik = fetch_revision_docs(
                str(h.get("법령일련번호", "")), enf, num)
            if not reason and not moon:
                print(f"  [{i}/{len(history)}] {aid} — 제개정이유·개정문 없음(스킵)", flush=True)
                continue
            en = _gemini_enrich(law_name, reason, moon, buchik)
            rec = {
                "amendment_id": aid,
                "law_name":     law_name,
                "공포번호":     f"{kind} 제{int(num)}호" if num.isdigit() and kind else num,
                "공포일":       _iso(str(h.get("공포일자", ""))),
                "시행일":       _iso(enf),
                "개정유형":     h.get("제개정구분명", ""),
                "개정이유":     en.get("개정이유", ""),
                "주요내용":     en.get("주요내용", []),
                "개정조문":     en.get("개정조문", []),
                "조문_변경":    en.get("조문_변경", []),
                "목적론적_키포인트": en.get("목적론적_키포인트", ""),
                "부칙_시행일_특이사항": en.get("부칙_시행일_특이사항", {}),
                "부칙_적용례_요약":     en.get("부칙_적용례_요약", ""),
                "부칙_상세":            en.get("부칙_상세", {}),
                "연관_개정":    [],
                "개정문있음":   bool(moon),
                "부칙있음":     bool(buchik),
            }
            records.append(rec)
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fout.flush()
            print(f"  [{i}/{len(history)}] {aid} / 개정문{'O' if moon else 'X'} "
                  f"/ 부칙{'O' if buchik else 'X'} / 조문{en.get('개정조문', [])[:4]}", flush=True)
    return records


# ============================================================
# 3) jsonl 반영 (해당 법령 레코드 교체)
# ============================================================

def replace_in_jsonl(path: Path, law_name: str, new_recs: list[dict],
                     dry_run: bool, label: str) -> None:
    old = _load_jsonl(path)
    kept = [r for r in old if r.get("law_name") != law_name]
    removed = len(old) - len(kept)
    print(f"[{label}] 기존 {removed}건 교체 → 신규 {len(new_recs)}건 "
          f"(파일 전체 {len(kept) + len(new_recs)}건)")
    if dry_run:
        return
    _write_jsonl(path, kept + new_recs)


# ============================================================
# 메인
# ============================================================

def main():
    # Windows 콘솔(cp949)에서 em-dash 등 출력 크래시 방지
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="법제처 API 기반 법령 인제스트")
    ap.add_argument("--law", required=True, help='법령명 (예: "건축법 시행령")')
    ap.add_argument("--skip-amendments", action="store_true", help="본문+별표만")
    ap.add_argument("--amendments-only", action="store_true", help="개정이력만")
    ap.add_argument("--limit", type=int, default=0, help="개정이력 최대 건수(테스트용)")
    ap.add_argument("--dry-run", action="store_true", help="jsonl 미변경, 요약만 출력")
    args = ap.parse_args()

    if not os.getenv("LAW_API_KEY"):
        sys.exit("LAW_API_KEY가 .env에 없습니다.")
    law_name = args.law.strip()

    if not args.amendments_only:
        print(f"=== 본문+별표 수집: {law_name} ===")
        law = fetch_law_bundle(law_name)
        basic = _basic_info(law)
        print(f"법령ID={basic['law_id']} / {basic['promulgation_no']} / 시행 {basic['enforcement_date']}")

        articles = build_article_records(law, law_name)
        short = [r for r in articles if len(r["content"]) < 40]
        print(f"조문 {len(articles)}건 (짧은조문<40자: {len(short)})")
        replace_in_jsonl(ARTICLES_PATH, law_name, articles, args.dry_run, "본문")

        byeolpyo = build_byeolpyo_records(law, law_name)
        n_tables = len({r["byeolpyo_no"] for r in byeolpyo})
        print(f"별표 {n_tables}개 → 청크 {len(byeolpyo)}건")
        replace_in_jsonl(BYEOLPYO_PATH, law_name, byeolpyo, args.dry_run, "별표")

    if not args.skip_amendments:
        print(f"\n=== 개정이력 수집: {law_name} ===")
        if not os.getenv("GOOGLE_API_KEY"):
            sys.exit("GOOGLE_API_KEY가 .env에 없습니다 (enrich에 필요).")
        history = fetch_history(law_name)
        print(f"일부+전부개정 {len(history)}건 (타법개정 제외, 공포번호 dedupe)")
        amendments = build_amendment_records(law_name, history, limit=args.limit)
        if args.limit:
            print(f"[개정이력] --limit={args.limit} 테스트 모드 — jsonl 반영 생략 "
                  f"(체크포인트에만 저장)")
        else:
            replace_in_jsonl(AMENDMENTS_PATH, law_name, amendments, args.dry_run, "개정이력")

    print("\n완료. 반영했다면: 로컬 검증 → 커밋/push → 배포 재인덱싱은 "
          "REINDEX_AUX(개정이력만) 또는 FORCE_REINDEX(본문·별표 포함).")


if __name__ == "__main__":
    main()
