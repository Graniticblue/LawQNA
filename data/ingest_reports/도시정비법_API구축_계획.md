# 도시정비법 계열 API 구축 계획 (2026-07-15)

대상: 「도시 및 주거환경정비법」 + 시행령 + 시행규칙 3종.
도구: `ingest/ingest_law_from_api.py` (기존 범용 파이프라인 — 본문·별표·개정이력·취지 일괄).

## 0. 진단 — 왜 지금 검색이 안 되나

- **법률·시행령은 인덱서 소스(all_articles.jsonl, 26종 2,480건)에 병합된 적이 없다.**
  기존 `ingest/ingest_도시정비법.py`·`ingest_도시정비법시행령.py`는 PDF 파싱 후 로컬 chroma에
  **직접 add**하는 방식이라, 프로덕션이 all_articles.jsonl로 재빌드할 때마다 증발했다.
  (스냅샷 jsonl 3본은 raw_laws에 존재: 법 185조/시행 20260102, 영 133조/20260324, 규칙 52조/20260211)
- 시행규칙만 all_articles에 수록돼 있음 (2026-02-11판).
- 실증: eval 3회에서 AI가 도시정비법 조문을 창작 — 10-0306(영 구 제12조제8호 내용 날조),
  19-0103(제101조 단서 문구 재구성 오류), 22-0869 계열.
- 개정이력(amendments.jsonl 525건/14법령)에 도시정비법 계열 **0건**.

## 1. 실행 순서 (사용자 복귀 후)

```bash
# 사전: .env에 LAW_API_KEY(있음), GOOGLE_API_KEY(Gemini enrich용 — 답변 모델과 동일 키)

# ① 드라이런으로 응답 구조·규모 확인
python ingest/ingest_law_from_api.py --law "도시 및 주거환경정비법" --dry-run

# ② 본문+별표 먼저 (개정이력은 분리 실행 — enrich가 오래 걸림)
python ingest/ingest_law_from_api.py --law "도시 및 주거환경정비법" --skip-amendments
python ingest/ingest_law_from_api.py --law "도시 및 주거환경정비법 시행령" --skip-amendments
python ingest/ingest_law_from_api.py --law "도시 및 주거환경정비법 시행규칙" --skip-amendments

# ③ 개정이력 (체크포인트 지원 — 중단돼도 이어짐. --limit로 시험 가능)
python ingest/ingest_law_from_api.py --law "도시 및 주거환경정비법" --amendments-only
python ingest/ingest_law_from_api.py --law "도시 및 주거환경정비법 시행령" --amendments-only
python ingest/ingest_law_from_api.py --law "도시 및 주거환경정비법 시행규칙" --amendments-only

# ④ 로컬 검증(§4) → 커밋/push → ⑤ 배포 재인덱싱(§5)
```

## 2. 3대 요구사항 매핑

| 요구 | 처리 주체 | 방식 |
|---|---|---|
| **항·호 구분** | `02_Indexer_BASE.split_article_into_hangs` | 다항 조문을 **항 단위 벡터**로 분할하되 각 항에 조 헤더(`[법령명] 제N조(제목)`) 프리픽스 — 128토큰 절단 방지. '호'는 소속 항 청크 안에 온전히 유지(호 단위 과분할 없음). API 소싱이라 PDF 하드랩·목차 오염 없음 |
| **이력** | `fetch_history` | eflaw 연혁에서 **일부·전부개정만**(타법개정·제정 제외, 기존 정책), 공포번호 dedupe. 규모(실측): 법 57건(일부56+전부1)·영 39건·규칙 17건 = **약 113건** |
| **취지** | `fetch_revision_docs` + Gemini enrich | 각 판의 제개정이유·개정문·부칙 → 개정이유·주요내용·**목적론적_키포인트**·부칙_적용례 구조화 → amendments.jsonl. Gemini 키 사용(Anthropic 크레딧 무관) |

## 3. 도시정비법 특유 이슈

1. **2017.2.8. 전부개정(법률 제14567호, 시행 2018.2.9) — 조문 전면 재배열.**
   구법 기준 해석례가 코퍼스에 다수(10-0306 등). 이미 article_roles가 구법↔현행 상호참조를
   보유: 구 제4조↔제15조, 구 영 제12조↔영 제13조. **전부개정 amendments 레코드의 조문_변경
   필드에 코어 조문 이동표를 수동 보강**할 것(경미변경·주민절차·사업시행·관리처분 계열 위주).
   enrich가 생성한 레코드를 검수 후 이 표만 덧붙이면 됨.
2. 2002년 제정 이전은 연혁 없음 — 전신(도시재개발법·주촉법 아파트지구)은 18-0604가 다룬
   경과조치 영역으로, 해석례 코퍼스가 이미 커버.
3. 기존 PDF 스크립트 2본(`ingest_도시정비법.py`, `ingest_도시정비법시행령.py`)은 **대체됨** —
   구축 완료 후 deprecated 주석 또는 삭제 권장 (chroma 직접 add는 HNSW 증분 함정도 있음).
4. 별표는 파이프라인의 길이분할(2,000자) 방식 그대로 — 유형별 전용 청킹은 기존 보류 결정 유지.

## 4. 구축 후 검증 체크포인트

1. `fetch_exact`로 **영 제13조제4항** 원문 로딩 — 각 호 전체와 "어느 하나" 관문 문언 확인
2. **제101조제1항 단서** 원문 확인 (19-0103 eval 실패 지점)
3. **재-eval로 효과 정량 증명**: `10-0306`(corr 0.0) · `19-0103`(corr 0.0) · `22-0869`(cov 0.5)
   다시 돌려 상승 확인 — 조문 창작이 사라지는지가 핵심
4. amendments: 2017 전부개정 레코드 존재 + 취지·조문_변경 필드 검수
5. 팝업: 답변에서 도시정비법 조문 인용 시 원문 팝업 작동
6. 내장법령목록(/law-list)에 3종 표시 확인

## 5. 배포 재인덱싱 — 주의 필요

- 본문·별표가 바뀌므로 **FORCE_REINDEX=1** 필요 (REINDEX_AUX는 개정이력만 반영).
- FORCE_REINDEX는 chroma 볼륨 전체 삭제 후 재빌드(13분+, 헬스체크 유의) —
  **함께 지워지는 것**: 업로드 캐시, 조례 스캔분(남양주 등 — 서울 팩은 부팅 시 자동 복구),
  대화 팝업 요소 저장분, 인용 검증 캐시(_cite_verify — 후보 큐 포함, 재배포 전 백업 권장).
- 순서: (지금 돌리는) REINDEX_QA 완료·변수 삭제 → 구축 커밋/push → FORCE_REINDEX=1 →
  완료 확인 → 변수 삭제. FORCE가 qa_precedents도 재빌드하므로 이후 별도 REINDEX_QA 불필요.
- 조례 라이브러리의 스캔 조례(남양주 9건 등)는 재스캔으로 복구 — 사용자 안내 필요.

## 6. 예상 규모·시간

- API 호출: 본문 3회 + 연혁 목록 ~9페이지 + 판별 상세 113회 (0.3초 간격)
- Gemini enrich 113건 — 대략 15~30분, 체크포인트로 분할·재개 가능
- amendments.jsonl 525 → **약 638건**, all_articles.jsonl 2,480 → **약 2,798건**(법 185 + 영 133 교체·추가)
