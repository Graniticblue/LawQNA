# -*- coding: utf-8 -*-
"""
pack_recovered_for_index.py — 복원된 질의회신(seoul_qa_recovered.jsonl)을
02_Indexer_BASE.py의 qa_precedents 인덱싱 형식(contents 채팅 + doc 필드)으로
변환해 data/qa_precedents/updates/ 에 놓는다.

답변은 CoT enrich 없이 회신 원문 그대로 담는다 — 인덱서가 embed_text를
"[질문]...[답변]원문"으로 구성하고, chainlit 팝업 정리(_clean_precedent_body)가
[답변] 마커 이후를 표시하므로 원문이 그대로 노출된다(내부 분석문 오염 없음).

사용: python scripts/misc/pack_recovered_for_index.py
출력: data/qa_precedents/updates/seoul_qa_recovered_202607.jsonl
이후: 로컬 검증 후 커밋 → Railway REINDEX_QA=true 재배포(완료 후 변수 제거)
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "seoul_qa_recovered.jsonl"
OUT = ROOT / "data" / "qa_precedents" / "updates" / "seoul_qa_recovered_202607.jsonl"

rows = [json.loads(l) for l in SRC.read_text(encoding="utf-8").splitlines() if l.strip()]
out_rows = []
for r in rows:
    out_rows.append({
        "contents": [
            {"role": "user",  "parts": [{"text": r["question"]}]},
            {"role": "model", "parts": [{"text": r["answer"]}]},
        ],
        "doc_ref":    r["doc_ref"],
        "doc_agency": r["doc_agency"],
        "doc_code":   r["doc_code"],
        "doc_date":   r["doc_date"],
        "tag":        "seoul 2015 recovered",
    })

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in out_rows) + "\n",
               encoding="utf-8")
print(f"저장: {OUT} ({len(out_rows)}건)")
