#!/usr/bin/env python3
"""chainlit_app.py — 건축법규 AI (Chainlit UI)"""

import asyncio
import importlib.util
import io
import sys
from pathlib import Path

import chainlit as cl

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

# ── Generator 싱글톤 ─────────────────────────────────────────
_generator = None


def get_generator():
    global _generator
    if _generator is None:
        spec = importlib.util.spec_from_file_location(
            "Generator", BASE_DIR / "06_Generator.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _generator = mod.Generator()
    return _generator


# ── PDF 파싱 ─────────────────────────────────────────────────
def parse_pdf(path: str) -> str:
    try:
        import pdfplumber
        parts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    parts.append(t)
        return "\n".join(parts)
    except Exception as e:
        return f"[PDF 파싱 실패: {e}]"


# ── 대화 이력 → 컨텍스트 문자열 ─────────────────────────────
def history_to_context(history: list[dict]) -> str:
    if not history:
        return ""
    lines = ["[이전 대화 참고 — 연속 질의 시 맥락 유지]"]
    for h in history[-3:]:  # 최근 3턴
        lines.append(f"Q: {h['query']}")
        summary = h["answer"][:300].replace("\n", " ")
        lines.append(f"A: {summary}…")
    return "\n".join(lines)


# ── 출처 배지 텍스트 ─────────────────────────────────────────
def format_sources(source_info: dict) -> str:
    badges = []
    if source_info.get("db_law"):
        badges.append(f"📋 **조문** {source_info['db_law_detail']}")
    if source_info.get("db_qa"):
        badges.append(f"📌 **선례** {source_info['db_qa_detail']}")
    if source_info.get("db_amendment"):
        badges.append(f"📖 **입법요지** {source_info['db_amendment_detail']}")
    if source_info.get("internal"):
        badges.append(f"💡 **내장지식** {source_info['internal_detail']}")
    return "\n".join(badges)


# ── [출처 요약] 블록 제거 (본문에서 분리) ─────────────────────
def split_answer(raw: str) -> tuple[str, str]:
    import re
    m = re.search(r'\[출처 요약\]', raw)
    if m:
        return raw[: m.start()].rstrip(), raw[m.start():]
    return raw, ""


# ============================================================
# Chainlit 이벤트
# ============================================================

@cl.on_chat_start
async def on_start():
    cl.user_session.set("history", [])
    cl.user_session.set("uploaded_law", "")   # 누적 PDF 텍스트

    await cl.Message(
        content=(
            "## 건축법규 AI\n\n"
            "건축법·시행령·시행규칙 및 국토계획법 등 관련 법규에 대해 질의하세요.\n\n"
            "> **시스템에 없는 법령**은 PDF를 첨부하시면 해당 내용을 참고하여 답변합니다.\n"
            "> 이전 답변과 이어지는 질문도 그대로 입력하세요."
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    history: list[dict] = cl.user_session.get("history", [])
    uploaded_law: str = cl.user_session.get("uploaded_law", "")

    # ── PDF 첨부 처리 ─────────────────────────────────────────
    if message.elements:
        for elem in message.elements:
            if not hasattr(elem, "path") or not elem.path:
                continue
            name = getattr(elem, "name", "업로드 법령")
            if not name.lower().endswith(".pdf"):
                continue

            pdf_text = parse_pdf(elem.path)
            law_label = name.replace(".pdf", "").replace(".PDF", "")
            chunk = f"\n\n=== [{law_label}] ===\n{pdf_text}"
            # 토큰 과다 방지: 법령 1개당 최대 6000자
            uploaded_law += chunk[:6000]
            cl.user_session.set("uploaded_law", uploaded_law)

            await cl.Message(
                content=f"**{law_label}** PDF 업로드 완료. 이후 질문에 참고합니다."
            ).send()

    query = message.content.strip()
    if not query:
        return

    # ── extra_context 조합 ────────────────────────────────────
    parts = []
    hist_ctx = history_to_context(history)
    if hist_ctx:
        parts.append(hist_ctx)
    if uploaded_law:
        parts.append(f"[사용자 첨부 법령 전문]\n{uploaded_law}")
    extra_context = "\n\n".join(parts)

    # ── 답변 생성 ─────────────────────────────────────────────
    gen = get_generator()

    # 진행 메시지
    thinking = cl.Message(content="⏳ 법령 분석 중…")
    await thinking.send()

    try:
        result = await asyncio.to_thread(
            gen.generate,
            query,
            False,       # verbose
            extra_context,
        )
    except Exception as e:
        await thinking.remove()
        await cl.Message(content=f"⚠️ 오류가 발생했습니다: {e}").send()
        return

    await thinking.remove()

    # result 타입 보장
    if not isinstance(result, dict):
        await cl.Message(content=f"⚠️ 응답 형식 오류: {result}").send()
        return

    raw_answer   = result.get("answer", "답변 생성에 실패했습니다.")
    source_info  = result.get("source_info", {})
    if not isinstance(source_info, dict):
        source_info = {}
    body, _      = split_answer(raw_answer)
    sources_text = format_sources(source_info)

    # 본문 전송
    await cl.Message(content=body).send()

    # 출처 별도 전송 (있을 때만)
    if sources_text:
        await cl.Message(
            content=f"**출처**\n{sources_text}",
            author="출처",
        ).send()

    # 히스토리 업데이트
    history.append({"query": query, "answer": body})
    cl.user_session.set("history", history)
