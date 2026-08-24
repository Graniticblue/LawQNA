# ============================================================================
# 1단계: ONNX 임베딩 자산 생성 — torch는 오직 이 스테이지에만 존재한다.
#
# 최종 이미지에서 torch를 들어내는 게 목적이다. 실측(CPU-only) 기준 상주 메모리는
#   torch import 455MB + transformers·sentence-transformers 335MB + 가중치·추론 356MB
#   = 1,164MB  →  onnxruntime 경로 490MB
# 로 줄어든다. 두 경로의 벡터는 동일하므로(코사인 1.00000000) 재인덱싱은 필요 없다.
# ============================================================================
FROM python:3.11-slim AS embed-builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 익스포터 전용 의존성. 런타임 이미지에는 하나도 들어가지 않는다.
# 버전을 고정하는 이유: torch가 바뀌면 내보내는 ONNX 그래프가 달라질 수 있고,
# 그러면 벡터가 조용히 어긋난 채 배포된다.
# torch는 '+cpu' 로컬버전으로 못박는다 — 이 태그는 pytorch cpu 인덱스에만 있어서
# PyPI의 CUDA 빌드(수 GB)가 딸려올 여지가 없고, torch의 일반 의존성은 PyPI에서 받는다.
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu \
      torch==2.10.0+cpu \
 && pip install --no-cache-dir \
      sentence-transformers==5.2.3 \
      transformers==4.57.6 \
      onnx==1.22.0

# 익스포터 스크립트만 복사 — 앱 소스가 바뀌었다고 이 무거운 스테이지가
# 다시 돌지 않도록 캐시 경계를 좁게 잡는다.
COPY scripts/export_onnx_embedder.py scripts/

# 빌드 타임에는 내보내기만. torch 대조 검증(--skip-verify 미지정)은 로컬에서 수행한다.
RUN python scripts/export_onnx_embedder.py --skip-verify


# ============================================================================
# 2단계: 런타임 — torch·transformers·sentence-transformers 없음
# ============================================================================
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    TOKENIZERS_PARALLELISM=false \
    MALLOC_ARENA_MAX=2
# 컨테이너는 호스트 CPU를 전부 본다(예: 32코어). 스레드 수를 놔두면 스레드마다
# 워크스페이스와 malloc 아레나가 잡혀 RSS가 불어난다. 쿼리 1건 임베딩에 병렬은 무의미.

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 앱 소스 뒤에 두어야 한다 — .dockerignore가 models/를 빼고 있지만,
# 순서가 뒤집히면 COPY . . 가 자산을 덮어쓸 여지가 생긴다.
COPY --from=embed-builder /build/models /app/models

EXPOSE 8000

# exec 형식(JSON) + chainlit 앞 exec: SIGTERM이 셸이 아닌 앱에 직접 전달돼 graceful shutdown 보장
CMD ["sh", "-c", "python startup.py && exec chainlit run chainlit_app.py --port=${PORT:-8000} --host=0.0.0.0"]
