import sys
sys.stdout.reconfigure(encoding='utf-8')
import importlib.util

spec = importlib.util.spec_from_file_location('ret', '05_Retriever.py')
mod  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# 파서 테스트
hints = [
    '건축법 시행령 별표1',
    '건축법 제2조',
    '건축법 시행령 제86조제2항',
    '국토의 계획 및 이용에 관한 법률 시행령 별표2',
]
print('=== _parse_law_hint 테스트 ===')
for h in hints:
    law, art, byeolpyo = mod._parse_law_hint(h)
    print(f'  {h!r}')
    print(f'    → law={law!r}, art={art!r}, byeolpyo={byeolpyo}')

# 실제 DB 페칭 테스트
print('\n=== fetch_exact_articles 테스트 ===')
print('임베딩 모델 로드 중...')
r = mod.Retriever()
results = r._searcher.fetch_exact_articles(
    ['건축법 시행령 별표1'],
    top_n=3,
)
print(f'결과: {len(results)}건')
for d in results:
    print(f'  [{d.score_type}] {d.law_name} {d.article_no}')
    print(f'    {d.content[:100]}...')
