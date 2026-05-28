import sys, json
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

BASE = Path(__file__).parent.parent
target = "2003다70041"

for p in BASE.glob("data/**/*.jsonl"):
    try:
        lines = p.read_text(encoding='utf-8').splitlines()
        for line in lines:
            if not line.strip():
                continue
            obj = json.loads(line)
            text = json.dumps(obj, ensure_ascii=False)
            if target in text:
                print(f"\n파일: {p.relative_to(BASE)}")
                print(f"  law_name : {obj.get('law_name','')}")
                print(f"  article_no: {obj.get('article_no','')}")
                print(f"  내용 앞 200자:\n  {json.dumps(obj, ensure_ascii=False)[:300]}")
    except Exception as e:
        pass
