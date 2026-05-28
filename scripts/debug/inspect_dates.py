import json, sys
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(__file__).parent.parent

# ── amendments.jsonl 구조 확인 ──
amend_path = BASE / "data/law_amendments/amendments.jsonl"
records = [json.loads(l) for l in amend_path.read_text(encoding="utf-8").splitlines() if l.strip()]

print(f"amendments.jsonl: {len(records)}건")
print("샘플 키:", list(records[0].keys()))
print()
for r in records[:3]:
    for k in ["법령명", "공포일", "시행일", "법령호"]:
        print(f"  {k}: {r.get(k, 'N/A')}")
    print()

# ── 법령명별 공포일 범위 ──
print("=== 법령명별 개정이력 범위 ===")
by_law = defaultdict(list)
for r in records:
    by_law[r.get("법령명", "(없음)")].append(r.get("공포일", ""))

for law, dates in sorted(by_law.items()):
    dates = sorted(d for d in dates if d)
    print(f"  {law}: {dates[0] if dates else '?'} ~ {dates[-1] if dates else '?'}  ({len(dates)}건)")

# ── 조문 DB JSONL ──
print("\n=== 조문 DB JSONL 파일 목록 ===")
for p in sorted(BASE.glob("data/**/*.jsonl")):
    print(f"  {p.relative_to(BASE)}")

# all_articles.jsonl 구조 확인
aa = BASE / "data/raw_laws/all_articles.jsonl"
if aa.exists():
    sample = [json.loads(l) for l in aa.read_text(encoding="utf-8").splitlines()[:5] if l.strip()]
    print("\nall_articles.jsonl 샘플 키:", list(sample[0].keys()) if sample else "없음")
    for s in sample[:2]:
        for k in ["law_name", "법령명", "공포일", "시행일"]:
            if k in s:
                print(f"  {k}: {s[k]}")
        print()
