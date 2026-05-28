import sys, json
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

BASE = Path(__file__).parent.parent

# all_articles.jsonl에서 주택법 시행령 제16조 샘플 확인
path = BASE / "data/raw_laws/all_articles.jsonl"
count = 0
for line in path.read_text(encoding='utf-8').splitlines():
    if not line.strip():
        continue
    obj = json.loads(line)
    if '주택법 시행령' in obj.get('law_name','') and '제16조' in obj.get('article_no',''):
        print(f"law_name: {obj['law_name']}")
        print(f"article_no: {obj['article_no']}")
        print(f"article_title: {obj.get('article_title','')}")
        print(f"enforcement_date: {obj.get('enforcement_date','')}")
        print(f"content 앞 400자:\n{obj['content'][:400]}")
        print("---")
        count += 1
        if count >= 2:
            break
