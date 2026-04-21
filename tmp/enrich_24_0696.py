import sys, json
sys.stdout.reconfigure(encoding='utf-8')

path = 'data/qa_precedents/updates/법제처_24-0696.jsonl'

with open(path, encoding='utf-8') as f:
    rec = json.loads(f.read())

# Claude 보강 수동 입력
rec['relation_type']  = 'SCOPE_CL'
rec['relation_name']  = '적용범위확정형'
rec['label_summary']  = (
    '장애인용 승강기 이용을 위한 승강장은 건축법 시행령 제119조제1항제2호다목8)의 '
    '건축면적 산입 제외 대상(장애인용 승강기·에스컬레이터·휠체어리프트·경사로)에 포함되지 않는다. '
    '별표 2가 승강장을 편의시설로 열거하지 않아 전제 미충족.'
)
rec['search_tags'] = (
    '#건축면적산입제외 #장애인용승강기 #승강장 #건축법시행령제119조 '
    '#다목8 #별표연계제외조항 #역방향논증 #장애인편의시설 '
    '#국토교통부고시 #면적세부산정기준 #24-0696'
)
rec['logic_steps'] = [
    {"seq": 1, "role": "ANCHOR",       "title": "다목8) 명시적 열거 한정 — 승강장 미열거"},
    {"seq": 2, "role": "PREREQUISITE", "title": "별표 2 역방향 확인 — 승강장은 편의시설 미열거"},
    {"seq": 3, "role": "ANALYSIS",     "title": "국토교통부 고시 명시 — 승강장 건축면적 산입"},
    {"seq": 4, "role": "RESOLUTION",   "title": "전제 이중 미충족 → 산입 제외 불가"},
]

# search_tags를 contents 텍스트에도 반영
model_text = rec['contents'][1]['parts'][0]['text']
if '[검색태그]' not in model_text:
    rec['contents'][1]['parts'][0]['text'] = model_text + f"\n\n[검색태그] {rec['search_tags']}"

with open(path, 'w', encoding='utf-8') as f:
    f.write(json.dumps(rec, ensure_ascii=False) + '\n')

print('보강 완료')
print('search_tags:', rec['search_tags'][:80])
