#!/usr/bin/env python3
"""
embedder.py -- 임베딩 백엔드 단일 진입점 (ONNX Runtime 우선 / torch 폴백)

## 왜 있나

Railway 상주 메모리의 대부분이 벡터DB가 아니라 torch 스택이었다. CPU-only 실측:

    import torch                                  +455 MB
    transformers + sentence-transformers          +335 MB
    ko-sroberta 가중치·추론                        +356 MB   → 임베딩 소계 1,164 MB
    chroma 전 컬렉션(13,862벡터) 검색               +109 MB
                                                  ─────────
                                                   1,272 MB

쿼리 한 줄을 768차원으로 바꾸려고 1.16GB를 24시간 상주시키던 구조다. 같은 가중치를
onnxruntime으로 돌리면 490MB(onnxruntime 16MB + tokenizers + 가중치 438MB)로 끝난다.

## 왜 재인덱싱이 필요 없나

두 백엔드는 같은 가중치에 같은 후처리(mean pooling → L2 정규화)를 적용한다. 실측 결과
두 경로의 벡터는 코사인 1.00000000, 최대 절대오차 1.5e-7 로 사실상 동일하다.
→ torch로 만들어 둔 기존 인덱스를 ONNX로 그대로 검색해도 되고, 반대도 된다.
   백엔드가 섞여도 같은 벡터공간이므로 eval 기준선에 영향이 없다.

(int8 양자화는 여기 쓰지 않는다. 모델은 111MB로 줄지만 벡터가 코사인 0.961~0.970으로
 어긋나 코퍼스 전량 재인덱싱과 eval 재측정이 따라붙는다 — 별건으로 다룰 것.)

## 사용

    from embedder import get_embedder
    embed = get_embedder()
    v  = embed.get_text_embedding("건축법 제5조 적용의 완화 절차는?")   # list[float] 768dim
    vs = embed.get_text_embedding_batch(["...", "..."])              # 인덱싱용 배치

ONNX 자산은 ONNX_EMBED_DIR(기본 models/ko-sroberta-onnx/)의 model.onnx + tokenizer.json.
자산이 없으면 조용히 torch 백엔드로 폴백하므로 로컬 개발 환경은 그대로 돌아간다.
자산 생성: python scripts/export_onnx_embedder.py
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR      = Path(__file__).parent
EMBED_MODEL_NAME = "jhgan/ko-sroberta-multitask"
ONNX_DIR      = Path(os.environ.get("ONNX_EMBED_DIR", str(BASE_DIR / "models" / "ko-sroberta-onnx")))
# 컨테이너는 호스트 CPU를 전부 보므로(예: 32코어) 스레드를 놔두면 스레드마다 워크스페이스가
# 잡혀 RSS가 불어난다. 쿼리 1건 임베딩에 병렬은 무의미하니 1로 못박는다.
_THREADS      = int(os.environ.get("EMBED_NUM_THREADS", "1"))

_EMBEDDER = None


class OnnxEmbedder:
    """onnxruntime + tokenizers 만으로 sentence-transformers 출력을 재현한다.

    재현 대상: Transformer(max_seq_length 잘림) → mean pooling(attention_mask 가중)
               → L2 정규화. 세 단계 모두 export 시 저장한 meta.json 값을 따른다.
    """

    def __init__(self, onnx_dir: Path):
        import json
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self._np = np
        meta = json.loads((onnx_dir / "meta.json").read_text(encoding="utf-8"))
        self.model_name  = meta["model_name"]
        self.dim         = meta["dim"]
        self._max_len    = meta["max_seq_length"]
        self._input_names = meta["inputs"]

        self._tok = Tokenizer.from_file(str(onnx_dir / "tokenizer.json"))
        self._tok.enable_truncation(max_length=self._max_len)
        self._tok.enable_padding()

        so = ort.SessionOptions()
        so.intra_op_num_threads = _THREADS
        so.inter_op_num_threads = _THREADS
        # 그래프 최적화 결과를 캐시해 봐야 콜드스타트에만 쓰이고 RSS만 늘어난다.
        so.enable_mem_pattern = False
        self._sess = ort.InferenceSession(
            str(onnx_dir / "model.onnx"), so, providers=["CPUExecutionProvider"])

    def get_text_embedding_batch(self, texts: list[str]) -> list[list[float]]:
        np = self._np
        if not texts:
            return []
        encs = self._tok.encode_batch([t if t else " " for t in texts])
        ids  = np.array([e.ids for e in encs], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encs], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._input_names:
            # roberta 계열은 type_vocab_size=1 — 전부 0이 정상값이다.
            feed["token_type_ids"] = np.zeros_like(ids)
        last = self._sess.run(["last_hidden_state"], feed)[0]        # (B, T, H)
        m = mask[..., None].astype(np.float32)
        pooled = (last * m).sum(1) / np.clip(m.sum(1), 1e-9, None)   # mean pooling
        pooled = pooled / np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)
        return pooled.astype(np.float32).tolist()

    def get_text_embedding(self, text: str) -> list[float]:
        return self.get_text_embedding_batch([text])[0]

    # llama-index 호환 별칭 — 기존 호출부가 쿼리/문서를 구분해 부를 때를 대비.
    get_query_embedding = get_text_embedding
    get_text_embeddings = get_text_embedding_batch


class TorchEmbedder:
    """기존 경로 그대로 — ONNX 자산이 없는 로컬 환경용 폴백."""

    def __init__(self, model_name: str = EMBED_MODEL_NAME):
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding
        self.model_name = model_name
        self._m = HuggingFaceEmbedding(model_name=model_name)
        self.dim = 768

    def get_text_embedding(self, text: str) -> list[float]:
        return self._m.get_text_embedding(text)

    def get_text_embedding_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._m.get_text_embedding(t) for t in texts]

    get_query_embedding = get_text_embedding
    get_text_embeddings = get_text_embedding_batch


def onnx_assets_ready(onnx_dir: Path = ONNX_DIR) -> bool:
    return all((onnx_dir / f).exists() for f in ("model.onnx", "tokenizer.json", "meta.json"))


def get_embedder(force_backend: str | None = None):
    """프로세스당 1개 임베더를 공유 반환.

    force_backend: "onnx" | "torch" | None(자동). 자동은 ONNX 자산이 있으면 ONNX.
    """
    global _EMBEDDER
    if _EMBEDDER is not None and force_backend is None:
        return _EMBEDDER

    auto = force_backend is None
    want = force_backend or ("onnx" if onnx_assets_ready() else "torch")
    if want == "onnx":
        emb = OnnxEmbedder(ONNX_DIR)
        print(f"[embedder] ONNX Runtime 백엔드 ({ONNX_DIR})")
    else:
        emb = TorchEmbedder()
        why = "ONNX 자산 없음 — scripts/export_onnx_embedder.py 실행" if auto else "명시 지정"
        print(f"[embedder] torch 백엔드 ({why})")

    if force_backend is None:
        _EMBEDDER = emb
    return emb
