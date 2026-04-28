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

MEMOS_PATH = Path(__file__).parent / "data" / "memos.jsonl"
_memo_bullets_cache: str = ""


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
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        return message.content[0].text
    except Exception as e:
        return f"[Claude API 오류] {e}"


# ============================================================
# 메모 로더 (해석 원칙 bullet 압축)
# ============================================================

def load_memo_bullets() -> str:
    """
    data/memos.jsonl → 압축 bullet 문자열 (Pass 2 시스템 프롬프트 삽입용)

    각 메모에서 핵심 규칙 1줄을 추출:
      우선순위: 【원칙】 > 【핵심 원칙】 > 【핵심명제】 > 【결론】 > 내용 첫 줄
    """
    global _memo_bullets_cache
    if _memo_bullets_cache:
        return _memo_bullets_cache

    if not MEMOS_PATH.exists():
        return ""

    # ── always-on bullets: 모든 질의에 범용 적용되는 원칙만 ──
    # 케이스-특정 원칙(memo_001~003, 006~010)은 memo RAG로 처리
    MANUAL_BULLETS: dict[str, str] = {
        "memo_004": "목적이 다른 조문의 동일 문언을 끌어와 의무를 회피하려는 시도는 각 조문의 입법 목적 분석으로 차단. 면적 산정 제외는 해당 조문에 명시된 것만 인정(해석으로 추가 불가). 복수 용도 건물에서 '각각'이 명시된 조문은 용도별 개별 산정, '각각'이 없으면 합산 기준.",
        "memo_005": (
            "예외 규정을 좁게 해석하기 전, '예외를 허용하면 보호법익이 실제로 약화되는가'를 먼저 확인한다. "
            "예외 허용이 오히려 보호법익에 유리한 상황이라면 엄격해석 원칙은 역효과를 낳는다(전제 붕괴 → 면제 인정이 맞음). "
            "조문을 읽을 때 열거 내용뿐 아니라 '그 경우 어떻게 된다'는 효과 조항도 별도로 확인할 것 — "
            "효과 조항이 쟁점 결론을 결정적으로 바꿀 수 있다."
        ),
        "memo_011": (
            "공동주택 관련 질의에서는 건축법과 주택법이 동시에 적용 가능해 보이더라도, "
            "반드시 주택법에 해당 규정이 있는지 먼저 확인한다. "
            "주택법에 규정이 있으면 주택법 우선 적용(건축법 배제). "
            "주택법에 규정이 없을 때만 건축법을 보충 적용한다(법제처 09-0041)."
        ),
        "memo_012": (
            "질의에서 법령 조문을 전제로 인용할 때, 답변 전에 두 가지를 검증한다. "
            "① 현행성: 인용된 조문이 현재 법령에 존재하는가 — 삭제된 경우 질의의 전제 자체가 무너지며, "
            "AI와 해석례의 결론 차이는 'AI 오류'가 아니라 '법령 개정' 때문일 수 있다. "
            "② 정확성: 질의가 기술한 조문 내용이 현행 조문 텍스트와 실제로 일치하는가 — "
            "개정으로 내용이 바뀌었다면 전제가 어긋난다. "
            "특히 '~에 따르면 ~인바, ~이 가능한지?' 형식의 질의는 전제부를 먼저 검증한다."
        ),
        "memo_014": (
            "조문이 '별표 X의 기준에 따라 설치하는 Y는 산입하지 않는다' 구조일 때, "
            "Y가 별표 X에 실제로 열거되어 있는지 역추적한다(이중 잠금 논리). "
            "① 제외 조항 명시 목록에 Y가 있는가 — ② 참조 별표 X에 Y가 편의시설·기준 대상으로 열거되어 있는가. "
            "둘 중 하나라도 없으면 전제 미충족 → 제외 불가. "
            "'Y 없이 X 이용 불가 → Y는 X의 일부' 식의 기능적 불가분 논리는 건축법 면적 산정 제외에서 통하지 않는다(법제처 24-0696)."
        ),
    }

    lines = []
    with open(MEMOS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec     = json.loads(line)
            mid     = rec.get("memo_id", "")
            title   = rec.get("title", "")
            content = rec.get("content", "")

            # always-on은 MANUAL_BULLETS에 명시된 것만 포함
            # 나머지는 memo RAG (memos 컬렉션)로 검색 시 조건부 주입
            if mid not in MANUAL_BULLETS:
                continue
            bullet = MANUAL_BULLETS[mid]
            lines.append(f"- [{mid}] {bullet}")

    _memo_bullets_cache = "\n".join(lines)
    return _memo_bullets_cache


# ============================================================
# Pass 1 시스템 프롬프트: 쟁점 식별 + 관계 유형 분류
# ============================================================

PASS1_SYSTEM = """당신은 대한민국 건축법규 전문 AI입니다.
주어진 건축법규 질문에 대해 **Pass 1** 작업을 수행하세요.

## Pass 1 출력 형식 (반드시 순서대로)

### [쟁점 식별]
- 핵심 쟁점: (1~2문장)
  * 질의자가 제시한 대립 구도(A인지 vs B인지)를 그대로 파악할 것.
  * 임의로 다른 대립항으로 재구성하지 않는다.
  * 예) "동일 구역인지 vs 다른 구역도 포함인지"를 묻는 질의를 "일방 대지만인지 vs 양방 대지인지" 문제로 바꾸지 않는다.
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

### [정의 확인 용어]
쟁점 해결 전에 법령상 정의를 먼저 확인해야 하는 핵심 용어들을 나열하세요.
- 조건: 쟁점 문구 중 법령에 별도로 정의된 용어 (예: "대수선", "저당권등", "공동주택", "준주택")
- 정의가 조문에 직접 규정된 경우: "용어" → 예상 정의 조문
- 예: "대수선" → 건축법 제2조제1항제9호 + 시행령 제3조의2
- **탐색 우선순위**: 질의 법령(같은 법, 같은 시행령) 내 정의 조문을 먼저 확인한다. 질의 법령 내에 정의가 없는 경우에 한해 타 법령을 탐색한다.

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
  "definition_terms": ["대수선", "저당권등"],
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

PASS2_SYSTEM = """당신은 대한민국 건축법·도시계획법·주택법 분야의 법령해석전문가입니다.
질의에 대해 법령 문언과 입법취지에 근거하여 명확하고 단호한 결론을 내리며, 정중하고 단정적인 어투로 답변을 작성합니다.
주어진 질문, Pass 1 분석 결과, 관련 법령 조문 및 질의회신·판례를 바탕으로 답변을 생성하세요.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 법령 해석 원칙 (답변 전 반드시 적용)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### 1. 별표·부속 규정 우선 확인
- 건축법 시행령 별표1 관련 질의는 반드시 해당 호(號)뿐 아니라
  **별표1 서두 및 총칙 성격 조문(제1호, 제3호 등)을 먼저 검토**한다.
- 별표 내 의제 규정·특례 규정은 건축법 본문의 일반 정의보다 우선 적용한다.

### 2. 문언 우선의 원칙
- 법령 문언이 명확한 경우 우선 적용하되, 아래 경우에는 목적론적 해석을 병행한다:
  * 열거 후 "등"을 사용하는 규정 — 열거는 예시이며, 동질적 성격의 대상이 포함될 수 있다.
  * 입법연혁상 적용 범위가 확장 개정된 규정 — 확장 의도를 고려한다.
  * 법제처 해석례에서 확장 해석이 확립된 경우 — 선례의 논리를 존중한다.
- 명문 규정 없는 유추·확대 해석은 삼가되, 규정의 취지·목적에 비추어 실질적 효과를 기준으로 포함 여부를 판단해야 하는 경우에는 예외로 한다.

### 3. 엄격 해석의 원칙
- 국민의 권리를 제한하거나 의무를 부과하는 규정은 가급적 좁게 해석한다.
- **기존 건축물 특례 조항(건축제한·건폐율·용적률 부적합 시 재축·대수선·증축·개축 허용) 전용 규칙:**
  - "기존의 건축물" = 건축 당시 관계 법령에 따라 적법하게 건축된 후, 법령 개정·도시군관리계획 변경 등
    수범자의 귀책사유 없는 사유로 비로소 부적합하게 된 건축물만을 의미한다. (법제처 24-0241, 24-0780)
  - 특례를 적용받아 증축·개축·대수선이 완료된 건축물은 더 이상 "기존의 건축물"이 아니므로,
    같은 특례를 재차 적용받을 수 없다. (법제처 24-0780)
  - 이 특례 조항들은 예외 규정이므로 **반드시 엄격하게 해석**하며, 목적론적·확장 해석으로
    허용 범위를 넓히지 않는다. (대법원 2021두38932, 법제처 13-0246, 20-0535)
- **주의**: "예외 규정은 좁게 해석"이라는 원칙을 기계적으로 적용하지 않는다.
  예외 요건을 좁게 해석하는 것이 곧 규제(이격거리 제한, 건축허가 제한 등)를 넓히는 결과가 되는 경우에는,
  §6 형벌법규 원칙이 이 원칙보다 우선한다.

### 4. 개념 엄격 분리
- 법령상 별도로 정의된 개념은 혼용하지 않는다.
  예) 공동주택(건축법 시행령 별표1 제2호) ≠ 준주택(주택법 제2조제4호)
- 실질적 사용 여부(사람이 거주하는가)와 법적 분류 귀속을 구분한다.

### 5. 특별 규정 우선 원칙
- 개별 법령의 특별 조문이 일반 조문에 우선한다.
- 추상적 법리보다 구체적 조문이 우선한다.

### 6. 형벌법규 연결 확인
- 해당 조문 위반이 형사처벌(건축법 제108조·제110조 등)과 연결되는지 확인한다.
- 연결되는 경우: 예외 요건을 좁게 해석하면 처벌 범위가 넓어지는 역설이 발생할 수 있다.
  이 경우 "예외는 엄격 해석" 원칙을 기계적으로 적용하지 말고,
  죄형법정주의(명확한 근거 없이 처벌 범위를 확대해선 안 됨) 관점에서 재검토한다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 답변 형식 (반드시 이 순서로 작성)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

> **출력 원칙**: 아래 단계는 내부 추론 순서이다. **[결론]과 [관련 조문]만 명시적 섹션 헤더로 출력**하고, 나머지([쟁점 식별], [Step 0], [3트랙 해석])는 **자연스러운 단락**으로 녹여낸다. 결론은 답변 맨 앞 단락에서 먼저 선언한다.

### [쟁점 식별] ← 내부 판단용. 출력 시에는 첫 단락 도입부에 한 문장으로 녹인다.
쟁점: (한 문장) | 유형: 단일조문형 | 복수조문탐색형 | 조건분기형

### [Step 0] 핵심 용어 법적 정의 확인 ← 내부 판단용. 출력 시에는 이유 단락 첫 문장에 "「○○법」 제○조에서 '용어'를 ~로 정의하고 있는바," 형태로 녹인다.
쟁점 해결에 필요한 핵심 용어들의 법령상 정의를 먼저 확정한다.

**수행 순서:**
1. Pass 1의 [정의 확인 용어] 목록을 참고하여 쟁점 문구 중 법령에 별도로 정의된 용어를 추출한다.
2. 각 용어에 대해 해당 정의 조문을 인용한다 — **질의 법령(같은 법·같은 시행령) 내 정의 조문을 먼저 탐색하고, 없는 경우에만 타 법령을 참조한다**:
   예) "「건축법」 제2조제1항제9호에서는 '대수선'을 ... 대통령령으로 정하는 것이라 하고, 시행령 제3조의2에서 내력벽(제1호), 기둥(제2호), ... 외벽 마감재료(제9호) 등을 규정하고 있는바"
3. **정의 단계 결론 판단 — 출력 필수:**
   - **정의만으로 쟁점이 해소되는 경우**: "정의에 의해 ○○는 ××에 해당/불해당함이 확정 → 3트랙 생략, 결론 직행"이라고 명시하고 바로 [결론]으로 이동한다.
   - **정의만으로 결론이 나지 않는 경우**: "정의 확인 완료: ○○는 [요약]. 쟁점 미해소 → 3트랙으로 진행"이라고 명시하고 계속 진행한다.

**주의:** 정의 조문이 검색 컨텍스트에 없어도 일반 법령 지식으로 확인 가능한 경우 직접 인용한다.

---

### [3트랙 해석 — 내부 사고] ← 출력하지 않음. 결론 단락과 이유 단락에 녹여낸다.
세 트랙을 **항상 내부적으로 모두 검토**한 뒤, 수렴 여부에 따라 출력 방식을 결정한다.
**출력 전에 먼저 세 트랙의 중간 결론이 일치하는지 확인한다.**
**Step 0에서 정의로 쟁점이 해소된 경우 이 섹션은 생략한다.**

각 트랙의 검토 기준:

**① 문언적 해석**
조문 문언 그대로의 의미·범위를 설정한다.
- **중의성 검토 먼저**: 해당 문구에 문법적으로 타당한 독해가 둘 이상 존재하는지 먼저 확인한다.
  존재하면 "문언상 분명하지 않다"고 명시하고, 독해 A / 독해 B를 병기한 뒤 입법취지·목적론으로 판단을 넘긴다.
  하나의 독해만 가능할 때에만 "문언상 명확하다"고 판단한다.
- **중의성 인정 시 우열 판단 금지**: 독해가 둘 이상인 경우, "더 자연스럽다", "더 문법적이다", "문언상 지지된다"는 식으로 어느 한 쪽에 우열을 매기는 것 자체를 삼간다.
  문언 트랙의 결론란에는 반드시 "문언상 중의적 — 입법취지·목적론으로 판단 이관"이라고만 기재하고, 결론은 ②③ 트랙에서만 도출한다.
- 용어 정의 선행: 법령에 정의된 용어는 그 정의를 따름
- 열거 규정: 열거 항목의 문언적 범위, "등"의 한정 vs 예시 여부
- 체계적 맥락: 같은 법·시행령 내 유사 조문과의 정합성

**② 입법취지 해석**
해당 조문·항이 신설 또는 개정된 이유와 목적을 분석한다.
**핵심 기능: 어느 독해가 해당 법령의 존재 이유(입법 목적)를 실현하고, 어느 독해가 그것을 무력화하는지를 판단하는 것이다.**
- 해당 조문이 어떤 문제를 해결하기 위해 만들어졌는가
- 보호하려는 법익과 의무 부과 대상의 관계
- 개정 전후를 명시적으로 비교하고, 개정의 효과 방향을 먼저 확정한다:
  · 새 요건이 추가된 것인지(범위 제한) vs 기존 요건이 구체화된 것인지(명확화)
  · 예외 대상이 확대된 것인지 vs 축소된 것인지 방향을 확정한 뒤 취지를 서술한다.
  · 범위가 확대된 개정이라면 "한정 의도"로 해석하지 않는다.
- **⚠ 회피 가능성이 결정적 논거가 되는 경우**: 두 독해 중 하나가 규정의 존재 이유(입법 목적)를 체계적으로 무력화하는 회피를 허용하는 경우, 그 독해는 입법취지에 반한다고 단정한다. 이 경우 "어느 쪽이 우위인지 단정하기 어렵다"는 유보 결론을 내려서는 안 된다. '의무부과에 대한 보수적 해석'은 취지가 명확할 때 판단 자체를 회피하는 근거가 아니다 — 그것은 자의적 의무 확대를 막기 위한 원칙이며, 입법 목적이 명백히 지지하는 방향으로 결론을 내리는 것을 막지 않는다.

**③ 목적론적 해석**
법 전체의 목적과 규정의 실질적 효과를 기준으로 해석한다.
**핵심 기능: 특정 독해가 채택될 경우 법이 실제로 작동하는가, 아니면 형해화(形骸化)되는가를 판단하는 것이다.**
- 해석 결과가 법의 보호 목적을 달성하는가
- 해석 결과가 실무상 부당한 결과(흠결, 과잉 제한, 의무 회피 경로 개방 등)를 낳지 않는가
- 동질적 성격의 권리·의무가 달리 취급될 합리적 이유가 있는가

---

### [3트랙 해석 분석] ← 아래 두 가지 형식 중 하나로 작성

**〔수렴하는 경우〕** 세 트랙이 같은 결론에 이를 때:
- 가장 강한 근거가 되는 트랙을 완전히 전개하고 결론을 명시한다.
  · 문언이 명확한 경우: ① 문언 주(主) 트랙
  · 문언이 중의적이라고 판단한 경우: ② 입법취지 또는 ③ 목적론이 주(主) 트랙
- 나머지 트랙은 한 줄로 확인한다.
  예: "② 입법취지·③ 목적론적으로도 동일한 결론 — (이유 1~2줄)"

**〔분기하는 경우〕** 트랙 간 결론이 다를 때:
- 세 트랙 모두 완전히 전개하고 각 트랙 말미에 중간 결론을 한 문장으로 명시한다.
  - → **문언적 결론**: (한 문장)
  - → **입법취지상 결론**: (한 문장)
  - → **목적론적 결론**: (한 문장)

**④ 선례 포지셔닝** (질의회신·판례가 제공된 경우에만)
검색된 선례가 위 세 트랙 중 어느 해석을 지지하는지 명시한다.
- 선례 있음: 📌 [선례 번호/출처] → (문언적 / 입법취지 / 목적론적) 해석 지지
  요지: ~한 경우에 ~라고 회신·판시하였는바,
  사실관계 차이: (본 건과 다른 점이 있으면 명시)
- 선례 없음: "유사 선례 없음 — 유권해석 확인 권장"
- **유추 적용 전 ratio 확인 의무**:
  선례를 본 건에 유추 적용하기 전, 반드시 아래 두 단계를 먼저 수행한다.
  1. **ratio 파악**: 선례가 그 결론에 이른 근거(판단 이유·목적)가 무엇인지 명시한다.
     예) "이 선례의 ratio는 '20m 도로가 일조·채광의 물리적 완충 역할을 한다'는 것임"
  2. **구조 동질성 검증**: 선례의 ratio가 본 건에도 동일하게 작동하는지 확인한다.
     동질하면 유추 적용, 동질하지 않으면 "구조 차이로 유추 불가 — 독립적 해석 필요"라고 명시한다.
     예) "도로(두 대지가 공유하는 물리적 요소) vs 구역 지정(각 대지에 독립적으로 부여되는 법적 지위) — 구조가 다르므로 선례의 '상호간' 논리를 그대로 이관할 수 없음"

### [결론]
세 트랙의 수렴 여부에 따라 아래 중 하나로 작성한다.

**[수렴하는 경우]** [확신도: 확정]
결론을 단정적으로 선언한다.
**쟁점 해소에서 멈추지 말고, 그 결과 실제 적용·불적용되는 구체적 조·항을 반드시 선언한다.**
예: "따라서 이 사안의 경우 「건축법」 제○조제○항이 적용됩니다." (법제처 회답 형식)

**[부분 수렴]** [확신도: 조건부]
일부 트랙이 수렴하고 일부가 다른 경우.
- 다수 트랙의 결론: ~으로 판단됨
- 소수 트랙(문언적/입법취지/목적론적)의 이견: ~

**[분기하는 경우]** [확신도: 해석분기]
- 문언적 해석에 따르면: ~으로 판단됨
- 입법취지 해석에 따르면: ~으로 판단됨
- 목적론적 해석에 따르면: ~으로 판단됨
- 실무상 어느 해석이 적용될지는 아래 [해석 분기점]을 참고하시기 바랍니다.

### [해석 분기점] ← 결론이 분기하는 경우에만 작성
결론을 가르는 핵심 판단 지점을 구체적으로 명시한다.
1. (쟁점이 되는 문구나 개념): ~로 보면 → 결론 A / ~로 보면 → 결론 B
2. (추가 분기점이 있으면):
※ 선례나 담당 기관의 유권해석이 확립되어 있다면 그에 따르는 것이 안전합니다.

### [관련 조문 확인]
① 직접 적용 조문: 법령명·조·항·호·별표 포함하여 원문 키워드 발췌
② 예외·특례·준용: (해당 시 서술, 없으면 "해당 없음")
③ 상충·연관 조문: (해당 시 서술)

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
## 출력 형식 및 문체 기준
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### 출력 형식
- **단락(paragraph)형 서술**이 원칙이다. `###` 헤더는 **[결론]과 [관련 조문]** 두 곳에만 사용하고, 나머지 분석 내용은 헤더 없이 자연스러운 단락으로 전개한다.
- **결론 우선**: 결론을 **첫 단락**에서 먼저 선언하고, 이후 단락에서 근거(법령 인용 → 논리 → 선례)를 서술한다. 법제처 회답 형식: "질의와 같이 ~에 해당하는 경우, 「건축법 시행령」 제○조제○항에 따라 ○○이 요구됩니다."
- **3트랙 해석**은 내부 판단 과정이다. 출력에서는 트랙 번호(①②③)나 "① 문언적 해석" 같은 레이블을 사용하지 않고, "「○○법 시행령」 제○조제○항에서는 ~라고 규정하고 있는바," / "같은 법 제○조의 입법 취지에 비추어 볼 때," / "따라서 ~으로 판단됨" 형태의 단락으로 표현한다.
- **[Step 0] 용어 정의**는 별도 섹션 헤더 없이, 이유 단락 첫 문장에 자연스럽게 녹인다: "「건축법 시행령」 제2조제13호나목에서 '주차' 용도를 부속용도로 정의하고 있는바,"
- **법령 인용**은 조·항·호 단위까지 구체적으로 명시한다: 「건축법 시행령」 제39조제1항제1호, 「건축법」 제43조제1항

### 문체 기준
- **단락 연결 공식**: 이유 단락은 `먼저 ~ 그리고 ~ 아울러 ~ 따라서`의 순서로 전개한다.
- **결론 어미**: "~라고 보는 것이 [문언에/취지 및 체계에] 부합하는 해석입니다", "~해야 합니다", "~을 의미합니다"
- **전제→결론 연결**: "~인바," 를 사용하여 논리 흐름을 자연스럽게 연결한다.
- **관점 제시**: "~에 비추어 볼 때,", "~을 종합하여 보면,"
- **부정 결론**: "~라고 보기는 어렵습니다"
- **반론 처리 공식**: 반대 해석이 예상될 때 "~이라는 의견이 있으나, ... 그러한 의견은 타당하지 않습니다"로 명시적으로 반박한다.
- **추가 논거 공식**: "~점도 이 사안을 해석할 때 고려해야 합니다"로 보조 논거를 추가한다.
- 유보 표현: "다만, ~에 대하여는 구체적인 사실관계를 확인하여 판단하여야 할 사항임"
- 재량 사항: 최종 판단이 허가권자 재량에 속하는 경우 반드시 명시
- 선례가 있으면 선례의 논리를 존중하되, 사실관계 차이점을 명시
- 같은 법·같은 시행령을 반복 지칭할 때는 "같은 법", "같은 영"으로 약칭한다

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 주의사항
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- 세 트랙은 항상 내부적으로 검토하되, **출력은 수렴 여부에 따라 압축**하세요
- 수렴 시: 가장 강한 트랙(통상 문언) 완전 전개 + 나머지 두 트랙 1줄 확인
- 분기 시: 세 트랙 모두 완전 전개 후 [해석 분기점] 작성
- 제공된 조문 내용을 벗어나는 추론은 삼가세요
- 별표1 문제는 별표1 전체(서두·총칙 성격 조문 포함)를 확인한 후 결론을 내세요
- 판례·질의회신의 사실관계가 본 건과 다르면 인용하지 마세요
- 확신도 '확정'은 두 해석이 모두 동일한 결론에 수렴할 때만 사용하세요
- 확신도 '해석분기'는 두 해석의 결론이 다를 때 사용하세요

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 출처 원칙 (반드시 준수)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### 답변 생성 우선순위
1. **[직접 참조 조문]** 섹션이 제공된 경우: 그 내용이 이 질문을 위해 DB에서 직접 가져온 것입니다. 반드시 이것을 1차 근거로 삼으세요. 내장지식과 충돌하면 DB 조문을 따르세요.
2. **[관련 법령 조문]** 섹션: 유사도 검색으로 찾은 조문. 적용 가능하면 사용하세요.
3. **[유사 질의회신 선례]** 섹션: 관련 있으면 반드시 인용하세요.
4. **내장지식**: 위 검색 결과에 없는 내용을 보충할 때만 사용. 단, 내장지식으로 법령 조문을 인용하는 경우 "(내장지식)"이라고 명시하세요.

### 답변 맨 끝에 반드시 [출처 요약] 추가
```
[출처 요약]
DB-조문: 참조함 (예: 건축법 시행령 별표1, 건축법 제○조) / 참조 없음
DB-선례: 참조함 (예: 법제처 25-0252) / 참조 없음
DB-입법요지: 참조함 (예: 건축법 시행령 34580호 개정이유) / 참조 없음
내장지식: 사용함 — (보충한 내용을 1줄로) / 사용 안 함
```
※ DB-입법요지는 [관련 개정연혁] 섹션의 개정이유·목적론적 키포인트를 실제로 답변에 활용한 경우에만 "참조함"으로 표시하세요."""


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
        "question_type":    "복수조문탐색형",
        "triggers":         [],
        "article_nodes":    [],
        "relation_types":   [],
        "law_hints":        [],
        "definition_terms": [],
    }

    # ── JSON 블록 파싱 (우선) ────────────────────────────
    json_match = re.search(r'```json\s*(\{.*?\})\s*```', pass1_text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            result["question_type"]    = data.get("question_type", result["question_type"])
            result["law_hints"]        = data.get("law_hints", [])
            result["definition_terms"] = data.get("definition_terms", [])
            result["relation_types"]   = data.get("relation_types", [])
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
# 출처 파서
# ============================================================

def parse_source_info(answer: str) -> dict:
    """
    답변 끝의 [출처 요약] 블록을 파싱.
    반환: {"db_law": bool, "db_qa": bool, "internal": bool,
           "db_law_detail": str, "db_qa_detail": str, "internal_detail": str}
    """
    info = {
        "db_law": False, "db_law_detail": "",
        "db_qa":  False, "db_qa_detail":  "",
        "db_amendment": False, "db_amendment_detail": "",
        "internal": False, "internal_detail": "",
    }
    m = re.search(r'\[출처 요약\](.*?)(?:\Z)', answer, re.DOTALL)
    if not m:
        return info
    block = m.group(1)

    for line in block.splitlines():
        if line.startswith("DB-조문:"):
            val = line.split(":", 1)[1].strip()
            info["db_law"] = val.startswith("참조함")
            info["db_law_detail"] = val
        elif line.startswith("DB-선례:"):
            val = line.split(":", 1)[1].strip()
            info["db_qa"] = val.startswith("참조함")
            info["db_qa_detail"] = val
        elif line.startswith("DB-입법요지:"):
            val = line.split(":", 1)[1].strip()
            info["db_amendment"] = val.startswith("참조함")
            info["db_amendment_detail"] = val
        elif line.startswith("내장지식:"):
            val = line.split(":", 1)[1].strip()
            info["internal"] = val.startswith("사용함")
            info["internal_detail"] = val

    return info


# ============================================================
# 2-pass 생성 파이프라인
# ============================================================

class Generator:
    def __init__(self):
        self._client    = get_claude_client()
        self._retriever = None
        # Streamlit @st.cache_resource 환경에서 시작 시 미리 워밍업
        # → 첫 질의도 두 번째 질의와 동일한 속도
        self._get_retriever()   # 임베딩 모델 로드
        load_memo_bullets()     # 메모 캐시 준비

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

        parsed           = parse_pass1(pass1_text)
        question_type    = parsed["question_type"]
        triggers         = parsed["triggers"]
        article_nodes    = parsed["article_nodes"]
        relation_types   = parsed["relation_types"]
        law_hints        = parsed["law_hints"]
        definition_terms = parsed["definition_terms"]

        if verbose:
            print(f"\n→ 질문 유형: {question_type}")
            print(f"→ 관계 유형: {[r['type'] for r in relation_types]}")
            print(f"→ 법령 힌트: {law_hints}")
            if definition_terms:
                print(f"→ 정의 확인 용어: {definition_terms}")

        # ── 검색 ──────────────────────────────────────
        if verbose:
            print("\n[검색] 관련 조문 + 판례 검색 중...")

        retriever = self._get_retriever()
        search_query = query
        if triggers:
            search_query += " " + " ".join(triggers[:3])
        if definition_terms:
            search_query += " " + " ".join(definition_terms[:3])

        law_docs, qa_docs, case_docs = retriever.retrieve(
            query=search_query,
            question_type=question_type,
            extra_article_nodes=article_nodes if article_nodes else None,
            relation_types=relation_types if relation_types else None,
            law_hints=law_hints if law_hints else None,
            definition_terms=definition_terms if definition_terms else None,
        )

        # 조문 해석 프레임 로드 (law_hints + definition_terms 모두 사용)
        article_roles = retriever.get_article_roles(
            law_hints, definition_terms=definition_terms
        ) if (law_hints or definition_terms) else []

        # memo 주입: retrieved docs와 linked_to/태그 결정론적 매칭
        memo_docs      = retriever.fetch_linked_memos(law_docs, qa_docs, case_docs)
        amendment_docs = retriever.fetch_linked_amendments(law_docs)

        context = retriever.format_context(
            law_docs, qa_docs, case_docs,
            article_roles=article_roles if article_roles else None,
            memo_docs=memo_docs if memo_docs else None,
            amendment_docs=amendment_docs if amendment_docs else None,
        )

        if verbose:
            print(f"→ 법령 조문 {len(law_docs)}건 / 질의회신 {len(qa_docs)}건 / 판례 {len(case_docs)}건 / 메모 {len(memo_docs)}건 / 개정연혁 {len(amendment_docs)}건 주입됨")

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

        def_terms_note = ""
        if definition_terms:
            def_terms_note = (
                "\n## [Step 0] 정의 확인 필요 용어\n"
                "아래 용어들의 법령상 정의를 3트랙 분석 전에 먼저 확인하세요:\n"
                + "\n".join(f"- \"{t}\"" for t in definition_terms)
            )

        pass2_input = f"""## 질문
{query}

## Pass 1 분석 결과
{pass1_text}
{rel_type_summary}{def_terms_note}
## 검색된 관련 조문 및 판례
{context}

위 내용을 바탕으로 완전한 CoT 답변을 작성하세요."""

        # ── 메모 주입 ────────────────────────────────────
        memo_bullets = load_memo_bullets()
        if memo_bullets:
            pass2_system = (
                PASS2_SYSTEM
                + "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                + "## 해석 원칙 메모 (누적 학습)\n"
                + "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                + "아래는 이전 해석례 분석에서 확립된 AI 오독 패턴 및 해석 원칙입니다.\n"
                + "관련 사안이 나오면 반드시 적용하세요:\n\n"
                + memo_bullets
            )
        else:
            pass2_system = PASS2_SYSTEM

        answer = call_claude(self._client, pass2_system, pass2_input)

        if verbose:
            print(f"\n{'='*60}")
            print("[최종 답변]")
            print(f"{'='*60}")
            print(answer)

        source_info = parse_source_info(answer)

        return {
            "query":            query,
            "pass1":            pass1_text,
            "relation_types":   relation_types,
            "law_hints":        law_hints,
            "definition_terms": definition_terms,
            "context":          context,
            "answer":           answer,
            "law_docs":         law_docs,
            "qa_docs":          qa_docs,
            "source_info":      source_info,
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
