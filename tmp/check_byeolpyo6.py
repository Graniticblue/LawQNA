import sys
sys.stdout.reconfigure(encoding='utf-8')
import chromadb

client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('law_articles')

r = col.get(include=["metadatas"])
metas = r['metadatas']

# 국토계획법 관련 법령 전체 목록
국토_laws = set()
for m in metas:
    name = m.get('law_name', '')
    if '국토' in name:
        국토_laws.add(name)
print("국토 관련 법령:", 국토_laws)

# 별표 청크 전체
byeolpyo = [(m.get('law_name'), m.get('article_no'), m.get('article_title'))
            for m in metas if m.get('is_byeolpyo') == 'true']
print(f"\nis_byeolpyo=true 청크 총 {len(byeolpyo)}개:")
for item in sorted(set(byeolpyo)):
    print(f"  {item[0]} | {item[1]} | {item[2]}")
