import json, sys
sys.stdout.reconfigure(encoding="utf-8")
with open("data/qa_precedents/updates/법제처_14-0840.jsonl", encoding="utf-8") as f:
    rec = json.loads(f.readline())
da = rec.get("doc_analysis", {})
print("cause_analysis:", da.get("cause_analysis", "")[:150])
print("legal_logic steps:", len(da.get("legal_logic", [])))
for s in da.get("legal_logic", []):
    print(f"  [{s['seq']}] {s['role']} — {s['title']}")
print("key_provisions:", da.get("key_provisions", []))
