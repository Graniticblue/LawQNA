# 건축법규 검토 RAG 시스템 — 전체 구조 다이어그램

```mermaid
flowchart TB
    %% ─── 데이터 파이프라인 (오프라인) ───────────────────────────────
    subgraph PIPELINE["🔧 데이터 파이프라인 (오프라인)"]
        direction LR

        subgraph SRC["데이터 소스"]
            L1["법제처 OpenAPI\n법령 XML\n(17개 법령, ~3,000조)"]
            L2["별표 PDF\n(시행령 별표 등)"]
            L3["질의회신 JSONL\n(1,029건)"]
            L4["판례 PDF\n(대법원 등)"]
        end

        subgraph PROC["전처리"]
            P1["02_Indexer\n조문 청킹"]
            P2["02_Byeolpyo_Chunker\n별표 섹션 분리"]
            P3["21_QAChunker\nchunk_search / chunk_answer 분리"]
            P4["11_CaseExtractor → 12_CaseParser\nPDF 추출 + 구조 파싱"]
            P5["13_CaseLabeler\nLLM 7유형 관계 라벨링\n(Claude API)"]
            P6["14_CaseChunker\n판결요지/쟁점별 청킹"]
        end

        subgraph STORE["저장소 (ChromaDB)"]
            DB1[("law_articles\n법령 조문\n~3,000 docs")]
            DB2[("qa_precedents\n질의회신\n1,029건")]
            DB3[("court_cases\n판례\n300~2,000 청크\n★ 신규")]
        end

        subgraph GRAPH["부가 색인"]
            G1["keyword_law_map\n500+ 키워드"]
            G2["article_graph\n700 노드 / 2,000 엣지\n+ 판례 노드 ★"]
        end

        L1 --> P1 --> DB1
        L2 --> P2 --> DB1
        L3 --> P3 --> DB2
        L4 --> P4 --> P5 --> P6 --> DB3
        P3 --> G1
        P6 --> G2
    end

    %% ─── 런타임 파이프라인 (온라인) ─────────────────────────────────
    subgraph RUNTIME["⚡ 런타임 파이프라인 (온라인)"]
        direction TB

        Q["👤 사용자 질문"]

        subgraph PASS1["1차 LLM 호출 — 쟁점 식별 + 라우팅"]
            R1["출력 ①\n법령 힌트\n(법명, 조문번호)"]
            R2["출력 ②\n관계 유형 분류\n(복수 중첩, weight 0~1)"]
        end

        subgraph TYPES["7가지 관계 유형"]
            T1["🔵 DEF_EXP\n정의확장형"]
            T2["🟢 SCOPE_CL\n적용범위 확정형"]
            T3["🟡 REQ_INT\n요건해석형"]
            T4["🔴 EXCEPT\n예외인정형"]
            T5["🟣 INTER_ART\n조문간관계 해석형"]
            T6["⚪ PROC_DISC\n절차·재량 확인형"]
            T7["🟤 SANC_SC\n벌칙·제재 범위형"]
        end

        subgraph RETRIEVE["3층 하이브리드 검색 (Vector + BM25 → RRF)"]
            SR1["Layer 1 — law_articles\n① 토픽 기반\n② keyword_law_map\n③ 조문 그래프\n→ 법규 필터 조문 검색"]
            SR2["Layer 2 — qa_precedents\n유사 질의회신 검색\n(chunk_answer 전체 제공)"]
            SR3["Layer 3 — court_cases ★\n(법규 × 유형) 쌍 필터\n유형별 병렬 검색 → RRF 병합\nFallback: 유형완화 → 법규만 → 전체"]
        end

        subgraph CTX["컨텍스트 구성"]
            C1["=== [관련 법령 조문] ==="]
            C2["=== [유사 질의회신 선례] ==="]
            C3["=== [참조 판례 풀] ★ ===\n(법규 × 유형) 매칭 판례"]
        end

        subgraph PASS2["2차 LLM 호출 — 법리 답변 생성"]
            ANS["[쟁점 식별]\n[관련 조문 확인]\n[정의 원용 ③ / 법리 판단 ②]\n[직접 적용 판례 ①]\n[최종 답변]\n[근거 법령 + 인용 판례]"]
        end

        subgraph CONF["확신도 판정"]
            V1["✅ 확정\n법+판례로 결론 명확"]
            V2["⚠️ 조건부\n사실관계에 따라 상이"]
            V3["🏛️ 재량위임\n허가권자 재량 사항"]
            V4["❓ 범위외\n관할부서 안내"]
        end

        OUT["📋 최종 답변\n+ 담당부서 확인 질문 (해당 시)"]

        Q --> PASS1
        R2 -.-> T1 & T2 & T3 & T4 & T5 & T6 & T7
        R1 --> SR1 & SR2
        R1 & R2 --> SR3
        SR1 --> C1
        SR2 --> C2
        SR3 --> C3
        C1 & C2 & C3 --> PASS2
        ANS --> CONF
        CONF --> OUT
    end

    PIPELINE -.->|"임베딩\n(ko-sroberta 384d)"| RUNTIME

    %% ─── 판례 활용 3모드 ─────────────────────────────────────────
    subgraph MODES["📚 판례 활용 3모드"]
        M1["① 직접 적용\nfact_summary 유사 → 선례 인용"]
        M2["② 논리 차용\nlogic_summary 유사 → 판단 틀 차용"]
        M3["③ 정의 원용\n확장된 정의를 전제로 사용\n⚠️ apply_condition 검증 필수"]
    end

    C3 -.-> MODES
    MODES -.-> ANS

    %% ─── 스타일 ──────────────────────────────────────────────────
    classDef db fill:#dbeafe,stroke:#3b82f6,color:#1e3a8a
    classDef llm fill:#fef3c7,stroke:#f59e0b,color:#78350f
    classDef new fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef mode fill:#f3e8ff,stroke:#9333ea,color:#581c87
    classDef conf fill:#fff7ed,stroke:#ea580c,color:#7c2d12

    class DB1,DB2 db
    class DB3 new
    class PASS1,PASS2 llm
    class SR3,C3,P5,P6 new
    class M1,M2,M3 mode
    class V1,V2,V3,V4 conf
    class G2 new
```

---

## 핵심 설계 원칙

| 원칙 | 내용 |
|------|------|
| **(법규 × 유형) 쌍** | 판례 검색의 핵심 키 — 같은 법규를 같은 방식으로 해석한 판례를 찾는다 |
| **복수 유형 중첩** | 하나의 질문이 N개 유형에 중첩 가능 → weight ≥ 0.5만 필터, 나머지는 부스트 |
| **Fallback 3단계** | 유형 필터 완화 → 법규만 → 전체 검색 (초기 판례 데이터 부족 대비) |
| **확신도 4단계** | 확정 / 조건부 / 재량위임 / 범위외 — 모호한 경우 구체적 확인 질문 생성 |
| **판례 활용 3모드** | ① 직접 적용 (fact) ② 논리 차용 (logic) ③ 정의 원용 (condition 검증 필수) |
