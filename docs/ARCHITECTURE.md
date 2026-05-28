# 건축법규 RAG 시스템 — 구조 및 개선 로드맵

---

## 1. 데이터 구축 파이프라인

```
📄 서울시 건축법·건축조례 질의회신집.pdf
    │
    ▼ 00_PDF_QA_Extractor.py
extracted_qa.jsonl
    │
    ▼ split_multi_question.py  (복수 질문 분리)
clean_single.jsonl
    │
    ▼ label_relation_type.py  (관계유형 라벨링 — 7종)
labeled.jsonl
    │  + relation_type / logic_steps
    ▼ enrich_labeled.py  (doc_ref 매칭)
labeled_with_doc.jsonl
    │  + doc_ref / doc_agency / doc_date
    ▼ 02_Indexer_BASE.py
    │
    └──▶ ChromaDB: qa_precedents  (~1,888 벡터)

🌐 법제처 Open API (law.go.kr DRF, LAW_API_KEY)
    │
    ▼ law_api_fetcher.py  (캐시 TTL 30일)
data/law_cache/{법령명}.json
    │
    ▼ 02_Indexer_BASE.py
    │
    └──▶ ChromaDB: law_articles  (법령 조문 전문)

⚠ ChromaDB: court_cases  → 미구축 (판례 파이프라인 부재)
```

**라우팅 보조 데이터**
- `keyword_law_map.json` — 키워드 → 법령명 매핑
- `article_graph.json` — 조문 간 참조 그래프 (1-hop 확장용)

---

## 2. 쿼리 파이프라인

```
👤 사용자 질문
    │
    ▼ Pass 1 · Claude
    ├─ 핵심 쟁점 식별
    ├─ 질문 유형 분류  (단일조문형 / 복수조문탐색형 / 조건분기형)
    ├─ 관계유형 분류  (DEF_EXP / SCOPE_CL / REQ_INT / EXCEPT /
    │                  INTER_ART / PROC_DISC / SANC_SC)
    └─ 법령 힌트 추출  (예: "건축법 제19조")
    │
    ▼ 05_Retriever.py
    ├─ Layer 1: TOPIC_LAW_MAP  → 주제별 기본 법령셋
    ├─ Layer 2: keyword_law_map → 키워드 추가 법령
    ├─ Layer 3: article_graph  → 1-hop 조문 확장
    └─ HybridSearcher
       ├─ law_articles:   Vector + BM25 → RRF 병합
       ├─ qa_precedents:  Vector (유사도 ≥ 0.60)
       └─ court_cases:    ✗ 미구축
    │
    ▼ Pass 2 · Claude  (2트랙 해석 + 선례 포지셔닝)
    │  (상세 내용은 §3 참조)
    │
    ▼ app.py · Streamlit
    ├─ 탭 1: 관련 법령 조문  (law_docs)
    ├─ 탭 2: 유사 질의회신 선례  (qa_docs + doc_ref)
    ├─ 탭 3: Pass 1 분석 원문
    └─ 비교 분석 모드  (이력 2건 선택 → Claude 차이 분석)
```

---

## 3. Pass 2 판단 구조 — 2트랙 해석 + 선례 포지셔닝

### 현재 구조 (데이터 제약 반영)

```
① 문언적 해석
   └─ 조문 문언 그대로의 의미·범위
      열거 항목의 한정 vs 예시 여부
      체계적 맥락 (유사 조문과의 정합성)
      → 문언적 결론

② 목적·취지 해석  ← 입법취지 + 목적론 통합
   └─ 해당 조문이 어떤 문제를 해결하기 위해 만들어졌는가
      입법연혁상 범위 확장·축소가 있었다면 그 의도
      법 전체 목적 달성 여부, 실질적 효과
      동질적 권리·의무의 달리 취급 합리성
      → 목적·취지 결론

③ 선례 포지셔닝  (qa_docs / case_docs 있을 때만)
   └─ 검색된 선례가 ①②중 어느 해석을 지지하는지 태깅
      📌 [doc_ref] → 문언적 / 목적·취지 해석 지지
      요지 + 사실관계 차이점

결론 판정
   ├─ 수렴  → [확신도: 확정]
   ├─ 부분수렴 → [확신도: 조건부]
   └─ 분기  → [확신도: 해석분기] + [해석 분기점]
```

### 왜 입법취지를 목적론에 통합했나

입법취지 해석은 개정이유서·국회 심의록 등 **역사적 문서를 근거로 "입법자가 의도한 것이 무엇인가"** 를 확인하는 작업이다.
해당 문서가 인덱스에 없는 현재 상태에서는, Claude가 입법취지를 추론하는 과정이 목적론적 추론과 실질적으로 동일하다.
두 트랙을 분리하면 같은 논거를 두 번 쓰는 중복이 발생하므로, 데이터가 갖춰질 때까지 통합 운용한다.

---

## 4. 현재 시스템의 한계 (약점)

| # | 약점 | 영향 | 해결 방향 |
|---|------|------|-----------|
| 1 | qa_precedents 범위가 서울시 건축법만 포함 | 주택법·민법 교차 쟁점에서 ③ 선례 포지셔닝 미작동 | 법제처 해석례 추가 (target=expc API) |
| 2 | court_cases 미구축 | 판례 인용 불가 | 판례 크롤링·인덱싱 파이프라인 구축 |
| 3 | 개정이유서·국회 심의록 없음 | ② 입법취지가 Claude 추론에만 의존 | 개정이유서 데이터 투입 후 트랙 분리 |

---

## 5. 로드맵 — 입법취지 트랙 분리 조건

아래 데이터가 인덱스에 추가되면 `② 목적·취지 해석`을 다시 분리한다.

```
필요 데이터:
  - 주요 법령 개정이유서  (법제처 법령정보센터)
  - 국회 심의·의결 자료  (국회 의안정보시스템)
  - 법제처 법령해석 통합 DB  (target=expc)

분리 후 구조:
  ② 입법취지 해석  ← 역사적 사실 질문
     "개정이유서에 따르면 X를 위해 신설되었으며..."
     근거: 실제 문서 인용
  ③ 목적론적 해석  ← 규범적 판단 질문
     "현재 법 목적상 이 해석이 Y를 달성하는가"
     근거: 법 체계·실질적 효과 분석
```

---

## 6. 파일 구조 요약

```
d:/## Workspace(model4, 0318)/
├── app.py                      Streamlit UI
├── 06_Generator.py             2-pass Claude 생성 (Pass1 + Pass2)
├── 05_Retriever.py             3-Layer 하이브리드 검색
├── 02_Indexer_BASE.py          ChromaDB 인덱스 빌드
├── law_api_fetcher.py          법제처 Open API 캐시
├── 00_PDF_QA_Extractor.py      PDF 추출
├── split_multi_question.py     복수 질문 분리
├── label_relation_type.py      관계유형 라벨링
├── enrich_labeled.py           doc_ref 매칭
├── data/
│   ├── labeled_with_doc.jsonl  최종 QA 학습 데이터
│   ├── chroma_db/              벡터 인덱스
│   │   ├── law_articles/
│   │   ├── qa_precedents/
│   │   └── court_cases/        (미구축)
│   ├── law_cache/              법령 조문 캐시
│   ├── keyword_law_map.json
│   └── article_graph.json
└── ARCHITECTURE.md             ← 이 파일
```
