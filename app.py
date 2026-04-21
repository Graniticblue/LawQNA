#!/usr/bin/env python3
"""app.py — 건축법규 AI 자문 시스템"""

import importlib.util
import os
import re
import sys
from pathlib import Path

import streamlit as st

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

# ── 페이지 설정 ──────────────────────────────────────────────
st.set_page_config(
    page_title="건축법규 AI",
    page_icon="🏛",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── 디자인 시스템 ────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.8/dist/web/static/pretendard.css');

:root {
  --blue:      #3182F6;
  --blue-lt:   #EBF3FE;
  --blue-dk:   #1b6fe4;
  --green:     #05C072;
  --green-lt:  #E5FAF1;
  --orange:    #FF6B2B;
  --orange-lt: #FFF1EB;
  --red:       #F04452;
  --red-lt:    #FEF0F1;
  --t1: #191F28;
  --t2: #4E5968;
  --t3: #8B95A1;
  --t4: #B0B8C1;
  --bg:      #F2F4F6;
  --surface: #FFFFFF;
  --line:    #E5E8EB;
  --fill:    #F2F4F6;
  --radius:  16px;
}

/* ── 기본 ── */
html, body, [class*="css"] {
  font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, sans-serif !important;
  color: var(--t1);
  -webkit-font-smoothing: antialiased;
}
.stApp { background: var(--bg) !important; }
.main .block-container {
  max-width: 720px !important;
  padding: 0 16px 80px !important;
}

/* ── 헤더 ── */
.app-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 20px 0 10px;
  margin-bottom: 4px;
}
.app-header-icon {
  width: 36px; height: 36px;
  background: var(--blue);
  border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 18px; flex-shrink: 0;
}
.app-header-title {
  font-size: 18px; font-weight: 700;
  color: var(--t1); letter-spacing: -.4px; line-height: 1;
}
.app-header-sub {
  font-size: 12px; color: var(--t3); margin-top: 2px;
}

/* ── 히어로 (빈 상태) ── */
.hero-empty {
  text-align: center;
  padding: 60px 0 40px;
}
.hero-empty-icon {
  font-size: 48px; margin-bottom: 16px; line-height: 1;
}
.hero-empty h2 {
  font-size: 22px; font-weight: 700; color: var(--t1);
  letter-spacing: -.5px; margin: 0 0 8px;
}
.hero-empty p {
  font-size: 14px; color: var(--t3); margin: 0; line-height: 1.7;
}

/* ── 예시 칩 ── */
.chips-wrap {
  display: flex; gap: 8px; flex-wrap: wrap;
  margin-bottom: 10px;
}
.chip-btn button {
  background: var(--surface) !important;
  color: var(--t2) !important;
  border: 1.5px solid var(--line) !important;
  border-radius: 20px !important;
  font-size: 12px !important;
  font-weight: 500 !important;
  height: 32px !important;
  padding: 0 14px !important;
  white-space: nowrap !important;
  transition: all .12s !important;
  box-shadow: none !important;
}
.chip-btn button:hover {
  background: var(--blue-lt) !important;
  color: var(--blue) !important;
  border-color: var(--blue) !important;
}

/* ── 입력 카드 ── */
.input-card {
  background: var(--surface);
  border-radius: var(--radius);
  box-shadow: 0 2px 12px rgba(0,0,0,.08);
  padding: 14px;
  margin-top: 8px;
}

/* ── textarea ── */
.stTextArea textarea {
  border-radius: 12px !important;
  border: 1.5px solid var(--line) !important;
  background: var(--fill) !important;
  font-size: 15px !important;
  font-family: 'Pretendard', sans-serif !important;
  padding: 14px 16px !important;
  line-height: 1.65 !important;
  color: var(--t1) !important;
  resize: none !important;
  box-shadow: none !important;
  transition: border-color .15s, box-shadow .15s !important;
}
.stTextArea textarea:focus {
  border-color: var(--blue) !important;
  background: var(--surface) !important;
  box-shadow: 0 0 0 3px rgba(49,130,246,.12) !important;
  outline: none !important;
}
.stTextArea label { display: none !important; }

/* ── 제출 버튼 ── */
.stButton > button {
  background: var(--blue) !important;
  color: #fff !important;
  border: none !important;
  border-radius: 12px !important;
  font-size: 15px !important;
  font-weight: 600 !important;
  height: 50px !important;
  letter-spacing: -.2px !important;
  transition: background .12s, transform .08s !important;
  box-shadow: none !important;
}
.stButton > button:hover  { background: var(--blue-dk) !important; }
.stButton > button:active { background: #1260c8 !important; transform: scale(.99) !important; }

/* ── 질의 카드 (결과 헤더) ── */
.query-card {
  background: var(--blue);
  border-radius: 14px 14px 4px 14px;
  padding: 14px 18px;
  margin-bottom: 12px;
}
.query-label {
  font-size: 10px; font-weight: 700; color: rgba(255,255,255,.7);
  letter-spacing: .1em; text-transform: uppercase; margin-bottom: 5px;
}
.query-text {
  font-size: 15px; font-weight: 600; color: #fff;
  line-height: 1.55; letter-spacing: -.2px;
}

/* ── 결과 카드 ── */
.result-card {
  background: var(--surface);
  border-radius: 4px 14px 14px 14px;
  box-shadow: 0 1px 4px rgba(0,0,0,.06), 0 4px 20px rgba(0,0,0,.04);
  padding: 20px;
  margin-bottom: 20px;
}

/* ── 이력 아이템 ── */
.hist-item {
  background: var(--surface);
  border-radius: 12px;
  padding: 12px 14px;
  margin-bottom: 6px;
  border: 1.5px solid var(--line);
  cursor: pointer;
  transition: border-color .12s, background .12s;
}
.hist-item:hover {
  border-color: var(--blue);
  background: var(--blue-lt);
}
.hist-q {
  font-size: 13px; font-weight: 500; color: var(--t1);
  line-height: 1.5; margin-bottom: 3px;
}
.hist-meta { font-size: 11px; color: var(--t4); }

/* ── 배지 ── */
.badge {
  display: inline-flex; align-items: center;
  padding: 3px 9px;
  border-radius: 20px;
  font-size: 11px; font-weight: 600;
  letter-spacing: .01em;
  margin: 0 3px 4px 0;
  white-space: nowrap;
}
.bd-blue   { background: var(--blue-lt);   color: var(--blue);   }
.bd-green  { background: var(--green-lt);  color: var(--green);  }
.bd-orange { background: var(--orange-lt); color: var(--orange); }
.bd-gray   { background: var(--fill);      color: var(--t2);     }
.bd-red    { background: var(--red-lt);    color: var(--red);    }
.bd-purple { background: #ede9fe;          color: #6d28d9;       }

/* ── 법령 아이템 ── */
.law-item {
  border-left: 3px solid var(--blue);
  border-radius: 0 10px 10px 0;
  padding: 11px 15px;
  margin-bottom: 8px;
  background: var(--blue-lt);
}
.law-title {
  font-size: 12px; font-weight: 700;
  color: var(--blue); margin-bottom: 5px;
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
}
.law-body {
  font-size: 13px; color: var(--t2);
  line-height: 1.7; white-space: pre-wrap;
}

/* ── 선례 카드 ── */
.prec-card {
  background: var(--surface);
  border: 1.5px solid var(--line);
  border-radius: 14px;
  padding: 16px 18px;
  margin-bottom: 10px;
}
.prec-meta { margin-bottom: 10px; }
.prec-q    { font-size: 14px; color: var(--t1); font-weight: 500; line-height: 1.6; }
.section-label {
  font-size: 10px; font-weight: 700;
  color: var(--t4); letter-spacing: .08em;
  text-transform: uppercase; margin-bottom: 5px;
}

/* ── 탭 ── */
.stTabs [data-baseweb="tab-list"] {
  gap: 0; border-bottom: 1.5px solid var(--line); background: transparent;
}
.stTabs [data-baseweb="tab"] {
  font-size: 14px !important; font-weight: 600 !important;
  color: var(--t3) !important; padding: 10px 14px !important;
  background: transparent !important;
}
.stTabs [aria-selected="true"] { color: var(--blue) !important; }
.stTabs [data-baseweb="tab-highlight"] {
  background: var(--blue) !important; height: 2px !important; bottom: -1px !important;
}
.stTabs [data-baseweb="tab-panel"] { padding-top: 16px !important; }

/* ── 구분선 ── */
.hr-toss { border: none; border-top: 1.5px solid var(--fill); margin: 18px 0; }

/* ── 비교 카드 ── */
.cmp-answer-card {
  background: var(--surface);
  border: 1.5px solid var(--line);
  border-radius: 14px;
  padding: 16px 18px;
  height: 100%;
  box-sizing: border-box;
}
.cmp-answer-card .cmp-q {
  font-size: 13px; font-weight: 600; color: var(--blue);
  margin-bottom: 8px; line-height: 1.5;
}
.cmp-answer-card .cmp-a {
  font-size: 13px; color: var(--t2); line-height: 1.7;
}
.analysis-card {
  background: #FFFBEB;
  border: 1.5px solid #F5DEB3;
  border-radius: 14px;
  padding: 18px 20px;
  margin-top: 16px;
}
.analysis-card .analysis-title {
  font-size: 12px; font-weight: 700; color: #B45309;
  letter-spacing: .06em; text-transform: uppercase; margin-bottom: 10px;
}

/* ── 사이드바 숨기기 ── */
section[data-testid="stSidebar"] { display: none !important; }
button[data-testid="collapsedControl"] { display: none !important; }

/* ── 스피너 ── */
.stSpinner > div { border-top-color: var(--blue) !important; }

/* ── stAlert ── */
.stAlert { border-radius: 12px !important; }
</style>
""", unsafe_allow_html=True)


# ── 상수 ────────────────────────────────────────────────────
TYPE_NAMES = {
    "DEF_EXP":   "정의확장형",
    "SCOPE_CL":  "적용범위 확정형",
    "REQ_INT":   "요건해석형",
    "EXCEPT":    "예외인정형",
    "INTER_ART": "조문간관계 해석형",
    "PROC_DISC": "절차·재량 확인형",
    "SANC_SC":   "벌칙·제재 범위형",
}

EXAMPLES = [
    "근린생활시설 → 숙박시설 용도변경 시 허가 필요한가요?",
    "건폐율 산정 시 지하층 바닥면적 포함되나요?",
    "사용승인 전 임시사용 허가 기간·조건은?",
    "방재지구 건축물 용적률 완화 기준은?",
    "계획관리지역에 공장 설치할 수 있나요?",
]


# ── 세션 상태 ────────────────────────────────────────────────
for key, default in [
    ("history",          []),
    ("result",           None),
    ("pending_query",    ""),
    ("compare_mode",     False),
    ("compare_selected", []),
    ("compare_result",   None),
    ("show_history",     False),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ── Generator 캐시 ───────────────────────────────────────────
@st.cache_resource(show_spinner="AI 엔진 초기화 중…")
def load_generator():
    spec = importlib.util.spec_from_file_location(
        "generator_mod", BASE_DIR / "06_Generator.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Generator()


# ── 헬퍼 ────────────────────────────────────────────────────
def verdict_badge_html(answer: str) -> str:
    m = re.search(r'\[확신도:\s*([^\]]+)\]', answer)
    if not m:
        return ""
    v   = m.group(1).strip()
    cls = {"확정": "bd-green", "조건부": "bd-orange", "재량위임": "bd-orange"}.get(v, "bd-gray")
    return f'<span class="badge {cls}">확신도 {v}</span>'


def rel_badges_html(rel_types: list) -> str:
    html = ""
    for rt in rel_types[:4]:
        name = TYPE_NAMES.get(rt.get("type", ""), rt.get("type", ""))
        w    = rt.get("weight", 1.0)
        cls  = "bd-blue" if w >= 0.8 else "bd-gray"
        html += f'<span class="badge {cls}">{name}</span>'
    return html


def source_badges_html(source_info: dict, law_docs: list, qa_docs: list) -> str:
    html  = ""
    exact = [d for d in law_docs if getattr(d, "score_type", "") == "exact"]
    if exact:
        html += '<span class="badge bd-blue">DB 직접참조</span>'
    elif source_info.get("db_law") or law_docs:
        html += '<span class="badge bd-blue">DB 조문참조</span>'
    if source_info.get("db_qa") or qa_docs:
        html += '<span class="badge bd-green">DB 선례참조</span>'
    if source_info.get("db_amendment"):
        html += '<span class="badge bd-purple">입법요지 참조</span>'
    if source_info.get("internal"):
        html += '<span class="badge bd-orange">내장지식 보충</span>'
    return html


# ── 비교 분석 ────────────────────────────────────────────────
def run_comparison(items: list[dict]) -> str:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        model  = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
        blocks = []
        for i, item in enumerate(items, 1):
            a_clean = re.sub(r'\[확신도:[^\]]+\]', '', item["answer"]).strip()
            blocks.append(f"[질의 {i}]\n{item['query']}\n\n[답변 {i}]\n{a_clean}")

        prompt = (
            "아래는 동일하거나 유사한 건축법규 질의에 대한 복수의 AI 답변입니다.\n\n"
            + "\n\n---\n\n".join(blocks)
            + "\n\n---\n\n"
            "위 답변들을 비교하여 다음을 분석해주세요:\n"
            "1. **핵심 결론의 차이**: 각 답변의 결론이 어떻게 다른지\n"
            "2. **차이 발생 원인**: 질의 표현, 적용 조문, 해석 관점 중 어디서 갈렸는지\n"
            "3. **더 적절한 해석**: 어느 쪽이 더 설득력 있는지, 이유는 무엇인지\n\n"
            "간결하고 구조적으로 작성하세요."
        )
        msg = client.messages.create(
            model=model, max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text
    except Exception as e:
        return f"분석 중 오류가 발생했습니다: {e}"


# ── 결과 렌더링 ──────────────────────────────────────────────
def render_result(result: dict):
    answer      = result["answer"]
    pass1       = result["pass1"]
    rel_types   = result.get("relation_types", [])
    law_docs    = result.get("law_docs", [])
    qa_docs     = result.get("qa_docs", [])
    source_info = result.get("source_info", {})

    badges = rel_badges_html(rel_types) + verdict_badge_html(answer) + source_badges_html(source_info, law_docs, qa_docs)
    if badges:
        st.markdown(f'<div style="margin-bottom:14px">{badges}</div>', unsafe_allow_html=True)

    st.markdown(answer)
    st.markdown('<hr class="hr-toss">', unsafe_allow_html=True)

    tab_law, tab_qa, tab_p1 = st.tabs([
        f"📄 법령 조문 ({len(law_docs)}건)",
        f"🗂 유사 선례 ({len(qa_docs)}건)",
        "🔬 Pass 1 분석",
    ])

    with tab_law:
        if law_docs:
            exact_shown = False
            for doc in law_docs:
                is_exact = getattr(doc, "score_type", "") == "exact"
                if is_exact and not exact_shown:
                    st.markdown(
                        '<div style="font-size:11px;font-weight:700;color:var(--blue);'
                        'letter-spacing:.06em;margin:6px 0 4px">직접참조 조문</div>',
                        unsafe_allow_html=True,
                    )
                    exact_shown = True
                elif not is_exact and exact_shown:
                    st.markdown(
                        '<div style="font-size:11px;font-weight:700;color:var(--t3);'
                        'letter-spacing:.06em;margin:12px 0 4px">유사도 검색 조문</div>',
                        unsafe_allow_html=True,
                    )
                    exact_shown = False

                badge_html      = ('<span class="badge bd-blue">직접참조</span>'
                                   if is_exact else
                                   f'<span class="badge bd-gray">유사도 {doc.score:.3f}</span>')
                content_preview = doc.content[:500].replace("<", "&lt;").replace(">", "&gt;")
                st.markdown(
                    f'<div class="law-item">'
                    f'  <div class="law-title">{doc.law_name} {doc.article_no} {badge_html}</div>'
                    f'  <div class="law-body">{content_preview}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.caption("검색된 법령 조문이 없습니다.")

    with tab_qa:
        if qa_docs:
            TAG_LABELS = {"seoul 2015": "서울시 질의회신집", "법제처해석례": "법제처 법령해석례"}
            for doc in qa_docs:
                meta        = doc.metadata
                doc_ref     = meta.get("doc_ref", "")
                tag         = meta.get("tag", "")
                question    = meta.get("question", "")
                answer_head = meta.get("answer_head", "")
                search_tags = meta.get("search_tags", "")
                tag_label   = TAG_LABELS.get(tag, tag)

                ref_b  = f'<span class="badge bd-blue">{doc_ref}</span>'       if doc_ref   else ""
                tag_b  = f'<span class="badge bd-gray">({tag_label})</span>'   if tag_label else ""
                sc_b   = f'<span class="badge bd-gray">유사도 {doc.score:.3f}</span>'
                q_html = question.replace("<", "&lt;").replace(">", "&gt;")
                a_html = answer_head.replace("<", "&lt;").replace(">", "&gt;")
                t_html = search_tags.replace("<", "&lt;").replace(">", "&gt;")

                sim_sec = (
                    f'<div style="margin-top:12px;padding-top:12px;border-top:1.5px solid #F2F4F6">'
                    f'  <div class="section-label">유사도 근거</div>'
                    f'  <div style="font-size:12px;color:#B0B8C1;line-height:1.65">{t_html}</div>'
                    f'</div>'
                ) if t_html else ""

                st.markdown(
                    f'<div class="prec-card">'
                    f'  <div class="prec-meta">{ref_b}{tag_b}{sc_b}</div>'
                    f'  <div class="section-label">질의내용</div>'
                    f'  <div class="prec-q" style="margin-bottom:12px">{q_html}</div>'
                    f'  <div style="padding-top:12px;border-top:1.5px solid #F2F4F6">'
                    f'    <div class="section-label">답변내용</div>'
                    f'    <div style="font-size:13px;color:#4E5968;line-height:1.7">{a_html}</div>'
                    f'  </div>'
                    f'  {sim_sec}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.info("유사도 0.60 이상인 선례를 찾지 못했습니다.", icon="ℹ️")

    with tab_p1:
        st.caption("Pass 1: 쟁점 식별 및 검색 트리거 분류 결과")
        st.markdown(pass1)


def render_compare_result(items: list[dict], analysis: str):
    st.markdown(
        '<div style="font-size:16px;font-weight:700;color:var(--t1);'
        'margin-bottom:14px;letter-spacing:-.3px">답변 비교</div>',
        unsafe_allow_html=True,
    )
    if len(items) == 2:
        cols = st.columns(2, gap="small")
        for col, item in zip(cols, items):
            with col:
                q_s = item["query"].replace("<", "&lt;").replace(">", "&gt;")
                a_s = re.sub(r'\[확신도:[^\]]+\]', '', item["answer"]).strip()
                a_s = a_s.replace("<", "&lt;").replace(">", "&gt;")[:800]
                st.markdown(
                    f'<div class="cmp-answer-card">'
                    f'  <div class="cmp-q">{q_s}</div>'
                    f'  <div class="cmp-a">{a_s}{"…" if len(item["answer"]) > 800 else ""}</div>'
                    f'</div>', unsafe_allow_html=True,
                )
    else:
        for item in items:
            q_s = item["query"].replace("<", "&lt;").replace(">", "&gt;")
            a_s = re.sub(r'\[확신도:[^\]]+\]', '', item["answer"]).strip()
            a_s = a_s.replace("<", "&lt;").replace(">", "&gt;")[:600]
            st.markdown(
                f'<div class="cmp-answer-card" style="margin-bottom:10px">'
                f'  <div class="cmp-q">{q_s}</div>'
                f'  <div class="cmp-a">{a_s}{"…" if len(item["answer"]) > 600 else ""}</div>'
                f'</div>', unsafe_allow_html=True,
            )

    st.markdown(
        '<div class="analysis-card"><div class="analysis-title">AI 차이 분석</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown(analysis)


# ════════════════════════════════════════════════════════════
# 메인 UI
# ════════════════════════════════════════════════════════════

# ── 헤더 ────────────────────────────────────────────────────
h_left, h_right = st.columns([5, 1])
with h_left:
    st.markdown("""
    <div class="app-header">
      <div class="app-header-icon">🏛</div>
      <div>
        <div class="app-header-title">건축법규 AI</div>
        <div class="app-header-sub">건축법 · 도시계획법 · 주택법 전문 자문</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

with h_right:
    history_count = len(st.session_state.history)
    hist_label    = f"이력 {history_count}건" if history_count else "이력"
    if st.button(hist_label, key="hist_toggle"):
        st.session_state.show_history = not st.session_state.show_history
        st.rerun()

st.markdown('<hr class="hr-toss" style="margin-top:0">', unsafe_allow_html=True)


# ── 이력 패널 ────────────────────────────────────────────────
if st.session_state.show_history and st.session_state.history:
    history_rev = list(reversed(st.session_state.history[-10:]))

    hdr_l, hdr_r = st.columns([5, 1])
    with hdr_l:
        st.markdown(
            '<div style="font-size:13px;font-weight:700;color:var(--t2);'
            'letter-spacing:.04em;margin-bottom:8px">최근 질의</div>',
            unsafe_allow_html=True,
        )

    # 비교 모드 토글
    with hdr_r:
        if st.session_state.compare_mode:
            if st.button("취소", key="cmp_cancel"):
                st.session_state.compare_mode     = False
                st.session_state.compare_selected = []
                st.rerun()
        else:
            if st.button("비교 선택", key="cmp_toggle"):
                st.session_state.compare_mode     = True
                st.session_state.compare_selected = []
                st.rerun()

    if st.session_state.compare_mode:
        st.caption("비교할 항목을 2개 이상 선택하세요.")
        for i, h in enumerate(history_rev):
            short   = h["query"][:40] + ("…" if len(h["query"]) > 40 else "")
            checked = i in st.session_state.compare_selected
            if st.checkbox(short, value=checked, key=f"cmp_{i}"):
                if i not in st.session_state.compare_selected:
                    st.session_state.compare_selected.append(i)
            else:
                if i in st.session_state.compare_selected:
                    st.session_state.compare_selected.remove(i)

        n_sel = len(st.session_state.compare_selected)
        if n_sel >= 2:
            if st.button(f"비교 분석 ({n_sel}건)", use_container_width=True, type="primary", key="cmp_run"):
                selected_items = [history_rev[i] for i in sorted(st.session_state.compare_selected)]
                with st.spinner("분석 중…"):
                    analysis = run_comparison(selected_items)
                st.session_state.compare_result   = {"items": selected_items, "analysis": analysis}
                st.session_state.compare_mode     = False
                st.session_state.compare_selected = []
                st.session_state.result           = None
                st.session_state.show_history     = False
                st.rerun()
    else:
        for i, h in enumerate(history_rev):
            short = h["query"][:50] + ("…" if len(h["query"]) > 50 else "")
            if st.button(short, key=f"hist_{i}", use_container_width=True):
                st.session_state.result         = h
                st.session_state.compare_result = None
                st.session_state.show_history   = False
                st.rerun()

        st.markdown("")
        if st.button("이력 초기화", key="hist_clear"):
            st.session_state.history        = []
            st.session_state.result         = None
            st.session_state.compare_result = None
            st.session_state.show_history   = False
            st.rerun()

    st.markdown('<hr class="hr-toss">', unsafe_allow_html=True)


# ── 결과 영역 ────────────────────────────────────────────────
if st.session_state.compare_result:
    cr = st.session_state.compare_result
    with st.container(border=True):
        render_compare_result(cr["items"], cr["analysis"])

elif st.session_state.result:
    r     = st.session_state.result
    q_esc = r["query"].replace("<", "&lt;").replace(">", "&gt;")
    st.markdown(
        f'<div class="query-card">'
        f'  <div class="query-label">질의</div>'
        f'  <div class="query-text">{q_esc}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        render_result(r)

else:
    # 빈 상태
    st.markdown("""
    <div class="hero-empty">
      <div class="hero-empty-icon">⚖️</div>
      <h2>건축법규, 바로 답드립니다</h2>
      <p>건축법 · 국토계획법 · 주택법 관련 질의를<br>아래에 입력하시면 관련 조문과 선례를 찾아드립니다.</p>
    </div>
    """, unsafe_allow_html=True)


# ── 입력 영역 ────────────────────────────────────────────────

# 예시 칩
st.markdown('<div style="margin-bottom:4px">', unsafe_allow_html=True)
chip_cols = st.columns(len(EXAMPLES))
for col, ex in zip(chip_cols, EXAMPLES):
    with col:
        st.markdown('<div class="chip-btn">', unsafe_allow_html=True)
        if st.button(ex[:18] + "…", key=f"chip_{ex[:10]}", use_container_width=True):
            st.session_state.pending_query = ex
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# 입력 폼
with st.container():
    query = st.text_area(
        "질문",
        value=st.session_state.pending_query,
        placeholder="건축법 관련 질문을 입력하세요…\n예) 근린생활시설을 숙박시설로 변경할 경우 건축허가를 받아야 하나요?",
        height=110,
        key="main_input",
        label_visibility="collapsed",
    )

    col_send, col_clear = st.columns([5, 1])
    with col_send:
        submit = st.button("질의하기  →", use_container_width=True, type="primary")
    with col_clear:
        if st.button("↺", use_container_width=True, key="clear_btn", help="초기화"):
            st.session_state.result         = None
            st.session_state.compare_result = None
            st.session_state.pending_query  = ""
            st.rerun()


# ── 처리 ────────────────────────────────────────────────────
if submit and query.strip():
    st.session_state.pending_query = ""

    try:
        gen = load_generator()
    except Exception as e:
        st.error(f"시스템 초기화 실패: {e}")
        st.stop()

    with st.status("건축법규 분석 중…", expanded=True) as status:
        st.write("⚙️  Pass 1 — 쟁점 식별 및 관계 유형 분류 중…")
        result = gen.generate(query.strip(), verbose=False)
        law_docs_all = result.get("law_docs", [])
        n_exact      = sum(1 for d in law_docs_all if getattr(d, "score_type", "") == "exact")
        n_law        = len(law_docs_all)
        n_qa         = len(result.get("qa_docs", []))
        exact_note   = f" (직접참조 {n_exact}건 포함)" if n_exact else ""
        st.write(f"✅  법령 조문 {n_law}건{exact_note} · 선례 {n_qa}건 검색 완료")
        st.write("✅  Pass 2 — 최종 답변 생성 완료")
        status.update(label="분석 완료", state="complete", expanded=False)

    st.session_state.result = result
    st.session_state.history.append(result)
    st.rerun()
