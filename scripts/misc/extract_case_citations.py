"""법제처 해석례 JSONL에서 판례 인용 목록 추출"""
import json, re, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

BASE = Path(__file__).parent.parent

# 판례 패턴: 대법원/헌법재판소/서울고법 등
CASE_PATTERN = re.compile(
    r'(대법원|헌법재판소|서울고등법원|서울행정법원|서울중앙지방법원|부산고등법원|광주고등법원)'
    r'\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\s*선고\s*'
    r'(\d{4}[가-힣다두]\d+)\s*판결'
)

cases = {}

# qa_precedents 폴더 순회
for p in sorted(BASE.glob("data/qa_precedents/**/*.jsonl")):
    try:
        for line in p.read_text(encoding='utf-8').splitlines():
            if not line.strip(): continue
            obj = json.loads(line)
            text = json.dumps(obj, ensure_ascii=False)
            for m in CASE_PATTERN.finditer(text):
                case_id = f"{m.group(1)} {m.group(2)}.{m.group(3)}.{m.group(4)}. {m.group(5)}"
                src = p.stem
                if case_id not in cases:
                    cases[case_id] = []
                if src not in cases[case_id]:
                    cases[case_id].append(src)
    except Exception:
        pass

print(f"총 {len(cases)}개 판례 인용 발견\n")
for case, srcs in sorted(cases.items()):
    print(f"  {case}")
    for s in srcs:
        print(f"    ← {s}")
