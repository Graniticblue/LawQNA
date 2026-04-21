import json, sys
sys.stdout.reconfigure(encoding='utf-8')

# 제27조의2제1항제1호 → 제27조의2 승격용 전체 내용 확인
d = json.loads(open('data/article_roles/건축법시행령_제27조의2제1항제1호.json', encoding='utf-8').read())
print(json.dumps(d, ensure_ascii=False, indent=2))
