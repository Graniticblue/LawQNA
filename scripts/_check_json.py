import json

with open('data/qa_precedents/updates/법제처_15-0688.jsonl', 'r', encoding='utf-8') as f:
    content = f.read()

print(f"총 길이: {len(content)}")
print(f"컬럼 654 주변: {repr(content[640:680])}")

try:
    json.loads(content.strip())
    print("JSON 파싱 OK")
except json.JSONDecodeError as e:
    print(f"오류: {e}")
    print(f"위치 {e.pos} 주변: {repr(content[e.pos-20:e.pos+20])}")
