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


# ── Chainlit 핸들러 ─────────────────────────────────────────

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

    await cl.Message(
        content=(
            "**건축법규 AI 자문 시스템**에 오신 것을 환영합니다.\n\n"
            "건축법·국토계획법·주택법 관련 질의를 입력하시거나, "
            "참고할 법령 PDF를 첨부하시면 해당 내용을 함께 검토하여 답변드립니다."
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
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

    answer = result.get("answer", "")
    law_docs = result.get("law_docs", [])
    qa_docs = result.get("qa_docs", [])

    # 답변 전송
    await cl.Message(content=answer).send()

    # 검색 결과 요약 (Elements)
    elements = []

    if law_docs:
        law_lines = [f"**검색된 법령 조문 ({len(law_docs)}건)**\n"]
        for doc in law_docs[:5]:
            badge = "(직접참조)" if getattr(doc, "score_type", "") == "exact" else f"(유사도 {doc.score:.3f})"
            law_lines.append(f"- {doc.law_name} {doc.article_no} {badge}")
        elements.append(
            cl.Text(name="법령 조문", content="\n".join(law_lines), display="inline")
        )

    if qa_docs:
        qa_lines = [f"**유사 선례 ({len(qa_docs)}건)**\n"]
        for doc in qa_docs[:3]:
            ref = doc.metadata.get("doc_ref", "") or doc.metadata.get("doc_code", "")
            qa_lines.append(f"- {ref or doc.law_name} (유사도 {doc.score:.3f})")
        elements.append(
            cl.Text(name="유사 선례", content="\n".join(qa_lines), display="inline")
        )

    if elements:
        await cl.Message(content="", elements=elements).send()


@cl.on_chat_end
async def on_end():
    session_id = cl.user_session.get("session_id", "")
    if session_id:
        gen = get_generator()
        retriever = gen._get_retriever()
        retriever.delete_session_collection(session_id)
