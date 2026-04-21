import sys, json
sys.stdout.reconfigure(encoding='utf-8')
import chromadb

client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('law_articles')

# 국토계획법 시행규칙 법령ID 확인
r = col.get(where={"law_name": {"$eq": "국토의 계획 및 이용에 관한 법률 시행규칙"}},
            include=["metadatas"], limit=1)
print("시행규칙 메타:", json.dumps(r['metadatas'][0], ensure_ascii=False, indent=2))

# 기존 byeolpyo 항목 하나 확인 (형식 참고)
r2 = col.get(where={"$and": [{"law_name": {"$eq": "국토의 계획 및 이용에 관한 법률 시행령"}},
                              {"is_byeolpyo": {"$eq": "true"}}]},
             include=["documents", "metadatas"], limit=1)
print("\n시행령 별표 메타:", json.dumps(r2['metadatas'][0], ensure_ascii=False, indent=2))
print("시행령 별표 문서 앞부분:", r2['documents'][0][:200])
