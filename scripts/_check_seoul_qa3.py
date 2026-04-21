import json

# labeled_with_doc.jsonl 분석
records = []
with open('data/labeled_with_doc.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if line:
            records.append(json.loads(line))

print(f"총 레코드 수: {len(records)}")
print(f"첫번째 레코드 키: {list(records[0].keys())}")
print()

# doc_agency 분포
agencies = {}
for r in records:
    ag = r.get('doc_agency', '')
    agencies[ag] = agencies.get(ag, 0) + 1
print("기관별 분포:")
for k, v in sorted(agencies.items(), key=lambda x: -x[1])[:20]:
    print(f"  {v:5d}  {k}")

# tag 분포
tags = {}
for r in records:
    t = r.get('tag', '')
    tags[t] = tags.get(t, 0) + 1
print("\ntag 분포:")
for k, v in sorted(tags.items(), key=lambda x: -x[1]):
    print(f"  {v:5d}  {k}")
