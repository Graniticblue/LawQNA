#!/usr/bin/env python3
"""
chainlit_app.py -- 건축법규 AI 자문 시스템 (Chainlit 인터페이스)

PDF 업로드 → 백그라운드 임베딩 → 세션 전용 ChromaDB 컬렉션 → 기존 law_articles와 동시 검색
"""

import asyncio
import importlib.util
import re
import sys
from pathlib import Path

import chainlit as cl

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))


# ── Generator 싱글턴 ────────────────────────────────────────

_generator_instance = None


def get_generator():
    global _generator_instance
    if _generator_instance is None:
        spec = importlib.util.spec_from_file_location(
            "generator_mod", BASE_DIR / "06_Generator.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _generator_instance = mod.Generator()
    return _generator_instance


# ── PDF 파싱 ────────────────────────────────────────────────

def parse_pdf(path: str) -> str:
    """PDF 파일에서 텍스트 추출 (PyMuPDF 우선, pdfplumber 폴백)."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(path)
        pages = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(pages)
    except Exception:
        pass
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception:
        return ""


# ── PDF 청킹 ────────────────────────────────────────────────

def chunk_law_pdf(text: str, law_name: str) -> list[dict]:
    """법령 PDF 텍스트를 제XX조 단위로 청킹."""
    # 제XX조 패턴으로 분리
    pattern = r'(?=제\d+조(?:의\d+)?[\s(（])'
    parts = re.split(pattern, text)
    chunks = []
    for part in parts:
        part = part.strip()
        if not part or len(part) < 20:
            continue
        # 조문 번호 추출
        m = re.match(r'(제\d+조(?:의\d+)?)', part)
        article_no = m.group(1) if m else f"chunk_{len(chunks)}"
        chunks.append({
            "law_name": law_name,
            "article_no": article_no,
            "content": part[:2000],
        })
    # 청킹 실패 시 전체를 500자 단위로 분할
    if not chunks:
        for i in range(0, len(text), 500):
            chunks.append({
                "law_name": law_name,
                "article_no": f"p{i // 500 + 1}",
                "content": text[i:i + 500],
            })
    return chunks


# ── 인라인 인용 마커 파싱 ───────────────────────────────────

def build_citation_elements(answer: str, result: dict) -> tuple[str, list]:
    """
    답변 텍스트의 [법령N], [해석례N], [판례N] 마커를 파싱하여
    cl.Text(display="side") 요소 리스트를 반환.
    """
    law_docs   = result.get("law_docs",  [])
    qa_docs    = result.get("qa_docs",   [])
    case_docs  = result.get("case_docs", [])

    elements: list = []
    seen: set[str] = set()

    for m in re.finditer(r'\[(법령|해석례|판례)(\d+)\]', answer):
        kind = m.group(1)
        idx  = int(m.group(2)) - 1   # 0-based
        name = f"{kind}{m.group(2)}"

        if name in seen:
            continue
        seen.add(name)

        doc = None
        if kind == "법령"   and 0 <= idx < len(law_docs):
            doc = law_docs[idx]
        elif kind == "해석례" and 0 <= idx < len(qa_docs):
            doc = qa_docs[idx]
        elif kind == "판례"  and 0 <= idx < len(case_docs):
            doc = case_docs[idx]

        if doc is None:
            continue

        content = f"**{doc.law_name}  {doc.article_no}**\n\n{doc.content}"
        elements.append(cl.Text(name=name, content=content, display="side"))

    return answer, elements


# ── [출처 요약] 분리 ─────────────────────────────────────────

def split_answer(raw: str) -> tuple[str, str]:
    m = re.search(r'\[출처 요약\]', raw)
    if m:
        return raw[: m.start()].rstrip(), raw[m.start():]
    return raw, ""


# ── 출처 배지 텍스트 ─────────────────────────────────────────

def format_sources(source_info: dict) -> str:
    badges = []
    if source_info.get("db_law"):
        badges.append(f"📋 **조문** {source_info['db_law_detail']}")
    if source_info.get("db_qa"):
        badges.append(f"📌 **해석례** {source_info['db_qa_detail']}")
    if source_info.get("db_amendment"):
        badges.append(f"📖 **입법요지** {source_info['db_amendment_detail']}")
    if source_info.get("internal"):
        badges.append(f"💡 **내장지식** {source_info['internal_detail']}")
    return "\n".join(badges)


# ── 내장 법령 목록 ───────────────────────────────────────────

LAW_DB_INFO = """\
### 📋 내장 법령 데이터베이스

**건축법 계열** — DB 반영일 2026.04.21 · 개정이력 2018.06 ~ 2026.02 (61건)

| 법령 | 현행 시행일 | 개정이력 |
|------|-----------|---------|
| 건축법 | 2026.02.27 | 2018.08 ~ 2025.08 (18건) |
| 건축법 시행령 | 2025.08.26 | 2018.06 ~ 2025.08 (26건) |
| 건축법 시행규칙 | 2026.02.27 | 2018.06 ~ 2026.02 (17건) |

**국토계획법 계열** — DB 반영일 2026.04.21 · 개정이력 2023.07 ~ 2025.12 (9건)

| 법령 | 현행 시행일 | 개정이력 |
|------|-----------|---------|
| 국토의 계획 및 이용에 관한 법률 | 2025.10.01 | 2024.02 ~ 2025.12 (2건) |
| 국토의 계획 및 이용에 관한 법률 시행령 | 2025.07.01 | 2023.07 ~ 2025.07 (6건) |
| 국토의 계획 및 이용에 관한 법률 시행규칙 | 2025.12.26 | 2024.05 (1건) |

**주택법 계열** — DB 반영일 2026.04.21 · 개정이력 미구축

| 법령 | 현행 시행일 |
|------|-----------|
| 주택법 | 2026.08.04 |
| 주택법 시행령 | 2025.12.30 |
| 주택법 시행규칙 | 2024.08.02 |

**기타 내장 법령** — DB 반영일 2026.04.21 · 개정이력 미구축

건설산업기본법 · 건축물관리법 · 건축물의 피난·방화구조 등의 기준에 관한 규칙 · 건축물의 설비기준 등에 관한 규칙 · 소방시설 설치 및 관리에 관한 법률 · 소방시설 설치 및 관리에 관한 법률 시행령 · 장애인·노인·임산부 등의 편의증진 보장에 관한 법률 · 주택건설기준 등에 관한 규정

---
📌 내장 DB에 없는 법령은 PDF를 첨부하시면 실시간으로 분석에 활용됩니다.\
"""

_LAW_LIST_TRIGGER = "📋 내장 법령 목록"


# ── Chainlit 핸들러 ─────────────────────────────────────────

@cl.set_starters
async def set_starters():
    return [
        cl.Starter(
            label="📋 내장 법령 목록",
            message=_LAW_LIST_TRIGGER,
            icon="/public/starter_list.svg",
        ),
    ]


@cl.on_chat_start
async def on_start():
    cl.user_session.set("uploaded_law", "")
    cl.user_session.set("pdf_ready", False)  # 임베딩 완료 여부

    # 세션 컬렉션 미리 생성
    session_id = cl.context.session.id
    gen = get_generator()
    retriever = gen._get_retriever()
    retriever.create_session_collection(session_id)
    cl.user_session.set("session_id", session_id)



@cl.on_message
async def on_message(message: cl.Message):
    # ── 법령 목록 트리거 ──────────────────────────────────────
    if message.content.strip() == _LAW_LIST_TRIGGER:
        await cl.Message(content=LAW_DB_INFO).send()
        return

    # ── PDF 첨부 처리 ─────────────────────────────────────────
    if message.elements:
        for elem in message.elements:
            if not hasattr(elem, "path") or not elem.path:
                continue
            name = getattr(elem, "name", "업로드 법령")
            if not name.lower().endswith(".pdf"):
                continue

            law_label = name.replace(".pdf", "").replace(".PDF", "")

            # 파싱 알림
            parsing_msg = cl.Message(content=f"**{law_label}** 파싱 중…")
            await parsing_msg.send()

            pdf_text = parse_pdf(elem.path)
            chunks = chunk_law_pdf(pdf_text, law_label)

            await parsing_msg.remove()

            # 백그라운드 임베딩
            indexing_msg = cl.Message(
                content=f"**{law_label}** 임베딩 중… ({len(chunks)}개 청크) 질문을 먼저 입력하셔도 됩니다."
            )
            await indexing_msg.send()

            session_id = cl.user_session.get("session_id", "")

            async def do_index(chunks=chunks, session_id=session_id, msg=indexing_msg, label=law_label):
                gen = get_generator()
                retriever = gen._get_retriever()
                n = await asyncio.to_thread(retriever.index_uploaded_chunks, session_id, chunks)
                cl.user_session.set("pdf_ready", True)
                await msg.remove()
                await cl.Message(
                    content=f"**{label}** 인덱싱 완료 ({n}개 청크). 이제 이 법령을 참고하여 답변합니다."
                ).send()

            asyncio.create_task(do_index())

    # ── 텍스트 질의 처리 ─────────────────────────────────────
    query = message.content.strip()
    if not query:
        return

    # extra_context 조합 (필요 시 확장 가능)
    extra_context = ""
    session_id = cl.user_session.get("session_id", "")

    thinking_msg = cl.Message(content="분석 중…")
    await thinking_msg.send()

    try:
        gen = get_generator()
        result = await asyncio.to_thread(
            gen.generate,
            query,
            False,
            extra_context,
            session_id,  # session_id 전달
        )
    except Exception as e:
        await thinking_msg.remove()
        await cl.Message(content=f"오류가 발생했습니다: {e}").send()
        return

    await thinking_msg.remove()

    raw_answer  = result.get("answer", "")
    source_info = result.get("source_info", {})
    if not isinstance(source_info, dict):
        source_info = {}

    # [출처 요약] 블록 분리
    body, _ = split_answer(raw_answer)

    # 인라인 인용 마커 → cl.Text 요소 생성
    body, cite_elements = build_citation_elements(body, result)

    # 본문 + 인라인 인용 요소 전송
    await cl.Message(content=body, elements=cite_elements).send()

    # 출처 요약 (있을 때만 별도 메시지)
    sources_text = format_sources(source_info)
    if sources_text:
        await cl.Message(content=f"**출처**\n{sources_text}", author="출처").send()


@cl.on_chat_end
async def on_end():
    session_id = cl.user_session.get("session_id", "")
    if session_id:
        gen = get_generator()
        retriever = gen._get_retriever()
        retriever.delete_session_collection(session_id)
