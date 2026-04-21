import sys, json
sys.stdout.reconfigure(encoding='utf-8')

with open('data/memos.jsonl', encoding='utf-8') as f:
    lines = f.readlines()

clean = []
for line in lines:
    line = line.strip()
    if not line:
        continue
    try:
        json.loads(line)
        clean.append(line)
    except Exception:
        print(f'  제거: {repr(line[:80])}')

with open('data/memos.jsonl', 'w', encoding='utf-8') as f:
    for line in clean:
        f.write(line + '\n')

print(f'\n정리 완료: {len(clean)}개 메모 유지')
