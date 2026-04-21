import sys, json
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

path = Path('data/law_amendments/amendments.jsonl')
records = [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]

for r in records:
    if r['amendment_id'] != '건축법시행규칙_20250114_1439호':
        continue

    r['개정전_기준법령'] = "건축법 시행규칙 [시행 2024. 12. 17] [국토교통부령 제1419호, 2024. 12. 17, 일부개정]"

    r['조문_변경'] = [
        {
            "조문": "제12조의3②",
            "개정전": (
                "제1항에도 불구하고 허가권자는 지방건축위원회의 심의를 거쳐 "
                "다른 시설군의 용도간의 복수 용도를 허용할 수 있다."
            ),
            "개정후": (
                "제1항에도 불구하고 허가권자는 지방건축위원회의 심의를 거쳐 "
                "다른 시설군의 용도간의 복수 용도를 허용할 수 있다. "
                "다만, 영 제14조제5항제4호나목에 따른 종교시설 및 같은 항 제6호다목에 따른 "
                "노유자시설(老幼者施設) 간의 복수 용도를 허용하려는 경우에는 "
                "지방건축위원회의 심의를 생략할 수 있다."
            ),
            "비고": "단서 신설 — 종교시설-노유자시설 간 복수 용도 허용 시 지방건축위원회 심의 생략 가능"
        }
    ]
    break

with open(path, 'w', encoding='utf-8') as f:
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')

print("완료: 건축법시행규칙_20250114_1439호 — 개정전 기준법령 + 조문_변경 추가")
