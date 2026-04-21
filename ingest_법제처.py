"""
법제처 해석례 PDF → qa_precedents JSONL 변환 스크립트

사용법:
  python ingest_법제처.py              # add/ 폴더의 미처리 PDF 전체 처리 (Claude 분석 포함)
  python ingest_법제처.py --no-enrich  # Claude 분석 없이 원문만 저장
  python ingest_법제처.py --run-index  # 변환 후 인덱서 자동 실행

처리 흐름:
  add/*.pdf
    → 텍스트 추출 (PyMuPDF)
    → 섹션 파싱 (질의요지 / 회답 / 이유 / 관계법령)
    → [Claude] 검색태그 · relation_type · logic_steps 보강
    → data/qa_precedents/updates/{code}.jsonl 저장
    → 원본 PDF → data/raw_laws/ 이동
"""

import re
import json
import os
import shutil
import argparse
import subprocess
from pathlib import Path

import fitz  # PyMuPDF

# ─── .env 로드 ────────────────────────────────────────────────
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# ─── 경로 설정 ────────────────────────────────────────────────
ADD_DIR        = Path("add")
PROCESSED_DIR  = Path("data/raw_laws")
UPDATES_DIR    = Path("data/qa_precedents/updates")

MODEL_NAME = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")


# ─── PDF 텍스트 추출 ──────────────────────────────────────────
def extract_text(pdf_path: Path) -> str:
    doc = fitz.open(str(pdf_path))
    pages = [page.get_text("text") for page in doc]
    doc.close()
    return "\n".join(pages)


# ─── 섹션 파싱 ────────────────────────────────────────────────
SECTION_MARKERS = [
    "【질의요지】",
    "【회답】",
    "【이유】",
    "【관계 법령】",
    "【관계법령】",
    "【법제처 법령해석의 효력 등에 대한 안내】",
]

# · 마커 / 번호 마커 / <> 마커 형식 → 표준 마커 매핑 (일부 PDF에서 사용)
ALT_MARKERS = {
    # · 형식 (25-0877 등)
    "· 질의요지":  "【질의요지】",
    "· 회답":      "【회답】",
    "· 이유":      "【이유】",
    "· 관계 법령": "【관계 법령】",
    "· 관계법령":  "【관계법령】",
    # 번호 형식 (22-0411 등) — 줄바꿈 포함하여 오매칭 방지
    "\n1. 질의요지": "\n【질의요지】",
    "\n2. 회답":     "\n【회답】",
    "\n3. 이유":     "\n【이유】",
    # <> 형식
    "<관계 법령>":  "【관계 법령】",
    "<관계법령>":   "【관계법령】",
}

def parse_sections(text: str) -> dict:
    # 대체 마커 형식 → 표준 형식으로 치환
    for alt, std in ALT_MARKERS.items():
        text = text.replace(alt, std)

    positions = []
    for marker in SECTION_MARKERS:
        idx = text.find(marker)
        if idx != -1:
            positions.append((idx, marker))
    positions.sort(key=lambda x: x[0])

    sections = {}
    for i, (pos, marker) in enumerate(positions):
        start = pos + len(marker)
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        content = text[start:end].strip()
        content = re.sub(r'법제처\s+\d+\s+국가법령정보센터', '', content)
        content = re.sub(r'"[^"]*"\(법령해석례,[\d-]+\)', '', content)
        content = re.sub(r'\n{3,}', '\n\n', content)
        sections[marker] = content.strip()
    return sections


# ─── 메타데이터 추출 ──────────────────────────────────────────
def extract_metadata(text: str, filename: str) -> dict:
    m = re.search(
        r'\[(\d{2,4}-\d+),\s*([\d]{4}\.\s*\d{1,2}\.\s*\d{1,2}\.),\s*([^\]]+)\]',
        text
    )
    if m:
        code     = m.group(1).strip()
        raw_date = m.group(2).strip()
        agency   = m.group(3).strip()
    else:
        fm = re.search(r'(\d{2,4}-\d+)', filename)
        code     = fm.group(1) if fm else "unknown"
        agency   = "법제처"
        # 텍스트 앞부분에서 첫 번째 날짜 자동 감지 (회신일)
        dm2 = re.search(r'(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.', text[:500])
        raw_date = dm2.group(0) if dm2 else ""

    dm = re.match(r'(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?', raw_date)
    if dm:
        doc_date = f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"
        date_str = f"{dm.group(1)}. {int(dm.group(2))}. {int(dm.group(3))}."
    else:
        doc_date = ""
        date_str = ""

    doc_ref = f"[법제처 {date_str} 회신 {code}]" if date_str else f"[법제처 {code}]"
    return {
        "doc_code":   code,
        "doc_date":   doc_date,
        "doc_agency": "법제처",
        "doc_ref":    doc_ref,
    }


# ─── Claude 분석 보강 ─────────────────────────────────────────
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

def enrich_with_claude(question: str, answer: str) -> dict:
    """Claude로 검색태그·relation_type·logic_steps 생성"""
    try:
        import anthropic
    except ImportError:
        print("  [WARN] anthropic 패키지 없음 -기본값 사용")
        return {}

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("  [WARN] ANTHROPIC_API_KEY 없음 -기본값 사용")
        return {}

    client = anthropic.Anthropic(api_key=api_key)
    prompt = ENRICH_PROMPT.format(
        question=question[:1500],
        answer=answer[:2000],
    )

    try:
        response = client.messages.create(
            model=MODEL_NAME,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        # JSON 블록 추출
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception as e:
        print(f"  [WARN] Claude 분석 실패: {e}")

    return {}


# ─── JSONL 레코드 생성 ────────────────────────────────────────
def build_record(sections: dict, meta: dict, enriched: dict) -> dict:
    question    = sections.get("【질의요지】", "").strip()
    answer_head = sections.get("【회답】", "").strip()
    reasoning   = sections.get("【이유】", "").strip()
    law_refs    = sections.get("【관계 법령】", sections.get("【관계법령】", "")).strip()

    # 모델 답변: 법제처 원문 그대로
    answer_parts = []
    if answer_head:
        answer_parts.append(f"【회답】\n{answer_head}")
    if reasoning:
        answer_parts.append(f"【이유】\n{reasoning}")
    if law_refs:
        answer_parts.append(f"【관계 법령】\n{law_refs}")

    # 검색태그 포함 (검색 품질 향상)
    search_tags = enriched.get("search_tags", "")
    if search_tags:
        answer_parts.append(f"[검색태그] {search_tags}")

    answer_full = "\n\n".join(answer_parts)

    return {
        "contents": [
            {"role": "user",  "parts": [{"text": question}]},
            {"role": "model", "parts": [{"text": answer_full}]},
        ],
        "_orig_idx":     0,
        "relation_type": enriched.get("relation_type", "SCOPE_CL"),
        "relation_name": enriched.get("relation_name", "적용범위확정형"),
        "label_summary": enriched.get("label_summary", answer_head[:200]),
        "logic_steps":   enriched.get("logic_steps", []),
        "search_tags":   search_tags,
        "doc_ref":       meta["doc_ref"],
        "doc_agency":    meta["doc_agency"],
        "doc_code":      meta["doc_code"],
        "doc_date":      meta["doc_date"],
        "tag":           "법제처해석례",
    }


# ─── 메인 처리 ────────────────────────────────────────────────
def process_pdf(pdf_path: Path, enrich: bool = True) -> Path | None:
    print(f"\n처리 중: {pdf_path.name}")

    text = extract_text(pdf_path)
    if not text.strip():
        print("  [SKIP] 텍스트 추출 실패")
        return None

    sections = parse_sections(text)
    if not sections.get("【질의요지】"):
        print("  [SKIP] 【질의요지】 섹션 없음")
        return None

    meta = extract_metadata(text, pdf_path.name)

    enriched = {}
    if enrich:
        print("  Claude 분석 중...")
        question = sections.get("【질의요지】", "")
        answer   = sections.get("【회답】", "") + "\n" + sections.get("【이유】", "")
        enriched = enrich_with_claude(question, answer)
        if enriched:
            print(f"  relation_type: {enriched.get('relation_type')}")
            print(f"  search_tags:   {enriched.get('search_tags', '')[:60]}")

    record   = build_record(sections, meta, enriched)

    UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = UPDATES_DIR / f"법제처_{meta['doc_code']}.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"  doc_ref: {meta['doc_ref']}")
    print(f"  저장:    {out_path}")
    return out_path


def move_to_processed(pdf_path: Path):
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    shutil.move(str(pdf_path), str(PROCESSED_DIR / pdf_path.name))


def main():
    parser = argparse.ArgumentParser(description="법제처 해석례 PDF → qa_precedents JSONL")
    parser.add_argument("--no-enrich", action="store_true",
                        help="Claude 분석 없이 원문만 저장")
    parser.add_argument("--run-index", action="store_true",
                        help="변환 후 인덱서 자동 실행")
    args = parser.parse_args()

    pdf_files = sorted(ADD_DIR.glob("*.pdf"))
    if not pdf_files:
        print("add/ 폴더에 PDF 파일이 없습니다.")
        return

    print(f"발견된 PDF: {len(pdf_files)}개")
    enrich = not args.no_enrich
    if enrich:
        print(f"모드: Claude 분석 포함 (모델: {MODEL_NAME})")
    else:
        print("모드: 원문만 저장 (--no-enrich)")

    saved = []
    for pdf_path in pdf_files:
        out = process_pdf(pdf_path, enrich=enrich)
        if out:
            saved.append(out)
            move_to_processed(pdf_path)

    print(f"\n완료: {len(saved)}개 변환 → data/qa_precedents/updates/")

    if saved and args.run_index:
        print("\n인덱서 실행 중...")
        subprocess.run(["python", "02_Indexer_BASE.py", "--collection", "qa"], check=True)
        print("인덱싱 완료")
    elif saved:
        print("\n인덱싱 반영하려면:")
        print("  python 02_Indexer_BASE.py --collection qa")


if __name__ == "__main__":
    main()
