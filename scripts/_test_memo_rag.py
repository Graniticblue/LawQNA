import sys
sys.stdout.reconfigure(encoding='utf-8')

import importlib.util

spec = importlib.util.spec_from_file_location('ret', '05_Retriever.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

r = mod.Retriever()

queries = [
    "외벽 마감재료 방화기준 대수선 허가",
    "공공공지 이격거리 제86조",
    "공동주택 주택법 건축법 우선",
]

for q in queries:
    memos = r.retrieve_memos(q, top_k=3)
    print(f"\n[{q}] → {len(memos)}건")
    for m in memos:
        print(f"  [{m['memo_id']}] score={m['score']} — {m['title'][:50]}")
