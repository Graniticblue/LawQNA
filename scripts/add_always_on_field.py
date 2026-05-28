#!/usr/bin/env python3
"""
memos.jsonl의 always-on 메모 6건에 `always_on: true` + `bullet` 필드 추가.
하드코딩된 MANUAL_BULLETS를 데이터로 이주.
"""
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ALWAYS_ON_BULLETS = {
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
    "memo_023": (
        "건축기준(바닥면적·높이·층수·용적률) 특례 규정을 중첩 적용하려면 명시적 허용 규정이 있어야 한다. "
        "없으면 중첩 불가가 원칙(프롬프트 §5-2 참조). "
        "§5 '특별 규정 우선 원칙'은 충돌 해소 원칙이지 중첩 허용 원칙이 아니다 — "
        "두 규정이 모두 같은 원칙 조문의 예외(특례)인 경우 특히 주의. "
        "각 특례의 적용 전제(해당 공간이 본래 산입될 공간인가)를 독립적으로 확인한다. "
        "'두 규정의 취지가 다르니 동시 적용 가능'이라는 목적론 논리는 중첩의 근거가 아니다(법제처 발코니 나목+라목 사례)."
    ),
}

path = Path(__file__).parent.parent / "data" / "memos.jsonl"

records = []
with open(path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))

updated = 0
for rec in records:
    mid = rec.get("memo_id", "")
    if mid in ALWAYS_ON_BULLETS:
        rec["always_on"] = True
        rec["bullet"] = ALWAYS_ON_BULLETS[mid]
        updated += 1
        print(f"  업데이트: {mid}")

with open(path, "w", encoding="utf-8") as f:
    for rec in records:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

print(f"\n완료: {updated}건 always_on 필드 추가 → {path}")
