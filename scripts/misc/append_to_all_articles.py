from pathlib import Path

src = Path("data/raw_laws/도시정비법시행규칙_articles.jsonl").read_text(encoding="utf-8")
with open("data/raw_laws/all_articles.jsonl", "a", encoding="utf-8") as f:
    f.write(src)

count = sum(1 for l in open("data/raw_laws/all_articles.jsonl", encoding="utf-8") if l.strip())
print(f"all_articles.jsonl 총 레코드: {count}")
