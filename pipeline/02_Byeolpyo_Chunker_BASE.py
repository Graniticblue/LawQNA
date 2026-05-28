"""
02_Byeolpyo_Chunker.py

별표 PDF → JSONL 변환기
법제처에서 다운로드한 별표 PDF를 청킹하여
RAG 인덱스에 바로 쓸 수 있는 JSONL로 변환한다.

청킹 전략:
  - 섹션분리형: 복잡하고 긴 별표 (건축법 별표1, 소방시설법 별표4 등)
               → 최상위 번호(1. 2. 3. ...)별로 분리
  - 단일청크형: 짧은 별표 (국토계획법 별표2~25 등)
               → 별표 전체를 1개 청크로
"""

import re
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional
import pdfplumber

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────

BYEOLPYO_DIR = Path(r"D:\Workspace(0309 RAG)\별표")
OUTPUT_DIR   = Path(r"D:\Workspace(0309 RAG)\data\raw_laws\byeolpyo")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────
# 법령 메타데이터 매핑
# 파일명 내 법령명(부분) → (정규 법령명, 법령구분, ID접두어)
# ──────────────────────────────────────────────

LAW_META: list[tuple[str, str, str, str]] = [
    # (매칭키워드, 정규법령명, 법령구분, ID접두어)
    ("건축법 시행령",
     "건축법 시행령", "대통령령", "BLDG_SIR"),

    # 국토계획법: 파일명 잘림 대비 다양한 키워드 등록
    ("국토의 계획 및 이용에 관한 법률 시행령",
     "국토의 계획 및 이용에 관한 법률 시행령", "대통령령", "LAND_SIR"),
    ("국토의계획및이용에관한법률시행령",        # 파일명 잘림 시 붙여쓰기 형태
     "국토의 계획 및 이용에 관한 법률 시행령", "대통령령", "LAND_SIR"),
    ("국토의 계획 및 이용에 관한 법",           # 파일명이 잘려 뒷부분 없는 경우
     "국토의 계획 및 이용에 관한 법률 시행령", "대통령령", "LAND_SIR"),

    ("소방시설 설치 및 관리에 관한 법률 시행령",
     "소방시설 설치 및 관리에 관한 법률 시행령", "대통령령", "FIRE_SIR"),

    ("편의증진 보장에 관한 법률 시행령",
     "장애인·노인·임산부 등의 편의증진 보장에 관한 법률 시행령",
     "대통령령", "DISAB_SIR"),

    ("피난",
     "건축물의 피난·방화구조 등의 기준에 관한 규칙", "부령", "ESCAPE_RULE"),
]


# ──────────────────────────────────────────────
# 데이터 모델
# ──────────────────────────────────────────────

@dataclass
class ByeolpyoChunk:
    law_id:           str
    law_name:         str
    law_type:         str
    article_no:       str   # "별표1", "별표1의2" 등
    article_title:    str   # "용도별 건축물의 종류"
    content:          str
    enforcement_date: str   # "20251001" 형식
    source_url:       str
    is_byeolpyo:      bool = True
    byeolpyo_no:      str  = ""   # "1", "1의2", "2" 등
    related_article:  str  = ""   # "제3조의5"
    chunk_seq:        int  = 0    # 같은 별표 내 순서
    section_title:    str  = ""   # "단독주택", "소화설비" 등


# ──────────────────────────────────────────────
# 파일명 파서
# 형식: [별표 N] 제목(관련조문)(법령명)-버전.pdf
# ──────────────────────────────────────────────

def parse_filename(fname: str) -> dict:
    """파일명에서 별표번호·제목·관련조문·법령명 추출"""
    # 버전 접미사 제거 (-2, -3 등)
    base = re.sub(r'-\d+\.pdf$', '.pdf', fname)
    base = base.replace('.pdf', '').strip()

    # 별표 번호 추출: [별표 1] 또는 [별표 1의2]
    m_no = re.match(r'\[별표\s+([\d의\s]+)\]', base)
    byeolpyo_no = m_no.group(1).replace(' ', '') if m_no else ""

    # 괄호 내용 전체 추출
    parens = re.findall(r'\(([^)]+)\)', base)

    # 관련 조문 (제X조 패턴 포함)
    related_article = ""
    law_name_raw = ""
    for p in parens:
        if re.search(r'제\d+조', p):
            related_article = re.sub(r'\s*관련\s*$', '', p).strip()
        elif any(kw in p for kw in ['법률', '시행령', '시행규칙', '규칙', '건축법']):
            law_name_raw = p.strip()

    # 별표 제목: "] " 이후 ~ 첫 "(" 이전
    m_title = re.search(r'\]\s*(.+?)\s*\(', base)
    article_title = m_title.group(1).strip() if m_title else ""

    return {
        'byeolpyo_no':    byeolpyo_no,
        'article_no':     f"별표{byeolpyo_no}" if byeolpyo_no else "별표",
        'article_title':  article_title,
        'related_article': related_article,
        'law_name_raw':   law_name_raw,
    }


def resolve_law_meta(law_name_raw: str) -> tuple[str, str, str]:
    """법령명 원문 → (정규 법령명, 법령구분, ID접두어)"""
    # ㆍ(U+318D) ↔ ·(U+00B7) 정규화
    normalized = law_name_raw.replace('ㆍ', '·')
    for keyword, name, ltype, prefix in LAW_META:
        if keyword in normalized or keyword in law_name_raw:
            return name, ltype, prefix
    return law_name_raw, "대통령령", "UNKNOWN"


# ──────────────────────────────────────────────
# PDF 텍스트 추출
# ──────────────────────────────────────────────

def extract_text(pdf_path: Path) -> tuple[str, str, str]:
    """
    PDF 전문 텍스트 + 시행일자 + PDF 헤더에서 추출한 법령명 반환
    Returns: (full_text, enforcement_date, law_name_from_header)
    """
    pages = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                pages.append(t)
    full_text = "\n".join(pages)

    # 시행일자 추출 예: <개정 2025. 10. 1.>
    m = re.search(r'<(?:개정|제정|시행)\s+(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.>', full_text)
    enf_date = ""
    if m:
        y, mo, d = m.groups()
        enf_date = f"{y}{int(mo):02d}{int(d):02d}"

    # PDF 첫 줄 "■ 법령명 [별표 N]" 에서 법령명 추출 (파일명 잘림 대비)
    law_name_header = ""
    header_m = re.search(r'■\s*(.+?)\s*\[별표', full_text)
    if header_m:
        law_name_header = header_m.group(1).strip()

    return full_text, enf_date, law_name_header


# ──────────────────────────────────────────────
# 청킹 전략
# ──────────────────────────────────────────────

def _split_by_top_number(text: str) -> list[tuple[str, str]]:
    """
    최상위 번호(1. 2. 3. / 1의2. 등)를 기준으로 섹션 분리.
    비고 섹션은 마지막에 별도 청크로 추가.
    """
    lines = text.split('\n')

    # 비고 섹션 분리
    bigo_idx = None
    for i, ln in enumerate(lines):
        if ln.strip() == '비고':
            bigo_idx = i
            break

    main_lines = lines[:bigo_idx] if bigo_idx else lines
    bigo_lines = lines[bigo_idx:] if bigo_idx else []
    main_text  = '\n'.join(main_lines)

    # 최상위 번호 위치 탐지: 줄 시작 + "숫자(의숫자)." + 공백
    TOP = re.compile(r'^(\d+(?:의\d+)?)\.\s+', re.MULTILINE)
    matches = list(TOP.finditer(main_text))

    if not matches:
        result = [("전체", text.strip())]
        if bigo_lines:
            result.append(("비고", '\n'.join(bigo_lines).strip()))
        return result

    sections = []
    for i, m in enumerate(matches):
        start = m.start()
        end   = matches[i + 1].start() if i + 1 < len(matches) else len(main_text)
        chunk = main_text[start:end].strip()

        # 제목: 첫 줄에서 숫자 제거 후 대괄호([) 이전까지
        first_line = chunk.split('\n')[0]
        t = re.match(r'\d+(?:의\d+)?\.\s+(.+?)(?:\s*[\[（]|$)', first_line)
        title = t.group(1).strip() if t else first_line.strip()

        sections.append((title, chunk))

    if bigo_lines:
        sections.append(("비고", '\n'.join(bigo_lines).strip()))

    return sections


def _single_chunk(text: str) -> list[tuple[str, str]]:
    """전체를 1개 청크로 반환"""
    return [("전체", text.strip())]


# ──────────────────────────────────────────────
# 청킹 전략 라우터
# ──────────────────────────────────────────────

# (법령 키워드, 별표번호 또는 None) → 청킹 함수
_STRATEGY_MAP: list[tuple[str, Optional[str], callable]] = [
    # 건축법 시행령 별표1: 용도별 건축물 29개 호
    ("건축법 시행령",   "1",    _split_by_top_number),
    # 건축법 시행령 별표3: 특별건축구역 특례
    ("건축법 시행령",   "3",    _split_by_top_number),

    # 소방시설법 별표2: 특정소방대상물 (대분류 다수)
    ("소방시설",        "2",    _split_by_top_number),
    # 소방시설법 별표4: 소방시설 종류 (5대 분류)
    ("소방시설",        "4",    _split_by_top_number),

    # 장애인편의법 별표2: 대상시설별 편의시설 기준
    ("편의증진",        "2",    _split_by_top_number),

    # 피난방화규칙 별표1: 내화구조 성능기준
    ("피난",            "1",    _split_by_top_number),

    # 국토계획법 시행령 전부: 용도지역별 목록 (짧음)
    ("국토",            None,   _single_chunk),
]


def get_strategy(law_name: str, byeolpyo_no: str) -> callable:
    for law_kw, no, fn in _STRATEGY_MAP:
        if law_kw in law_name:
            if no is None or no == byeolpyo_no:
                return fn
    return _single_chunk   # 기본값


# ──────────────────────────────────────────────
# PDF 1개 처리
# ──────────────────────────────────────────────

def process_pdf(pdf_path: Path) -> list[ByeolpyoChunk]:
    fname = pdf_path.name
    meta  = parse_filename(fname)
    law_name, law_type, id_prefix = resolve_law_meta(meta['law_name_raw'])

    print(f"  법령: {law_name} | 별표{meta['byeolpyo_no']}", end="")

    # 텍스트 추출
    try:
        full_text, enf_date, law_name_header = extract_text(pdf_path)
    except Exception as e:
        print(f"\n  [ERROR] extraction failed: {e}")
        return []

    if not full_text.strip():
        print(f"\n  [WARN] empty text (image-based PDF)")
        return []

    # 법령명 fallback: 파일명 파싱 실패 시 PDF 헤더에서 보완
    if not law_name or law_name == meta['law_name_raw']:
        resolved, lt, pfx = resolve_law_meta(law_name_header)
        if pfx != "UNKNOWN":
            law_name, law_type, id_prefix = resolved, lt, pfx
        elif law_name_header:
            law_name = law_name_header   # 그래도 헤더값 사용

    law_id = f"{id_prefix}_별표{meta['byeolpyo_no']}"

    # 청킹 전략 선택 및 실행
    strategy = get_strategy(law_name, meta['byeolpyo_no'])
    sections = strategy(full_text)

    source_url = (
        f"https://www.law.go.kr/법령/{law_name.replace(' ', '')}/"
        f"별표{meta['byeolpyo_no']}"
    )

    chunks = []
    for seq, (section_title, section_content) in enumerate(sections, start=1):
        chunks.append(ByeolpyoChunk(
            law_id           = law_id,
            law_name         = law_name,
            law_type         = law_type,
            article_no       = meta['article_no'],
            article_title    = meta['article_title'],
            content          = section_content,
            enforcement_date = enf_date,
            source_url       = source_url,
            is_byeolpyo      = True,
            byeolpyo_no      = meta['byeolpyo_no'],
            related_article  = meta['related_article'],
            chunk_seq        = seq,
            section_title    = section_title,
        ))

    print(f"  → {len(chunks)}청크")
    return chunks


# ──────────────────────────────────────────────
# 전체 처리
# ──────────────────────────────────────────────

def process_all(byeolpyo_dir: Path = BYEOLPYO_DIR) -> tuple[list[ByeolpyoChunk], dict]:
    pdf_files = sorted(byeolpyo_dir.glob("*.pdf"))
    print(f"PDF files found: {len(pdf_files)}\n")

    all_chunks: list[ByeolpyoChunk] = []
    stats: dict[str, int] = {}

    for pdf_path in pdf_files:
        print(f"[{pdf_path.name[:60]}]")
        chunks = process_pdf(pdf_path)
        if chunks:
            key = f"{chunks[0].law_name} | 별표{chunks[0].byeolpyo_no}"
            stats[key] = stats.get(key, 0) + len(chunks)
            all_chunks.extend(chunks)

    return all_chunks, stats


def save_jsonl(chunks: list[ByeolpyoChunk], output_path: Path):
    with open(output_path, 'w', encoding='utf-8') as f:
        for chunk in chunks:
            f.write(json.dumps(asdict(chunk), ensure_ascii=False) + '\n')
    print(f"\n[SAVED] {output_path}  ({len(chunks):,} chunks)")


# ──────────────────────────────────────────────
# 실행
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Byeolpyo PDF Chunking Start")
    print("=" * 60 + "\n")

    all_chunks, stats = process_all()

    output_path = OUTPUT_DIR / "byeolpyo_chunks.jsonl"
    save_jsonl(all_chunks, output_path)

    # 통계 파일로 저장
    stats_path = OUTPUT_DIR / "byeolpyo_stats.txt"
    with open(stats_path, 'w', encoding='utf-8') as f:
        f.write("별표별 청크 수\n")
        f.write("=" * 70 + "\n")
        for key, cnt in sorted(stats.items()):
            f.write(f"  {key:<60s}  {cnt:4d}개\n")
        f.write(f"\n  {'합계':<60s}  {sum(stats.values()):4d}개\n")
    print(f"[STATS] {stats_path}")

    # 샘플 (건축법 시행령 별표1)
    sample_chunks = [c for c in all_chunks if "건축법 시행령" in c.law_name and c.byeolpyo_no == "1"]
    if sample_chunks:
        sample_path = OUTPUT_DIR / "sample_bldg_byeolpyo1.json"
        s = asdict(sample_chunks[0])
        s['content'] = s['content'][:400] + "..."
        with open(sample_path, 'w', encoding='utf-8') as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
        print(f"[SAMPLE] {sample_path}")
