# LawQNA 함수 인벤토리 — MCP화 검토 자료

작성 2026-07-15 · 기준 코드: master 25b3b14

MCP 관점의 분류 기준:
- **도구(Tool)** — 외부 에이전트(Claude Desktop 등)가 호출할 가치가 있는 함수. 입출력 경계가 명확하고 부작용이 통제됨
- **자원(Resource)** — 호출이 아니라 읽기로 제공할 문서·대장
- **보류** — 함수로는 좋지만 MCP로 열면 안 되는 것 (큐레이션 필요, 파괴적, 내부 전용)

운영 대원칙 (기확정): 답변·리서치는 **학습 코퍼스만** 사용하고, 실시간 외부 API는
**인용 실존 검증(허위사실 판명)** 과 **사각지대·미보유 조례 패치**에만 허용한다.

---

## 1. 코퍼스 인출 계열 — MCP 도구 1순위

전부 결정론(모델 호출 없음)이고 chroma 로컬 조회라 부작용이 없다.

| 현재 함수 (위치) | 하는 일 | MCP 도구명(안) |
|---|---|---|
| `fetch_exact_articles(hints)` — 05_Retriever | "주택법 제15조" 형식 힌트 → 조문 원문. 항 청크를 전체 조문으로 재구성(`_expand_hang_chunks`) | `get_article` |
| `retrieve(query, law_hints, as_of_date…)` — 05_Retriever | 벡터+BM25 하이브리드 통합 검색 → (법령, 해석례, 판례) 3층 | `search_corpus` |
| `fetch_qa_by_codes(codes)` — 05_Retriever | 해석례 안건번호 직접 조회 (검색 점수 우회 강제 포함) | `get_interpretation` |
| `fetch_cases_by_ids(ids)` — 05_Retriever | 판례 사건번호 직접 조회 (court_cases) | `get_precedent` |
| law_amendments 검색 — 05_Retriever / index_amendments | 개정이력: 시행일·개정이유·주요내용·목적론적 키포인트·부칙 적용례 | `get_amendment_history` |
| `_phrase_principle_codes(text, docs)` — 05_Retriever (신규) | 법정 문형 감지('각 호의 어느 하나'·단서·'등'·유추) → 원칙 해석례 코드. 매핑: data/phrase_principles.json | `detect_phrase_principles` |
| `search_region / fetch_exact_region / match_regions` — 05_Retriever | 지역 조례 검색 (지자체 실명 사전 ~170개, 자치구→시 매핑) | `search_ordinances_local` |
| `get_ordinance_article_text` — 05_Retriever | 조례 조문 원문 (레지스트리·팩·업로드 캐시 경유) | `get_ordinance_article` |
| `ordinance_registry` upsert/get — 05_Retriever | 조례 리딩 레지스트리 (지역별 법령체계 총괄 뷰) | `get_region_registry` (읽기만) |
| `search_uploaded` — 05_Retriever | 업로드·패치 자료 검색 (지역 교차오염 차단 내장) | 통합검색에 흡수 |
| `_doc_is_after_cutoff(meta, as_of)` — 05_Retriever | 시점 컷오프 (eval·역사적 질의 공정성) | 각 도구의 `as_of` 파라미터로 흡수 |

## 2. 외부 API 계열 — 정문(正門)만 노출

| 현재 함수 (위치) | 하는 일 | MCP 판단 |
|---|---|---|
| `cite_verify.check_answer / extract_citations` — ingest/cite_verify | 답변 속 판례·해석례 번호의 실존 검증. 3단 필터(대장→캐시→API), 미확인≠허위 시맨틱, 실존·미학습은 후보 큐 적재 | **도구 `verify_citation`** — 실시간 API의 유일한 정식 관문 |
| `scripts/ingest_prec.py --verify` | 위와 동일 시맨틱의 CLI판 | verify_citation에 통합 |
| `fetch_ordinance / search_ordinances` — ingest/law_api_fetcher | 자치법규 전문 패치 (별표단위 포함, 명칭 공백 정규화) | ⚠ 도구화 가능하되 "미보유 지역 캐싱" 용도 명시 (등록 부작용 있음) |
| `fetch_article / fetch_delegations` — ingest/law_api_fetcher | 국가법령 조문 패치·위임법령 추적 | ⚠ 사각지대 패치 전용 |
| `fetch_law_bundle / fetch_history / fetch_revision_docs` — ingest/ingest_law_from_api | 법령 전체 수집·연혁·제개정이유 (+Gemini enrich) | ❌ 학습 파이프라인 내부 전용 |

## 3. 학습 사이클 계열 — MCP 제외 권장

큐레이션(사람+에이전트 세션의 판단)이 본질인 작업들. 자동 호출로 열면
중복 학습·덮어쓰기(21-0674 사고 유형)가 모델 판단으로 재발할 수 있다.

| 스크립트 | 하는 일 |
|---|---|
| `scripts/ingest_prec.py --scaffold` | 판례 학습 스캐폴드 (기보유 가드 + [n] 정렬 파싱) |
| `scripts/make_ingest_report.py` | 검수 보고서 생성 (문단·gist 대조, roles 내역, eval) |
| `scripts/scan_citation_candidates.py` | 코퍼스 내부 인용 스캔 → 체크리스트 후보 감지 |
| `scripts/eval_pipeline.py` | 컷오프+LOO 평가 (corr/cov/거짓인용/갭 유형) |
| `ingest/ingest_law_from_api.py` | 법령 3종 세트 구축 (본문·별표·이력·취지) |
| `ingest/ingest_court_cases.py` | 판례 인덱싱 (전량 재빌드) |
| `pipeline/02_Indexer_BASE.py` | 컬렉션 재빌드 (laws/qa/법제처/all) |

## 4. 자원(Resource)으로 노출할 것

| 파일/데이터 | 내용 |
|---|---|
| `data/ingest_reports/학습후보_체크리스트.md` | 후보 대장 (등록일·출처·학습일) |
| `data/ingest_reports/*_학습보고.md` | 검수 보고서들 |
| 내장법령목록 (`/law-list`, 동적 집계) | 계열별 법령·시행일·이력 현황 |
| chroma 볼륨 `_cite_verify/queue.json` | 검증 훅의 학습 후보 큐 (전역, UI 비노출) |
| `data/article_roles/*.json` | 조문 프레임 (요건·역할·해석원칙) |
| `data/phrase_principles.json` | 문형→원칙 매핑 테이블 |

## 5. "쪼개면 함수가 되는" 매몰 요소 — MCP 전 리팩토링 후보

| # | 매몰 위치 | 분리 후 함수(안) | 비고 |
|---|---|---|---|
| 5-1 | 조례 스캔 퍼널 (`on_region_ordinance_scan`, chainlit 핸들러) | `scan_region_ordinances(region, topic?)` | 제목검색→필터→랭킹→전량 리딩→등록. UI와 분리하면 도구 겸 재사용 함수 |
| 5-2 | 사각지대 감지 (blind_spots, 06_Generator 내부) | `detect_blind_spots(answer_or_hints)` | "DB 미수록 법령" 판정 |
| 5-3 | 조례→모법 역링크 (`_ordinance_parent_hints`) | `resolve_ordinance_parents(text)` | 제1조 약칭 정의 파싱 |
| 5-4 | 인용 소독기 + cite_label 부여 | `sanitize_citations(text, allowed)` | 이미 거의 순수 함수 |
| 5-5 | pass1 분류 (모델 호출) | `classify_query(question)` | 도구화는 애매하나 산출 스키마(law_hints·query_regions·answer_mode)는 도구 명세로 재사용 |
| 5-6 | **(신규) 구법→현행 조문 리라우팅** | `resolve_article_era(law, article, date)` | 아직 없음. 10-0306 재-eval에서 구법 번호(제4조·영 제12조)가 현행의 동번호 이질 조문을 물어오는 문제 실증 — 2017 전부개정 이동표(amendments)를 기반으로 구현. **신규 함수화 1순위** |

## 6. 권고 — 최소 MCP 서버 구성 (1단계 5종)

```
lawqna-mcp
├── get_article(law, article, as_of?)        # 조문 원문 (코퍼스)
├── search_corpus(query, as_of?, top_k?)     # 통합 하이브리드 검색
├── get_interpretation(code)                 # 해석례 전문 (doc_code)
├── detect_phrase_principles(text)           # 문형 → 원칙 해석례
└── verify_citation(number)                  # 실존 검증 (유일한 외부 API)
```

- 이 5종이면 이번 주기(남양주 분쟁 리서치~학습)에서 수동으로 수행한 작업의
  약 8할이 외부 에이전트로 재현 가능
- chainlit 2-pass 파이프라인은 무수정 — MCP 서버는 기존 함수의 얇은 어댑터
  (이중 모드: 웹 챗 + 에이전트 도구)
- 2단계 후보: get_precedent, get_amendment_history, get_ordinance_article,
  get_region_registry + 5-1·5-6 리팩토링 완료분
- 학습 사이클(§3)은 끝까지 MCP 밖 — 대화 세션 전용으로 유지

## 7. 참고 — 원칙과 함정 (이번 주기의 교훈)

1. **코퍼스 우선, API는 검증·패치의 정문으로만** — 답변 인용은 학습분 한정
2. **기보유 가드 필수** — 대장(court_cases + qa_precedents + 체크리스트) 대조 없는
   등재·학습 금지 (21-0674 덮어쓰기, 23-0982 중복 등재의 재발 방지)
3. **컷오프 준수** — 시점 있는 조회(as_of)는 미래 자료 배제 (eval 공정성과 동일 원칙)
4. **문형 원칙은 검색이 아니라 감지로** — 도메인 어휘와 직교하는 지식은
   결정론 훅/도구로 소환
5. **HNSW 증분 함정** — 컬렉션 갱신은 전량 재빌드 원칙 (소규모 컬렉션은
   ensure_* 부팅 보증 패턴)
