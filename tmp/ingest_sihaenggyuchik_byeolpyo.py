import sys, json, time
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

# ── 경로 설정
BASE_DIR   = Path(__file__).parent.parent
CHROMA_DIR = BASE_DIR / "data" / "chroma_db"
BYEOLPYO_DIR  = BASE_DIR / "data" / "raw_laws" / "byeolpyo"
BYEOLPYO_PATH = BYEOLPYO_DIR / "byeolpyo_chunks.jsonl"

# ── 별표 청크 정의
LAW_NAME = "국토의 계획 및 이용에 관한 법률 시행규칙"
LAW_ID_PREFIX = "LAND_SIRULE"
LAW_TYPE = "국토교통부령"
SOURCE_BASE = "https://www.law.go.kr/법령/국토의계획및이용에관한법률시행규칙"

new_chunks = [
    {
        "law_id":          f"{LAW_ID_PREFIX}_별표1",
        "law_name":        LAW_NAME,
        "law_type":        LAW_TYPE,
        "article_no":      "별표1",
        "article_title":   "기반시설별 조성비용으로 볼 수 있는 실제 투입 조성비용",
        "byeolpyo_no":     "1",
        "related_article": "제11조의2",
        "section_title":   "전체",
        "enforcement_date": "20200302",
        "source_url":      f"{SOURCE_BASE}/별표1",
        "chunk_seq":       1,
        "content": (
            "■ 국토의 계획 및 이용에 관한 법률 시행규칙 [별표 1] <개정 2020. 3. 2.>\n"
            "기반시설별 조성비용으로 볼 수 있는 실제 투입 조성비용(제11조의2 관련)\n\n"
            "1. 기반시설별 조성비용으로 인정할 수 있는 실제 투입 조성비용은 납부의무자가 해당 기반시설의 조성과 관련하여 지출한 다음 각 목의 비용을 합한 금액으로서 산출내역서와 증명 서류를 갖추어 제시한 금액으로 산정한다.\n"
            "가. 순공사비: 해당 기반시설의 조성을 위하여 지출한 재료비·노무비·경비·제세공과금의 합계액. 다만, 재료비·노무비·경비는 「국가를 당사자로 하는 계약에 관한 법률 시행령」 제9조 또는 「지방자치단체를 당사자로 하는 계약에 관한 법률 시행령」 제10조에 따른 예정가격의 결정기준 중 공사원가계산을 위한 재료비·노무비·경비의 산출방법을 적용하여 산출하되, 정부표준품셈과 단가(정부고시가격이 있는 경우에는 그 금액을 말한다)에 따른 금액을 초과하지 아니하는 금액이어야 한다.\n"
            "나. 조사비: 직접 해당 기반시설의 조성을 위한 측량비, 그 밖에 조사에 소요된 비용으로서 가목에 따른 순공사비에 해당되지 아니하는 비용. 다만, 「엔지니어링기술 진흥법」 제10조에 따른 엔지니어링사업대가의 기준에 따라 산정한 금액을 초과하지 아니하는 금액이어야 한다.\n"
            "다. 설계비: 해당 기반시설의 설계를 위하여 지출한 비용. 다만, 「엔지니어링기술 진흥법」 제10조에 따른 엔지니어링사업대가의 기준에 따라 산정한 금액을 초과하지 아니하는 금액이어야 한다.\n"
            "라. 일반관리비: 해당 기반시설의 조성과 관련하여 관리활동부문에서 발생한 제비용의 합계액으로서 「국가를 당사자로 하는 계약에 관한 법률 시행령」 제9조 또는 「지방자치단체를 당사자로 하는 계약에 관한 법률 시행령」 제10조에 따른 예정가격결정을 위한 기준과 요율을 적용하여 산정한 금액을 말한다.\n"
            "마. 그 밖의 경비: 토지가액에 포함되지 아니한 기반시설 구역의 건물·입목·영업권 등에 대한 보상비\n"
            "2. 납부의무자가 「건설산업기본법」에 따라 등록한 건설사업자와의 도급계약, 「엔지니어링기술 진흥법」에 따라 신고한 엔지니어링활동주체와의 엔지니어링사업계약 등 명백한 원인에 따라 지출한 비용을 근거로 산정하여 제시한 조성비용이 제1호에 따라 산정한 금액을 초과하는 경우에는 그 조성비용을 기반시설별 조성비용으로 인정할 수 있다.\n"
            "비고: 특별시장·광역시장·시장 또는 군수는 제1호에 따라 납부의무자가 제시한 금액의 사실 여부 확인 및 금액의 산출에 있어 해당 기반시설의 조성 내용과 성질 등이 특수하여 그 확인 또는 금액 산출이 곤란한 경우에는 「건설기술관리법」 제28조에 따라 등록된 감리전문회사 또는 「국가를 당사자로 하는 계약에 관한 법률 시행규칙」 제9조제2항에 따른 원가계산 용역기관에 그 확인 또는 금액 산출을 의뢰할 수 있다."
        ),
    },
    {
        "law_id":          f"{LAW_ID_PREFIX}_별표1의2",
        "law_name":        LAW_NAME,
        "law_type":        LAW_TYPE,
        "article_no":      "별표1의2",
        "article_title":   "생산관리지역에서 휴게음식점을 설치할 수 없는 지역",
        "byeolpyo_no":     "1의2",
        "related_article": "제11조의9",
        "section_title":   "전체",
        "enforcement_date": "20240529",
        "source_url":      f"{SOURCE_BASE}/별표1의2",
        "chunk_seq":       1,
        "content": (
            "■ 국토의 계획 및 이용에 관한 법률 시행규칙 [별표 1의2] <신설 2024. 5. 29.>\n"
            "생산관리지역에서 휴게음식점을 설치할 수 없는 지역(제11조의9 관련)\n\n"
            "다음 각 호의 어느 하나에 해당하는 지역. 다만, 「하수도법」에 따른 공공하수처리시설이 설치·운영되거나 다음 각 호의 지역 내 10호 이상의 자연마을이 형성된 지역은 제외한다.\n"
            "1. 저수를 광역상수원으로 이용하는 댐의 계획홍수위선(계획홍수위선이 없는 경우에는 상시만수위선을 말한다. 이하 같다)으로부터 1킬로미터 이내인 집수구역\n"
            "2. 저수를 광역상수원으로 이용하는 댐의 계획홍수위선으로부터 수계상 상류방향으로 유하거리가 20킬로미터 이내인 하천의 양안(兩岸: 양쪽 기슭) 중 해당 하천의 경계로부터 1킬로미터 이내인 집수구역\n"
            "3. 제2호의 하천으로 유입되는 지천(제1지류인 하천을 말하며, 계획홍수위선으로부터 20킬로미터 이내에서 유입되는 경우로 한정한다. 이하 이 호에서 같다)의 유입지점으로부터 수계상 상류방향으로 유하거리가 10킬로미터 이내인 지천의 양안 중 해당 지천의 경계로부터 500미터 이내인 집수구역\n"
            "4. 상수원보호구역으로부터 500미터 이내인 집수구역\n"
            "5. 상수원보호구역으로 유입되는 하천의 유입지점으로부터 수계상 상류방향으로 유하거리가 10킬로미터 이내인 하천의 양안 중 해당 하천의 경계로부터 500미터 이내인 집수구역\n"
            "6. 유효저수량이 30만세제곱미터 이상인 농업용저수지의 계획홍수위선의 경계로부터 200미터 이내인 집수구역\n"
            "7. 「하천법」에 따른 국가하천·지방하천(도시·군계획조례로 정하는 지방하천은 제외한다)의 양안 중 해당 하천의 경계로부터 직선거리가 100미터 이내인 집수구역(「하천법」제10조에 따른 연안구역을 제외한다)\n\n"
            "주\n"
            "1) \"집수구역\"이란 빗물이 상수원·하천·저수지 등으로 흘러드는 지역으로서 주변의 능선을 잇는 선으로 둘러싸인 구역을 말한다.\n"
            "2) \"유하거리\"란 하천·호소 또는 이에 준하는 수역의 중심선을 따라 물이 흘러가는 방향으로 잰 거리를 말한다.\n"
            "3) \"제1지류\"란 본천으로 직접 유입되는 지천을 말한다."
        ),
    },
    {
        "law_id":          f"{LAW_ID_PREFIX}_별표2",
        "law_name":        LAW_NAME,
        "law_type":        LAW_TYPE,
        "article_no":      "별표2",
        "article_title":   "계획관리지역에서 휴게음식점 등을 설치할 수 없는 지역",
        "byeolpyo_no":     "2",
        "related_article": "제12조",
        "section_title":   "전체",
        "enforcement_date": "20240529",
        "source_url":      f"{SOURCE_BASE}/별표2",
        "chunk_seq":       1,
        "content": (
            "■ 국토의 계획 및 이용에 관한 법률 시행규칙 [별표 2] <개정 2024. 5. 29.>\n"
            "계획관리지역에서 휴게음식점 등을 설치할 수 없는 지역(제12조 관련)\n\n"
            "다음 각 호의 어느 하나에 해당하는 지역. 다만, 「하수도법」에 따른 공공하수처리시설이 설치·운영되거나 다음 각 호의 지역 내 10호 이상의 자연마을이 형성된 지역은 제외한다.\n"
            "1. 저수를 광역상수원으로 이용하는 댐의 계획홍수위선(계획홍수위선이 없는 경우에는 상시만수위선을 말한다. 이하 같다)으로부터 1킬로미터 이내인 집수구역\n"
            "2. 저수를 광역상수원으로 이용하는 댐의 계획홍수위선으로부터 수계상 상류방향으로 유하거리가 20킬로미터 이내인 하천의 양안(兩岸: 양쪽 기슭) 중 해당 하천의 경계로부터 1킬로미터 이내인 집수구역\n"
            "3. 제2호의 하천으로 유입되는 지천(제1지류인 하천을 말하며, 계획홍수위선으로부터 20킬로미터 이내에서 유입되는 경우에 한정한다. 이하 이 호에서 같다)의 유입지점으로부터 수계상 상류방향으로 유하거리가 10킬로미터 이내인 지천의 양안 중 해당 지천의 경계로부터 500미터 이내인 집수구역\n"
            "4. 상수원보호구역으로부터 500미터 이내인 집수구역\n"
            "5. 상수원보호구역으로 유입되는 하천의 유입지점으로부터 수계상 상류방향으로 유하거리가 10킬로미터 이내인 하천의 양안 중 해당 하천의 경계로부터 500미터 이내인 집수구역\n"
            "6. 유효저수량이 30만세제곱미터 이상인 농업용저수지의 계획홍수위선의 경계로부터 200미터 이내인 집수구역\n"
            "7. 「하천법」에 따른 국가하천·지방하천(도시·군계획조례로 정하는 지방하천은 제외한다)의 양안 중 해당 하천의 경계로부터 직선거리가 100미터 이내인 집수구역(「하천법」제10조에 따른 연안구역을 제외한다)\n"
            "8. 삭제 <2024. 5. 29.>\n\n"
            "주\n"
            "1) \"집수구역\"이란 빗물이 상수원·하천·저수지 등으로 흘러드는 지역으로서 주변의 능선을 잇는 선으로 둘러싸인 구역을 말한다.\n"
            "2) \"유하거리\"란 하천·호소 또는 이에 준하는 수역의 중심선을 따라 물이 흘러가는 방향으로 잰 거리를 말한다.\n"
            "3) \"제1지류\"란 본천으로 직접 유입되는 지천을 말한다."
        ),
    },
]

# ── 1) byeolpyo_chunks.jsonl 저장 (기존 항목 중복 방지)
BYEOLPYO_DIR.mkdir(parents=True, exist_ok=True)
existing_ids = set()
if BYEOLPYO_PATH.exists():
    with open(BYEOLPYO_PATH, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                existing_ids.add(rec.get("law_id", "") + "_" + str(rec.get("chunk_seq", 0)))

added_to_jsonl = 0
with open(BYEOLPYO_PATH, "a", encoding="utf-8") as f:
    for chunk in new_chunks:
        key = chunk["law_id"] + "_" + str(chunk["chunk_seq"])
        if key not in existing_ids:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
            added_to_jsonl += 1
print(f"byeolpyo_chunks.jsonl: {added_to_jsonl}개 추가")

# ── 2) 임베딩 모델 로드
print("임베딩 모델 로드 중...")
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
embed_model = HuggingFaceEmbedding(model_name="jhgan/ko-sroberta-multitask")
print("완료")

# ── 3) chroma_db 인덱싱
import chromadb
client = chromadb.PersistentClient(path=str(CHROMA_DIR))
col = client.get_or_create_collection("law_articles", metadata={"hnsw:space": "cosine"})

existing_chroma_ids = set(col.get(limit=200_000, include=[])["ids"])

docs_to_add = []
for chunk in new_chunks:
    doc_id = f"byp_{chunk['law_id']}_{chunk['chunk_seq']}"
    if doc_id in existing_chroma_ids:
        print(f"  스킵(중복): {doc_id}")
        continue

    section = chunk.get("section_title", "")
    related = chunk.get("related_article", "")
    text = (
        f"[{chunk['law_name']}] "
        f"{chunk['article_no']} {chunk['article_title']}"
        + (f" [{section}]" if section else "")
        + (f" (관련조문: {related})" if related else "")
        + f"\n{chunk['content']}"
    ).strip()

    meta = {
        "law_id":           chunk["law_id"],
        "law_name":         chunk["law_name"],
        "law_type":         chunk["law_type"],
        "article_no":       chunk["article_no"],
        "article_title":    chunk["article_title"][:200],
        "enforcement_date": chunk["enforcement_date"],
        "source_url":       chunk["source_url"],
        "is_byeolpyo":      "true",
        "byeolpyo_no":      chunk["byeolpyo_no"],
        "related_article":  chunk.get("related_article", ""),
        "chunk_seq":        str(chunk["chunk_seq"]),
        "section_title":    chunk.get("section_title", ""),
    }
    docs_to_add.append({"id": doc_id, "text": text, "meta": meta})

print(f"\n인덱싱 대상: {len(docs_to_add)}개")
for d in docs_to_add:
    print(f"  임베딩: {d['id']} ...", end="", flush=True)
    embedding = embed_model.get_text_embedding(d["text"])
    col.add(ids=[d["id"]], embeddings=[embedding], documents=[d["text"]], metadatas=[d["meta"]])
    print(" 완료")

print(f"\n완료! law_articles 총 청크: {col.count()}")
