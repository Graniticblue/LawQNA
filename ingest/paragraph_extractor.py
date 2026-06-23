"""
해석례 답변(이유)에서 문단별 논지(gist)를 추출.
- 【이유】 부분의 문단만 (회답·법령 조문 원문·검색태그 제외)
- 각 문단의 핵심 논지를 gemini로 한 문장 추출 (역할 고정 프레임워크 없이, 논지 중심)
- 법령 조문 원문 문단은 gist="SKIP" → 청킹 제외

ingest_법제처.py(신규 자동) + 기존 jsonl 일괄 처리에서 공용으로 사용.
"""
import os, re, json

# 결정적으로 제외할 메타/안내 문단 (조문 원문 식별은 gemini SKIP에 위임)
_META = re.compile(r"(\[검색태그\]|※\s*법제처 법령해석|법령해석의 효력|행정부 내부에서)")


def _split_reasoning(answer: str) -> list[str]:
    """답변에서 【이유】 문단 추출. 조문 원문 사전제외는 하지 않고(논지 섞인 문단 보존)
    gemini가 gist='SKIP'으로 거르도록 위임. 메타·안내 문단만 결정적으로 제외.
    【이유】 헤더가 짧은 단독 줄이어도 놓치지 않도록 위치를 직접 탐색."""
    idx = answer.find("【이유】")
    if idx < 0:
        return []   # 이유 섹션 없음(민원 회신 등) → 문단청킹 생략, 통째 doc만
    body = answer[idx:]
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip() and len(p.strip()) > 25]
    out = []
    for p in paras:
        if _META.search(p[:60]):
            continue
        out.append(re.sub(r"^【이유】\s*", "", p))
    return out


def extract_paragraphs_with_gist(answer: str) -> list[dict]:
    """반환: [{"text": 문단, "gist": 논지}, ...]. 논지 없는(SKIP) 문단은 제외."""
    reasoning = _split_reasoning(answer)
    if not reasoning:
        return []
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return []
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        return []

    joined = "\n\n".join(f"[{i}] {p}" for i, p in enumerate(reasoning, 1))
    prompt = (
        "다음은 법제처 해석례 '이유'의 문단들이다. 각 문단의 핵심 논지를 한 문장으로 요약하라.\n"
        "역할 분류는 하지 말고, 그 문단이 무엇을 주장하는지(논지)만 적는다.\n"
        "법령 조문 원문을 그대로 옮긴 문단은 gist를 \"SKIP\"으로.\n"
        "JSON 배열만 출력: [{\"i\":1,\"gist\":\"핵심 논지 한 문장\"}, ...]\n\n"
        f"{joined}"
    )
    try:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=8000, temperature=0.2,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        m = re.search(r"\[.*\]", resp.text or "", re.DOTALL)
        gists = {g["i"]: g.get("gist", "") for g in json.loads(m.group())} if m else {}
    except Exception as e:
        print(f"  [WARN] 문단 논지 추출 실패: {e}")
        return []

    result = []
    for i, p in enumerate(reasoning, 1):
        g = (gists.get(i, "") or "").strip()
        if not g or g == "SKIP":
            continue
        result.append({"text": p, "gist": g})
    return result
