import sys, json
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

path = Path('data/law_amendments/amendments.jsonl')
records = [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]

for r in records:
    if r['amendment_id'] != '국토계획법시행령_20240807_34774호':
        continue

    # 1. 개정전_기준법령
    r['개정전_기준법령'] = '국토의 계획 및 이용에 관한 법률 시행령 [시행 2024. 5. 28] [대통령령 제34531호, 2024. 5. 28, 일부개정]'

    # 2. 제32조의2 삭제 개정전 원문 보완
    for jm in r['조문_변경']:
        if jm['조문'] == '제32조의2 삭제':
            jm['개정전'] = (
                "제32조의2(입지규제최소구역의 지정 대상) 법 제40조의2제1항제6호에서 "
                "\"대통령령으로 정하는 지역\"이란 다음 각 호의 지역을 말한다.\n"
                "1. 「산업입지 및 개발에 관한 법률」 제2조제8호다목에 따른 도시첨단산업단지\n"
                "2. 「빈집 및 소규모주택 정비에 관한 특례법」 제2조제3호에 따른 소규모주택정비사업의 시행구역\n"
                "3. 「도시재생 활성화 및 지원에 관한 특별법」 제2조제1항제6호나목에 따른 "
                "근린재생형 활성화계획을 수립하는 지역"
            )
            break

    break

with open(path, 'w', encoding='utf-8') as f:
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')

print('완료: 국토계획법시행령_20240807_34774호 업데이트')
print('  - 개정전_기준법령 추가')
print('  - 제32조의2 삭제 개정전 원문 보완')
