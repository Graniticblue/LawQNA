# LawQNA — 세션 공통 지침

한국 건축·국토 법령 RAG (건축법·국토계획법·주택법·도시정비법 Q&A). chainlit + Railway.
학습 자산은 개별 해석례가 아니라 **이월되는 논지 계열**이다.

## 절대 규칙 (모델·세션 무관)

1. **공동 판정**: eval ⑥b 이후의 판독·반영·포지션 판정(R/M/A/B/X/L)은 사용자와 공동.
   AskUserQuestion으로 제안 후 확정 — 단독 확정 금지.
2. **판단 필드 수동**: gist·relation_name·position·doctrine_terms·계열명은 매 사안 수동 판단.
   헬퍼(scripts/curate_lib.py)는 검증 전용, 생성 금지.
3. **케이스패치 금지**: 메커니즘 보수는 전역 이득 수정만. "다른 질의에도 이득인가?"로 검문.
4. **대장 밖 학습 금지**: 모든 학습은 data/ingest_reports/학습후보_체크리스트.md의
   3단 장부(등재→완료→eval 후보)를 거친다.
5. **절차 생략 금지**: 배치·부채 청산이라도 eval 5단계를 건별 전부 밟는다.

## 상세 절차 (필독)

**새 해석례·판례 학습, eval 측정, 저점 처방, 판정 축, 커밋 규칙의 전 절차·코드 스니펫은
→ [data/ingest_reports/학습트랙_운영가이드.md](data/ingest_reports/학습트랙_운영가이드.md)**
학습·측정 요청을 받으면 이 가이드를 먼저 읽고 그대로 따를 것 (자기완결 문서).

## 자주 쓰는 명령

- 재인덱싱 3종: `REINDEX_QA=1`(해석례·회신) / `REINDEX_AUX=1`(개정이력·메모·원칙) / `FORCE_REINDEX=1`(전량 — 법령 추가 후 필수).
  모두 `PYTHONIOENCODING=utf-8 <플래그> python startup.py` (UTF-8 없으면 조용히 실패 — tail로 완주 확인)
- 판례 인덱싱: `python ingest/ingest_court_cases.py`
- 법령 추가: `python ingest/ingest_law_from_api.py --law "법령명"` (`--dry-run` 먼저) → FORCE_REINDEX
- 스키마 self-test: `python scripts/curate_lib.py` → "신규 스키마 위반 0" 확인 후 커밋
- 시제 게이트: `python scripts/check_temporal_drift.py --code XX-XXXX` (exit 2 = 커밋 금지)
- 검수 보고서: `python scripts/make_ingest_report.py --code XX-XXXX` / `--case 사건번호`

## 커밋

- 접두 `data:`(학습)/`eval:`(측정)/`feat:`·`fix:`, 메시지에 eval 결과와 `(판정: X·공동)` 포함.
- `LawQNA_대화_*.md` 대화 로그는 커밋에서 제외.
- Railway push는 사용자 수동 — 어시스턴트가 배포하지 않는다.
