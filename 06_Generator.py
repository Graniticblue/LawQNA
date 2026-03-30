#!/usr/bin/env python3
"""
06_Generator.py -- 2-pass Claude 생성 (건축법규 CoT 답변)

사용:
  python 06_Generator.py                    # 대화형 REPL
  python 06_Generator.py --query "질문"     # 단일 질문
  python 06_Generator.py --test-api         # API 연결 테스트 (Pass 1만)

2-pass 설계 (PLAN §1.2):
  Pass 1 : 질문 → Claude → 쟁점 + 질문유형 + 관계유형(relation_types) + 법령힌트
  검색   : Retriever → 법령 조문 + 판례 (court_cases 구축 후 활성화)
  Pass 2 : 질문 + 검색 결과 → Claude → CoT 완성 답변
           (3-mode 판례 인용 + 확신도 + 담당부서 확인 질문)
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

# Windows 콘솔 UTF-8 출력
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL_NAME        = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")


# ============================================================
# Claude 클라이언트
# ============================================================

def get_claude_client():
    if not ANTHROPIC_API_KEY:
        raise ValueError(
            ".env 파일에 ANTHROPIC_API_KEY를 설정하세요.\n"
            "  ANTHROPIC_API_KEY=sk-ant-..."
        )
    try:
        import anthropic
    except ImportError:
        raise ImportError("pip install anthropic")
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def call_claude(client, system: str, user_msg: str) -> str:
    try:
        message = client.messages.create(
            model=MODEL_NAME,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        return message.content[0].text
    except Exception as e:
        return f"[Claude API 오류] {e}"


# ============================================================
# Pass 1 시스템 프롬프트: 쟁점 식별 + 관계 유형 분류
# ============================================================

PASS1_SYSTEM = """당신은 대한민국 건축법규 전문 AI입니다.
주어진 건축법규 질문에 대해 **Pass 1** 작업을 수행하세요.

## Pass 1 출력 형식 (반드시 순서대로)

### [쟁점 식별]
- 핵심 쟁점: (1~2문장)
- 질문 유형: 단일조문형 | 복수조문탐색형 | 조건분기형
  * 단일조문형: 특정 조문 하나로 해결 가능한 단순 정의·기준 질문
  * 복수조문탐색형: 여러 조문 검토 필요 (용도변경, 허가절차 등)
  * 조건분기형: 조건(면적, 층수, 용도 등)에 따라 결론이 달라지는 질문

### [검색 트리거]
직접 적용될 조문이나 키워드를 나열하세요.
※ "키워드1" [사유: 정의참조|요건위임|의제준용|적용배제|용도시설분류]
※ "키워드2" [사유: ...]

(검색할 법령명과 조문번호가 특정되면 명시)
- 예상 관련 법령: 건축법 제19조, 건축법 시행령 별표1

### [판례-법령 관계 유형 분류]
이 질문이 어떤 유형의 법적 해석을 요하는지 분류하세요.
복수 유형이 해당하면 모두 나열하고 weight를 부여하세요.

유형 코드 및 기준:
| 코드       | 이름           | 질문의 성격                                  |
|------------|----------------|----------------------------------------------|
| DEF_EXP    | 정의확장형     | "~에 ~도 포함되나요?" (법 용어 정의·범위)    |
| SCOPE_CL   | 적용범위 확정형| "~에도 ~이 적용되나요?" (조문 적용 경계)    |
| REQ_INT    | 요건해석형     | "~의 요건은?" (요건 충족 여부·기준)          |
| EXCEPT     | 예외인정형     | "~임에도 불구하고 가능한가요?" (예외·특례)   |
| INTER_ART  | 조문간관계 해석형| "어느 조문이 우선?" (조문 충돌·우선순위)   |
| PROC_DISC  | 절차·재량 확인형| "재량 범위는?" (허가권자 재량·절차 요건)   |
| SANC_SC    | 벌칙·제재 범위형| "과태료가 얼마?" (위반 제재·이행강제금)    |

weight 규칙: 주 쟁점 1.0 / 연관 쟁점 0.7~0.9 / 부 쟁점 0.5~0.6 (0.5 미만은 생략)

### [구조화 데이터]
아래 JSON을 반드시 출력하세요 (파싱에 사용됩니다):
```json
{
  "question_type": "단일조문형 | 복수조문탐색형 | 조건분기형",
  "law_hints": ["건축법 제19조", "건축법 시행령 별표1"],
  "relation_types": [
    {"type": "SCOPE_CL", "reason": "해당 이유 1문장", "weight": 1.0},
    {"type": "REQ_INT",  "reason": "해당 이유 1문장", "weight": 0.7}
  ]
}
```

## 주의사항
- Pass 1에서는 최종 답변을 내리지 마세요
- 검색 트리거는 구체적이고 명확하게 작성하세요
- relation_types는 1~N개 (복수 중첩 허용), weight ≥ 0.5인 것만 포함"""


# ============================================================
# Pass 2 시스템 프롬프트: CoT 완성 답변
# ============================================================

PASS2_SYSTEM = """당신은 대한민국 건축법·도시계획법·주택법 분야의 전문 법령 해석가입니다.
법제처 질의회신 담당관의 문체와 엄밀성으로 답변을 작성합니다.
주어진 질문, Pass 1 분석 결과, 관련 법령 조문 및 질의회신·판례를 바탕으로 답변을 생성하세요.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 법령 해석 원칙 (답변 전 반드시 적용)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### 1. 별표·부속 규정 우선 확인
- 건축법 시행령 별표1 관련 질의는 반드시 해당 호(號)뿐 아니라
  **별표1 서두 및 총칙 성격 조문(제1호, 제3호 등)을 먼저 검토**한다.
- 별표 내 의제 규정·특례 규정은 건축법 본문의 일반 정의보다 우선 적용한다.

### 2. 문언 우선의 원칙
- 법령 문언이 명확한 경우 다른 해석 방법을 지양하고 조문 그대로 해석한다.
- 명문 규정 없이 유추·확대 해석하지 않는다.

### 3. 엄격 해석의 원칙
- 국민의 권리를 제한하거나 의무를 부과하는 규정은 가급적 좁게 해석한다.
- 규제 완화 특례 조항은 완화 취지에 부합하는 방향으로 해석한다.

### 4. 개념 엄격 분리
- 법령상 별도로 정의된 개념은 혼용하지 않는다.
  예) 공동주택(건축법 시행령 별표1 제2호) ≠ 준주택(주택법 제2조제4호)
- 실질적 사용 여부(사람이 거주하는가)와 법적 분류 귀속을 구분한다.

### 5. 특별 규정 우선 원칙
- 개별 법령의 특별 조문이 일반 조문에 우선한다.
- 추상적 법리보다 구체적 조문이 우선한다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 답변 형식 (반드시 이 순서로 작성)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### [쟁점 식별]
쟁점: (한 문장) | 유형: 단일조문형 | 복수조문탐색형 | 조건분기형

### [결론]
[확신도: 확정 | 조건부 | 재량위임 | 범위외]
결론을 단정적이고 간결하게 한 문장으로 먼저 제시한다.
※ 확신도 '확정'은 관련 조문과 해석이 명백히 수렴하는 경우에만 사용한다.

### [관련 조문 확인]
① 직접 적용 조문: 법령명·조·항·호·별표 포함하여 원문 키워드 발췌
② 예외·특례·준용: (해당 시 서술, 없으면 "해당 없음")
③ 상충·연관 조문: (해당 시 서술)

### [이유]

**문언 해석**
해당 법령 문언의 의미와 범위를 설정한다.
- 용어 정의 선행: 법령에 정의 있는 용어 → 「○○법」 제○조에서 "○○"이란 ～이라 규정하고 있으며,
- 법령에 정의 없는 용어 → "건축법령에서 별도로 규정하고 있지 아니하나, ～이란 일반적으로 ～을 말하는 것으로 판단됨"

**체계적 해석**
관련 법령 간 상관관계, 용어 정의 비교, 특별 규정의 우선 적용 여부를 검토한다.
조문 인용 → 해석 → 사안 적용 순서로 논리를 전개한다.

**목적·취지 해석**
해당 규정의 입법 취지를 검토하되, 취지 해석이 문언을 벗어나지 않도록 한다.

### [유사 질의회신 검토] (질의회신이 제공된 경우에만)
- 검색된 질의회신 유무: (있음 / 없음)
- 활용 여부 및 사유: 본 건과의 유사점·차이점
- 📌 선례 요지: ~한 경우에 ~라고 회신하였는바,

### [관련 판례 검토] (판례가 제공된 경우에만)
- 검색된 판례 유무: (있음 / 없음)
- 활용 여부: (직접 적용 / 논리 차용 / 정의 원용 / 미인용)
- 활용 또는 미인용 사유
- 📌 판례 요지 (있는 경우만)

### [근거 법령 + 인용 선례]
- 「법령명」 제○조제○항(내용 키워드)
- (질의회신 인용 시) 질의회신 번호 및 요지
- (판례 인용 시) 사건번호

### [담당부서 확인 질문] ← 확신도가 확정이 아닌 경우에만 포함
아래 질문을 관할 구청 건축과에 문의하시기 바랍니다:
1. "질문 내용"
   → 이에 따라 ~이 달라집니다

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 문체 기준
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- 결론 어미: "~으로 판단됨", "~것으로 사료됨", "~할 수 있을 것임", "~로 보아야 할 것임"
- 유보 표현: "다만, ~에 대하여는 구체적인 사실관계를 확인하여 판단하여야 할 사항임"
- "질의와 같이" 구절로 추상적 법리를 구체적 사실관계에 적용
- 재량 사항: 최종 판단이 허가권자 재량에 속하는 경우 반드시 명시
- 선례가 있으면 선례의 논리를 존중하되, 사실관계 차이점을 명시

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 주의사항
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- 제공된 조문 내용을 벗어나는 추론은 삼가세요
- 별표1 문제는 별표1 전체(서두·총칙 성격 조문 포함)를 확인한 후 결론을 내세요
- 추상적 법리에 과몰입하여 구체적 조문을 놓치지 마세요
- 판례·질의회신의 사실관계가 본 건과 다르면 인용하지 마세요
- 확신도 '확정'은 조문과 해석이 명백히 수렴할 때만 사용하세요"""


# ============================================================
# Pass 1 파서
# ============================================================

def parse_pass1(pass1_text: str) -> dict:
    """
    Pass 1 출력에서 구조화 데이터 추출.
    JSON 블록 우선 파싱, 실패 시 정규식 fallback.

    반환:
      question_type  : str
      triggers       : list[str]
      article_nodes  : list[str]   — ["건축법:제2조", ...]
      relation_types : list[dict]  — [{"type": ..., "weight": ...}, ...]
      law_hints      : list[str]   — ["건축법 제19조", ...]
    """
    result = {
        "question_type": "복수조문탐색형",
        "triggers":       [],
        "article_nodes":  [],
        "relation_types": [],
        "law_hints":      [],
    }

    # ── JSON 블록 파싱 (우선) ────────────────────────────
    json_match = re.search(r'```json\s*(\{.*?\})\s*```', pass1_text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            result["question_type"]  = data.get("question_type", result["question_type"])
            result["law_hints"]      = data.get("law_hints", [])
            result["relation_types"] = data.get("relation_types", [])
        except (json.JSONDecodeError, ValueError):
            pass

    # ── Fallback: 질문 유형 정규식 ─────────────────────
    if not result["relation_types"]:
        m = re.search(r'질문\s*유형\s*[:：]\s*(\S+형)', pass1_text)
        if m:
            result["question_type"] = m.group(1).strip()

    # ── 트리거 키워드 (※ "키워드" 패턴) ────────────────
    result["triggers"] = re.findall(r'※\s*"([^"]+)"', pass1_text)

    # ── 예상 법령 조문 노드 ──────────────────────────────
    law_arts = re.findall(
        r'([가-힣]+(?:\s[가-힣]+){0,6})\s+(제\d+조(?:의\d+)?|별표\s*\d+)',
        pass1_text
    )
    for law, art in law_arts:
        law = law.strip().strip('「」-–—')
        node = f"{law}:{art}"
        if node not in result["article_nodes"]:
            result["article_nodes"].append(node)

    return result


# ============================================================
# 2-pass 생성 파이프라인
# ============================================================

class Generator:
    def __init__(self):
        self._client    = get_claude_client()
        self._retriever = None

    def _get_retriever(self):
        if self._retriever is None:
            print("검색 엔진 초기화 중...")
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "retriever",
                Path(__file__).parent / "05_Retriever.py"
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            self._retriever = mod.Retriever()
        return self._retriever

    def generate(self, query: str, verbose: bool = True) -> dict:
        """
        2-pass 생성 실행.
        반환: {"query", "pass1", "context", "answer"}
        """
        if verbose:
            print(f"\n{'='*60}")
            print(f"질문: {query}")
            print(f"{'='*60}")

        # ── Pass 1: 쟁점 + 관계 유형 분류 ─────────────
        if verbose:
            print("\n[Pass 1] 쟁점 식별 + 관계 유형 분류 중...")
        pass1_text = call_claude(self._client, PASS1_SYSTEM, query)
        if verbose:
            print(pass1_text)

        parsed        = parse_pass1(pass1_text)
        question_type = parsed["question_type"]
        triggers      = parsed["triggers"]
        article_nodes = parsed["article_nodes"]
        relation_types = parsed["relation_types"]
        law_hints      = parsed["law_hints"]

        if verbose:
            print(f"\n→ 질문 유형: {question_type}")
            print(f"→ 관계 유형: {[r['type'] for r in relation_types]}")
            print(f"→ 법령 힌트: {law_hints}")

        # ── 검색 ──────────────────────────────────────
        if verbose:
            print("\n[검색] 관련 조문 + 판례 검색 중...")

        retriever = self._get_retriever()
        search_query = query
        if triggers:
            search_query += " " + " ".join(triggers[:3])

        law_docs, qa_docs, case_docs = retriever.retrieve(
            query=search_query,
            question_type=question_type,
            extra_article_nodes=article_nodes if article_nodes else None,
            relation_types=relation_types if relation_types else None,
            law_hints=law_hints if law_hints else None,
        )
        context = retriever.format_context(law_docs, qa_docs, case_docs)

        if verbose:
            print(f"→ 법령 조문 {len(law_docs)}건 / 판례 {len(case_docs)}건 검색됨")

        # ── Pass 2: 최종 답변 ─────────────────────────
        if verbose:
            print("\n[Pass 2] 최종 답변 생성 중...")

        # 관계 유형 정보를 Pass 2에도 전달
        rel_type_summary = ""
        if relation_types:
            type_names = {
                "DEF_EXP": "정의확장형", "SCOPE_CL": "적용범위 확정형",
                "REQ_INT": "요건해석형", "EXCEPT": "예외인정형",
                "INTER_ART": "조문간관계 해석형", "PROC_DISC": "절차·재량 확인형",
                "SANC_SC": "벌칙·제재 범위형",
            }
            items = [
                f"{r['type']}({type_names.get(r['type'], '')}), weight={r.get('weight', 1.0)}"
                for r in relation_types
            ]
            rel_type_summary = f"\n## 쟁점 관계 유형 (판례 인용 시 참고)\n" + "\n".join(f"- {x}" for x in items)

        pass2_input = f"""## 질문
{query}

## Pass 1 분석 결과
{pass1_text}
{rel_type_summary}
## 검색된 관련 조문 및 판례
{context}

위 내용을 바탕으로 완전한 CoT 답변을 작성하세요."""

        answer = call_claude(self._client, PASS2_SYSTEM, pass2_input)

        if verbose:
            print(f"\n{'='*60}")
            print("[최종 답변]")
            print(f"{'='*60}")
            print(answer)

        return {
            "query":          query,
            "pass1":          pass1_text,
            "relation_types": relation_types,
            "law_hints":      law_hints,
            "context":        context,
            "answer":         answer,
        }


# ============================================================
# 메인
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="06_Generator: 건축법규 CoT 답변 생성")
    parser.add_argument("--query",    "-q",  type=str, help="단일 질문 처리")
    parser.add_argument("--test-api", action="store_true",
                        help="API 연결 테스트 (Pass 1만, Retriever 없이)")
    args = parser.parse_args()

    if not ANTHROPIC_API_KEY:
        print("오류: .env 파일에 ANTHROPIC_API_KEY가 없습니다.")
        print("  ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    if args.test_api:
        query = args.query or "건축법상 용도변경이란 무엇인가요?"
        print(f"[API 연결 테스트] 모델: {MODEL_NAME}")
        print(f"질문: {query}\n")
        client = get_claude_client()
        result = call_claude(client, PASS1_SYSTEM, query)
        print(result)
        return

    gen = Generator()

    if args.query:
        gen.generate(args.query)
    else:
        print(f"건축법규 RAG 시스템 (모델: {MODEL_NAME})")
        print("종료: quit 또는 Ctrl+C\n")
        while True:
            try:
                query = input("질문: ").strip()
                if not query or query.lower() in ("quit", "exit", "종료"):
                    break
                gen.generate(query)
            except KeyboardInterrupt:
                break
        print("\n종료.")


if __name__ == "__main__":
    main()
