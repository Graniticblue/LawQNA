# 법제처 해석례 청킹 전략 계획서

> **적용 범위:** 이 전략은 `【질의요지】/【회답】/【이유】/【관계법령】` 마커가 있는
> **법제처 원문 형식 PDF**를 새로 추가할 때에만 적용한다.
> 기존 `labeled_with_doc.jsonl` / `seoul_reasoning_v9_final.jsonl`은
> 이미 CoT 스타일로 가공된 데이터이므로 현재 방식으로 충분하다.

---

## 0. 시스템 분류 프레임워크 (청킹에 반영할 레이블)

청크 메타데이터에 아래 3개 프레임워크의 레이블을 포함한다.

### 0.1 relation_type — 7종 (해석례 전체 단위)

| 코드 | 한글명 | 해석례 패턴 |
|------|--------|------------|
| `DEF_EXP` | 정의확장형 | "~에 ~도 포함되는가?" |
| `SCOPE_CL` | 적용범위확정형 | "~에도 ~이 적용되는가?" |
| `REQ_INT` | 요건해석형 | "~의 요건을 충족하는가?" |
| `EXCEPT` | 예외인정형 | "~임에도 예외가 인정되는가?" |
| `INTER_ART` | 조문간관계해석형 | "어느 조문이 우선하는가?" |
| `PROC_DISC` | 절차·재량확인형 | "재량 범위 또는 절차는?" |
| `SANC_SC` | 벌칙·제재범위형 | "위반 시 제재는?" |

→ **모든 청크**에 해당 해석례의 `relation_type` / `relation_name` 공통 부여

### 0.2 logic_steps role — 4종 (이유 단락 단위)

| 코드 | 의미 | 이유 텍스트 패턴 |
|------|------|-----------------|
| `ANCHOR` | 기준 법령 조문 확인 | "제○조제○항에서는 ... 규정하고 있고" |
| `ANALYSIS` | 입법연혁·취지 분석 | "입법연혁적으로 살펴보면", "도입된 이래" |
| `PREREQUISITE` | 적용 전제 조건 확정 | "해당하기 위해서는", "전제 조건" |
| `RESOLUTION` | 결론 도출 | "이상과 같은 점을 종합해 볼 때" |

→ **B 청크(REASONING_STEP)**에만 `step_role` / `step_seq` 부여

### 0.3 question_type — 3종 (Pass 1 런타임 분류, 청킹에는 참고만)

| 코드 | 설명 |
|------|------|
| `단일조문형` | 하나의 조문 해석 |
| `복수조문탐색형` | 여러 조문 간 관계 탐색 |
| `조건분기형` | 조건에 따라 적용 여부 달라짐 |

→ 청킹 시점에는 미리 알 수 없으므로 청크 메타데이터에 포함하지 않음.
  검색 시 `relation_type`으로 간접 추론.

---

## 1. 현황 및 문제점

### 1.1 현재 방식

`ingest_법제처.py` → `enrich_법제처.py` → `02_Indexer_BASE.py --collection 법제처`

현재 파이프라인은 해석례 1건을 **단일 Document**로 취급하고, LlamaIndex가 이를 토큰 단위로 자동 분할한다.

```
법제처_14-0840.jsonl (1 record)
  → LlamaIndex 자동 청킹
  → 18개 벡터 (텍스트 길이 기준 분할)
```

**문제점:**
- 자동 분할은 법적 논리 구조를 무시하고 임의 위치에서 잘림
- 예: "이유" 중간에 청크 경계 → 논거가 끊긴 채 검색됨
- 질의요지와 회답이 같은 청크에 담기지 않을 수 있음
- 관계법령(원문) 텍스트가 검색에 노이즈로 작용

### 1.2 해석례의 논리적 구조

```
┌─────────────────────────────────────────────────────┐
│ 해석례 1건                                           │
│                                                     │
│  ① 질의요지  — "~인 경우 적용되는지?"                 │
│                                                     │
│  ② 회답      — "적용되지 않습니다." (1~3문장)          │
│                                                     │
│  ③ 이유      — 다단계 논거                            │
│    [ANCHOR]     기준 법령 조문 확인                    │
│    [ANALYSIS]   입법연혁·취지 분석                     │
│    [PREREQUISITE] 적용 전제 조건 확정                  │
│    [RESOLUTION] 결론 도출                             │
│                                                     │
│  ④ 관계 법령 — 원문 조문 텍스트                        │
└─────────────────────────────────────────────────────┘
```

---

## 2. 제안 청킹 전략

해석례 1건 → **4종 청크** 생성 (+ 선택적 5번째)

### 청크 A: 질의+회답 (핵심 Q&A)

**목적:** 유사 질문 벡터 검색 최적화

```
[질의요지]
{question}

[회답]
{answer_head}

[출처] {doc_ref}
[검색태그] {search_tags}
```

- `embed_text`: 질의 + 회답 요약 + 검색태그
- `chunk_type`: `"QA_CORE"`
- 검색 시 가장 먼저 매칭되어야 하는 청크

---

### 청크 B: 이유 — 논증 단계별 (logic_steps 기반)

**목적:** "왜 그렇게 해석하는가" 논거 검색

logic_steps의 각 단계(`ANCHOR` / `ANALYSIS` / `PREREQUISITE` / `RESOLUTION`)를
이유 텍스트의 단락과 매핑하여 개별 청크로 분리.

```
[{role}: {title}]  ← ANCHOR: 건축법 제61조 규정 확인
{paragraph_text}

[출처] {doc_ref} | 단계 {seq}/{total}
[관련 쟁점] {label_summary}
```

- `chunk_type`: `"REASONING_STEP"`
- `step_role`: `"ANCHOR"` | `"ANALYSIS"` | `"PREREQUISITE"` | `"RESOLUTION"`
- `step_seq`: 1, 2, 3, 4

**단락 매핑 방법:**
- 이유 텍스트를 단락(`\n \n` 또는 `\n\n`) 기준으로 분리
- Claude에게 각 단락을 logic_steps 중 하나에 할당하도록 요청
- 또는: `RESOLUTION` = 마지막 단락("이상과 같은 점을 종합해 볼 때"), 나머지는 순서대로 배분

---

### 청크 C: 결론 요약 (label_summary 기반)

**목적:** "이 해석례의 결론이 무엇인가" 직접 검색

```
[해석 결론] {relation_name}
{label_summary}

[출처] {doc_ref}
[유형] {relation_type}
[검색태그] {search_tags}
```

- `chunk_type`: `"CONCLUSION"`
- 답변 생성 시 "선례 포지셔닝" 표시용으로 사용
- 짧고 검색 정확도 높음

---

### 청크 D: 관계 법령 연결 (선택적)

**목적:** "이 해석례가 어느 조문과 연결되는가" 매핑

```
[참조 조문]
{law_refs_text}

[이 조문을 해석한 해석례]
{doc_ref}: {label_summary}
```

- `chunk_type`: `"LAW_LINK"`
- 조문 조번호(`article_no`) 추출 후 `law_articles` 컬렉션과 cross-reference 가능
- 구현 난이도가 높으므로 2단계 과제로 분류

---

## 3. 메타데이터 스키마 (청크 공통)

| 필드 | 설명 | 예시 |
|------|------|------|
| `chunk_type` | 청크 종류 | `"QA_CORE"`, `"REASONING_STEP"`, `"CONCLUSION"`, `"LAW_LINK"` |
| `doc_ref` | 해석례 식별자 | `"[법제처 2015. 1. 26. 회신 14-0840]"` |
| `doc_code` | 코드 | `"14-0840"` |
| `doc_date` | 날짜 | `"2015-01-26"` |
| `doc_agency` | 기관 | `"법제처"` |
| `relation_type` | 해석 유형 | `"SCOPE_CL"` |
| `relation_name` | 유형 한글 | `"적용범위확정형"` |
| `search_tags` | 검색태그 | `"#일조권 #건축물높이제한..."` |
| `step_role` | (B 청크 전용) 단계 역할 | `"ANALYSIS"` |
| `step_seq` | (B 청크 전용) 단계 순서 | `2` |
| `source_file` | 원본 파일명 | `"법제처_14-0840.jsonl"` |

---

## 4. 구현 계획

### 4.1 스크립트 분리 구조

```
ingest_법제처.py    ← 기존: PDF → 단일 JSONL (updates/)
enrich_법제처.py    ← 기존: Claude → relation_type, logic_steps, search_tags
chunk_법제처.py     ← 구현 완료: JSONL → A/B/C 청크 → ChromaDB 직접 인덱싱
```

**전체 워크플로:**
```bash
# 1. add/ 폴더에 PDF 추가 후:
python ingest_법제처.py          # PDF → updates/*.jsonl
python enrich_법제처.py --run-index  # Claude 보강 → chunk_법제처.py 자동 호출
# 또는 수동:
python chunk_법제처.py           # updates/ 신규 파일만 청킹+인덱싱
python chunk_법제처.py --reset   # 전체 재빌드
python chunk_법제처.py --dry-run # 청크 미리보기
```

### 4.2 `chunk_법제처.py` 처리 흐름

```
입력: data/qa_precedents/updates/법제처_{code}.jsonl
         (enrich 완료된 레코드)

Step 1: 필드 파싱
  - question  = contents[0].parts[0].text
  - answer    = contents[1].parts[0].text
  - 이유 추출 = answer에서 【이유】 섹션
  - 회답 추출 = answer에서 【회답】 섹션
  - 관계법령  = answer에서 【관계 법령】 섹션

Step 2: 이유 단락 분리
  - 【이유】 텍스트를 "\n \n" 기준으로 단락 분리
  - 단락 수 ≥ len(logic_steps) 이면: Claude로 매핑
  - 단락 수 < len(logic_steps) 이면: 단락을 logic_steps에 순서 배분

Step 3: 4종 청크 생성
  - 청크 A: QA_CORE
  - 청크 B-1 ~ B-N: REASONING_STEP (logic_steps 수만큼)
  - 청크 C: CONCLUSION

Step 4: 청크 JSONL 저장
  출력: data/qa_precedents/chunks/법제처_{code}_chunks.jsonl
        (1개 해석례 → 5~8개 청크 레코드)
```

### 4.3 청크 JSONL 레코드 형식

```json
{
  "chunk_type": "QA_CORE",
  "embed_text": "...",
  "doc_ref": "[법제처 2015. 1. 26. 회신 14-0840]",
  "doc_code": "14-0840",
  "doc_date": "2015-01-26",
  "doc_agency": "법제처",
  "relation_type": "SCOPE_CL",
  "relation_name": "적용범위확정형",
  "label_summary": "...",
  "search_tags": "#일조권 ...",
  "step_role": null,
  "step_seq": null,
  "full_answer": "...",
  "source_file": "법제처_14-0840.jsonl"
}
```

### 4.4 `02_Indexer_BASE.py` 변경

`--collection 법제처` 실행 시:
- 현재: `updates/*.jsonl` → `load_qa_documents()` → LlamaIndex 자동 청킹
- 변경 후: `chunks/*.jsonl` → 청크 단위로 직접 Document 생성 (자동 청킹 OFF)

```python
# 자동 청킹 비활성화
from llama_index.core.node_parser import SimpleNodeParser
node_parser = SimpleNodeParser.from_defaults(chunk_size=99999)  # 청크 경계 없음
```

---

## 5. 단락↔logic_steps 매핑 방법론

### 5.1 휴리스틱 (빠른 구현)

```
이유 텍스트 단락 = ["공통사항...", "입법연혁...", "즉, 이 규정은...", "이상과 같은 점을..."]
logic_steps     = [ANCHOR, ANALYSIS, PREREQUISITE, RESOLUTION]

규칙:
  - "이상과 같은 점을 종합해 볼 때" 포함 → RESOLUTION
  - "입법연혁" / "도입된 이래" 포함 → ANALYSIS
  - "조(제X항)" 인용 후 조문 설명 → ANCHOR
  - 나머지 → PREREQUISITE
```

### 5.2 Claude 매핑 (정확)

```
프롬프트:
  아래 이유 단락들을 분석하여 각 단락을
  ANCHOR / ANALYSIS / PREREQUISITE / RESOLUTION 중 하나로 분류하세요.
  [단락 목록]
  ...
  출력: JSON 배열 [{"para_idx": 0, "role": "ANCHOR"}, ...]
```

**권장:** 2단계 구현
- 1단계: 휴리스틱으로 빠르게 구현 (현재 과제)
- 2단계: 품질이 중요한 해석례에 Claude 매핑 적용

---

## 6. 우선순위

| 단계 | 작업 | 비고 |
|------|------|------|
| ★ 즉시 | `chunk_법제처.py` 작성 (A/B/C 청크) | 휴리스틱 단락 매핑 |
| ★ 즉시 | `02_Indexer_BASE.py` 청크 파일 로드로 변경 | 자동 청킹 OFF |
| 2단계 | Claude 단락 매핑 (`--claude-map` 옵션) | 품질 향상 |
| 3단계 | 청크 D (관계법령↔조문 cross-reference) | law_articles 연동 |
| 3단계 | 검색 결과에서 `chunk_type`별 우선순위 가중치 | Retriever 수정 |

---

## 7. 검색 활용 전략 (Retriever 변경 사항)

청킹 완료 후 `05_Retriever.py`의 `search_qa()`를:

- **질의 유사도 검색**: `QA_CORE` 청크에 높은 가중치
- **논거 상세 검색**: `REASONING_STEP` 청크 (ANALYSIS, ANCHOR)
- **선례 포지셔닝**: `CONCLUSION` 청크 (결론 요약만 빠르게 읽기)
- **출력 조립**: `doc_ref`가 같은 청크들을 묶어 하나의 선례로 표시

```
검색 결과 예시:
  [선례1] [법제처 2015. 1. 26. 회신 14-0840]  ← QA_CORE 매칭
    결론: 도로 사이에 마주보는 경우 단서 적용 안 됨  ← CONCLUSION
    논거: 입법연혁상 도로변 연속성이 목적...  ← REASONING_STEP (ANALYSIS)
```
