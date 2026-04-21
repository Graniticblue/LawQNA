import sys, json
sys.stdout.reconfigure(encoding='utf-8')
with open('data/memos.jsonl', encoding='utf-8') as f:
    for i, line in enumerate(f, 1):
        line = line.strip()
        if not line:
            print(f'  line {i}: 빈줄')
            continue
        try:
            json.loads(line)
        except Exception as e:
            print(f'  line {i}: 오류 - {e}')
            print(f'  내용: {repr(line[:200])}')
print('검사 완료')
