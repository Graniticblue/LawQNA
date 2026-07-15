#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scan_citation_candidates.py -- 학습 코퍼스 내부 인용에서 학습 후보 감지

학습된 해석례(qa_precedents/updates)와 판례(court_cases)의 본문·참조판례에
인용된 번호 중 ① 미학습이고 ② 학습후보_체크리스트.md에 미등재인 것을 찾는다.
학습 사이클의 부속 단계: 새 학습 커밋 전후로 돌려서 감지분을 체크리스트에
등록일·출처(인용감지)와 함께 추가한다.

사용법: python scripts/scan_citation_candidates.py
"""
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))
from ingest import cite_verify as cv  # noqa: E402

CHECKLIST = BASE_DIR / "data" / "ingest_reports" / "학습후보_체크리스트.md"


def main():
    learned = cv._load_learned()
    listed = CHECKLIST.read_text(encoding="utf-8") if CHECKLIST.exists() else ""
    found: dict[str, dict] = {}

    def note(num: str, kind: str, src: str):
        if num in learned or num in listed:
            return
        found.setdefault(num, {"kind": kind, "seen_in": set()})["seen_in"].add(src)

    # 해석례 레코드: 모델 텍스트(회답+이유)의 인용
    for p in sorted((BASE_DIR / "data" / "qa_precedents" / "updates").glob("법제처_*.jsonl")):
        try:
            rec = json.loads(open(p, encoding="utf-8").readline())
            text = rec["contents"][1]["parts"][0]["text"]
        except Exception:
            continue
        code = rec.get("doc_code", p.stem)
        for c in cv.extract_citations(text):
            if c["num"] != code:
                note(c["num"], c["kind"], f"해석례 {code}")

    # 판례 레코드: holding/reasoning + related_cases (정식 인용 표기 파서 재사용)
    for p in sorted((BASE_DIR / "data" / "court_cases").glob("*.jsonl")):
        try:
            rec = json.loads(open(p, encoding="utf-8").readline())
        except Exception:
            continue
        cid = rec.get("case_id", "")
        blob = " / ".join([str(rec.get("holding", "")), str(rec.get("reasoning_summary", "")),
                           " / ".join(rec.get("related_cases", []))])
        for c in cv.extract_citations(blob):
            if c["num"] != cid:
                note(c["num"], c["kind"], f"판례 {cid}")

    if not found:
        print("신규 감지 없음 — 코퍼스 내부 인용은 전부 학습됐거나 체크리스트에 등재됨.")
        return
    print(f"감지 {len(found)}건 (미학습·미등재) — 중요도를 판단해 체크리스트에 등록할 것:")
    for num, v in sorted(found.items()):
        kind = "해석례" if v["kind"] == "expc" else "판례"
        print(f"  - [{kind}] {num}  ← {', '.join(sorted(v['seen_in']))}")


if __name__ == "__main__":
    main()
