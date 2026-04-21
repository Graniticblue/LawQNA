"""
enrich_법제처.py

data/qa_precedents/updates/ 의 JSONL을 읽어
Claude로 두 단계 분석을 수행합니다.

[단계 1] 기본 보강 (기존 동일)
  relation_type, label_summary, logic_steps, search_tags

[단계 2] 심층 분석 (신규)
  doc_analysis:
    cause_analysis  : 질문 원인 분석 (왜 이 질문이 발생했는가)
    legal_logic     : 법리적 판단 로직 (단계별 근거)
    key_provisions  : 핵심 적용 조문
  article_role_hints → data/article_roles/*.json 자동 생성/갱신

사용법:
  python enrich_법제처.py              # updates/ 전체 처리
  python enrich_법제처.py --run-index  # 보강 후 인덱서 자동 실행
  python enrich_법제처.py --no-roles   # article_roles 생성 건너뜀
"""

import json
import os
import re
import argparse
import subprocess
from pathlib import Path

# .env 로드
_env_path = Path(".env")
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

UPDATES_DIR      = Path("data/qa_precedents/updates")
ARTICLE_ROLES_DIR = Path("data/article_roles")
MODEL_NAME       = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# ============================================================
# 프롬프트 1: 기본 보강 (relation_type, logic_steps, search_tags)
# ============================================================

ENRICH_PROMPT = """\
아래는 법제처 법령해석례입니다. 이 Q&A를 분석하여 JSON만 출력하세요.

【질의요지】
{question}

【회답 및 이유】
{answer}

---
출력 형식 (JSON만, 설명 없이):
{{
  "relation_type": "DEF_EXP | SCOPE_CL | REQ_INT | EXCEPT | INTER_ART | PROC_DISC | SANC_SC 중 하나",
  "relation_name": "한글 유형명 (예: 적용범위확정형)",
  "label_summary": "이 해석례의 핵심 결론 1~2문장",
  "search_tags": "#태그1 #태그2 #태그3 ... (검색에 유용한 핵심 키워드 5~8개)",
  "logic_steps": [
    {{"seq": 1, "role": "ANCHOR|ANALYSIS|PREREQUISITE|RESOLUTION", "title": "단계 제목"}},
    {{"seq": 2, "role": "...", "title": "..."}}
  ]
}}

relation_type 기준:
  DEF_EXP   : "~에 ~도 포함되는가?" (법 용어·개념 범위)
  SCOPE_CL  : "~에도 ~이 적용되는가?" (조문 적용 경계)
  REQ_INT   : "~의 요건을 충족하는가?" (요건 충족 여부)
  EXCEPT    : "~임에도 예외가 인정되는가?" (예외·특례)
  INTER_ART : "어느 조문이 우선하는가?" (조문 간 충돌)
  PROC_DISC : "재량 범위 또는 절차는?" (허가권자 재량)
  SANC_SC   : "위반 시 제재는?" (벌칙·제재)
"""

# ============================================================
# 프롬프트 2: 심층 분석 (doc_analysis + article_role_hints)
# ============================================================

DEEP_ANALYSIS_PROMPT = """\
아래는 법제처 법령해석례입니다. 심층 분석을 수행하여 JSON만 출력하세요.

【질의요지】
{question}

【회답 및 이유】
{answer}

---
출력 형식 (JSON만, 설명 없이):
{{
  "cause_analysis": "이 질문이 발생한 원인 1~2문장 (문언 중의성/입법 공백/개념 모호성 등 유형 명시)",
  "legal_logic": [
    {{
      "seq": 1,
      "role": "ANCHOR|ANALYSIS|PREREQUISITE|RESOLUTION",
      "title": "단계 제목",
      "content": "이 단계의 법리적 근거 1~2문장",
      "provisions": ["건축법 제XX조", "건축법 시행령 제XX조"]
    }}
  ],
  "key_provisions": ["건축법 제XX조제X항", ...],
  "article_role_hints": [
    {{
      "article_id": "건축법시행령_제86조제2항제1호",
      "law": "건축법 시행령",
      "article_no": "제86조제2항제1호",
      "article_summary": "조문 한 줄 요약",
      "article_type": "면제조항|의무조항|정의조항|절차조항|제재조항 중 하나",
      "requirements": [
        {{
          "req_id": "A",
          "text": "요건 문구",
          "role": "보호메커니즘|수혜자격요건|절차요건|정량기준|용도정의 중 하나",
          "role_reason": "이 요건의 역할을 1문장으로",
          "protected_interest": "보호 법익 (보호메커니즘인 경우만, 나머지는 null)"
        }}
      ],
      "interpretation_logic": "이 조문의 전체 해석 원칙 1~2문장",
      "penal_connection": {{
        "connected": true,
        "basis": "형사처벌 근거 조문 (연결 없으면 null)",
        "implication": "죄형법정주의 관련 함의 (연결 없으면 null)"
      }}
    }}
  ]
}}

article_role_hints 작성 주의사항:
- 이 해석례에서 핵심적으로 해석된 조문만 포함하세요 (모든 언급 조문 포함 불요)
- requirements는 해당 조문에 나열된 요건 각각의 '역할'을 분류하세요
  · 보호메커니즘: 법익을 실질적으로 보호하는 요건 (예: 20m 도로 = 일조 완충)
  · 수혜자격요건: 혜택 대상 지역·주체를 한정하는 관문 조건 (예: 지구단위계획구역)
  · 절차요건: 행정 절차 이행 조건
  · 정량기준: 수치로 명확히 정해진 기준
  · 용도정의: 시설 분류·용도 귀속 판단
- article_role_hints가 없으면 빈 배열 []

⚠ JSON 출력 규칙:
- 모든 문자열 값(content, role_reason 등)은 반드시 한 줄로 작성하세요 (개행 금지)
- JSON 키 이름에 한글 사용 금지
- JSON 외 다른 텍스트 출력 금지
"""


def _extract_json(raw: str) -> dict:
    """JSON 블록 추출 + 다단계 파싱 시도."""
    # 1. ```json ... ``` 블록 우선
    m = re.search(r'```json\s*(\{.*?\})\s*```', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass

    # 2. 첫 번째 { ... } 블록
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if not m:
        raise ValueError(f"JSON 블록 없음:\n{raw[:300]}")

    candidate = m.group()

    # 3. 직접 파싱
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # 4. JSON 문자열 값 내부의 개행을 공백으로 치환 후 재시도
    #    "((?:[^"\\]|\\.)*)" 패턴으로 JSON 문자열 전체를 매칭, 내부 개행만 제거
    def _fix_string_newlines(text: str) -> str:
        return re.sub(
            r'"((?:[^"\\]|\\.)*)"',
            lambda m: '"' + re.sub(r'[\n\r\t]', ' ', m.group(1)) + '"',
            text,
        )

    cleaned = _fix_string_newlines(candidate)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        # 5. 줄별 디버그: 실패 위치 주변 출력
        lines = cleaned.splitlines()
        err_line = e.lineno - 1
        debug_lines = lines[max(0, err_line-2):err_line+3]
        debug_ctx = "\n".join(f"  {i+max(0,err_line-2)+1}: {l}" for i, l in enumerate(debug_lines))
        raise ValueError(f"JSON 파싱 최종 실패: {e}\n{debug_ctx}")


def call_claude(prompt: str, max_tokens: int = 800) -> dict:
    try:
        import anthropic
    except ImportError:
        raise SystemExit("pip install anthropic 필요")

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY 환경변수 없음")

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    # DEBUG: 실패 시 원본 저장
    try:
        return _extract_json(raw)
    except Exception:
        Path("debug_raw_response.txt").write_text(raw, encoding="utf-8")
        raise


# ============================================================
# article_roles JSON 생성/갱신
# ============================================================

def save_article_roles(hints: list[dict], source_ref: str):
    """
    article_role_hints를 data/article_roles/*.json으로 저장.
    기존 파일이 있으면 덮어쓰지 않고 출처 정보만 보강.
    """
    ARTICLE_ROLES_DIR.mkdir(parents=True, exist_ok=True)

    for hint in hints:
        article_id = hint.get("article_id", "")
        if not article_id:
            continue

        fpath = ARTICLE_ROLES_DIR / f"{article_id}.json"

        # 기존 파일이 있으면 스킵 (수동 편집 내용 보호)
        if fpath.exists():
            print(f"  [SKIP] article_roles 기존 파일 존재: {fpath.name}")
            continue

        # source 태깅
        role_source = {"type": "해석례", "ref": source_ref, "point": "자동 추출"}
        for req in hint.get("requirements", []):
            if "role_sources" not in req:
                req["role_sources"] = [role_source]

        hint.setdefault("interpretation_sources", [role_source])
        hint["last_updated"] = "자동생성"
        hint["last_updated_by"] = source_ref

        fpath.write_text(json.dumps(hint, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [NEW] article_roles 생성: {fpath.name}")


# ============================================================
# 파일 처리
# ============================================================

def enrich_file(jsonl_path: Path, skip_roles: bool = False) -> bool:
    print(f"\n처리 중: {jsonl_path.name}")
    lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
    updated = []

    for line in lines:
        rec = json.loads(line)
        question = rec["contents"][0]["parts"][0]["text"]
        answer   = rec["contents"][1]["parts"][0]["text"]

        # ── 단계 1: 기본 보강 ──────────────────────────
        try:
            p1 = ENRICH_PROMPT.format(question=question[:1500], answer=answer[:2000])
            basic = call_claude(p1, max_tokens=800)
        except Exception as e:
            print(f"  [FAIL-기본보강] {e}")
            updated.append(rec)
            continue

        search_tags = basic.get("search_tags", "")
        if search_tags and "[검색태그]" not in answer:
            rec["contents"][1]["parts"][0]["text"] = answer + f"\n\n[검색태그] {search_tags}"

        rec["relation_type"] = basic.get("relation_type", rec.get("relation_type", "SCOPE_CL"))
        rec["relation_name"] = basic.get("relation_name", rec.get("relation_name", ""))
        rec["label_summary"] = basic.get("label_summary", rec.get("label_summary", ""))
        rec["logic_steps"]   = basic.get("logic_steps",   rec.get("logic_steps", []))
        rec["search_tags"]   = search_tags

        print(f"  relation_type : {rec['relation_type']}")
        print(f"  search_tags   : {search_tags[:70]}")

        # ── 단계 2: 심층 분석 ──────────────────────────
        try:
            p2 = DEEP_ANALYSIS_PROMPT.format(question=question[:1500], answer=answer[:2000])
            deep = call_claude(p2, max_tokens=4096)
        except Exception as e:
            print(f"  [FAIL-심층분석] {e}")
            updated.append(rec)
            continue

        rec["doc_analysis"] = {
            "cause_analysis":  deep.get("cause_analysis", ""),
            "legal_logic":     deep.get("legal_logic", []),
            "key_provisions":  deep.get("key_provisions", []),
        }
        print(f"  cause_analysis: {rec['doc_analysis']['cause_analysis'][:80]}")
        print(f"  legal_logic   : {len(rec['doc_analysis']['legal_logic'])}단계")

        # ── article_roles 생성 ─────────────────────────
        hints = deep.get("article_role_hints", [])
        if hints and not skip_roles:
            # source_ref: 파일명에서 추출 (예: 법제처_14-0840 → 법제처 해석례 14-0840)
            stem = jsonl_path.stem.replace("_", " ")
            save_article_roles(hints, source_ref=stem)
        elif hints:
            print(f"  [SKIP] article_roles 생성 건너뜀 (--no-roles)")

        updated.append(rec)

    with open(jsonl_path, "w", encoding="utf-8") as f:
        for r in updated:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"  저장 완료: {jsonl_path}")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-index", action="store_true",
                        help="보강 후 인덱서 자동 실행")
    parser.add_argument("--no-roles", action="store_true",
                        help="article_roles JSON 생성 건너뜀")
    args = parser.parse_args()

    files = sorted(UPDATES_DIR.glob("*.jsonl"))
    if not files:
        print(f"처리할 파일 없음: {UPDATES_DIR}")
        return

    print(f"대상 파일: {len(files)}개")
    for f in files:
        enrich_file(f, skip_roles=args.no_roles)

    print("\n보강 완료")

    if args.run_index:
        print("\n인덱서 실행 중...")
        subprocess.run(["python", "chunk_법제처.py"], check=True)
        print("인덱싱 완료")
    else:
        print("\n인덱싱 반영하려면:")
        print("  python chunk_법제처.py")


if __name__ == "__main__":
    main()
