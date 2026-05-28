import sys
sys.stdout.reconfigure(encoding='utf-8')
count = sum(1 for l in open("data/raw_laws/all_articles.jsonl", encoding="utf-8") if l.strip())
print(f"all_articles.jsonl 총 레코드: {count}")
