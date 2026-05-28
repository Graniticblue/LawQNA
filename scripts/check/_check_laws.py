import json, os

out = []

# keyword_law_map에서 법령 목록 추출
d = json.load(open('data/keyword_law_map.json', encoding='utf-8'))
laws = set()
for v in d.values():
    for law in v.get('laws', []):
        laws.add(law)
out.append("=== keyword_law_map 법령 목록 ===")
for l in sorted(laws):
    out.append(l)

# law_cache 파일 목록
out.append("\n=== law_cache 파일 ===")
for f in sorted(os.listdir('data/law_cache')):
    out.append(f)

# labeled_with_doc에서 doc_title 샘플
out.append("\n=== labeled_with_doc doc 샘플 ===")
titles = set()
with open('data/labeled_with_doc.jsonl', encoding='utf-8') as f:
    for line in f:
        d2 = json.loads(line)
        t = d2.get('doc_title') or d2.get('law_name') or d2.get('source')
        if t:
            titles.add(t)
for t in sorted(titles)[:20]:
    out.append(t)

with open('_law_list_out.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))
print("done")
