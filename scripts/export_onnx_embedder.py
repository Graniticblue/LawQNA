#!/usr/bin/env python3
"""
export_onnx_embedder.py -- ko-sroberta → ONNX 자산 생성 (빌드 타임 1회)

serving 컨테이너에서 torch를 들어내기 위한 사전 단계. Docker 멀티스테이지 빌드의
1단계(torch 있는 stage)에서 실행하고, 최종 이미지에는 여기서 나온 models/ 디렉터리와
onnxruntime만 넣는다. 로컬에서 한 번 돌려 두면 개발 환경도 곧바로 ONNX로 돈다.

    python scripts/export_onnx_embedder.py            # 생성 + 동등성 검증
    python scripts/export_onnx_embedder.py --skip-verify

산출: models/ko-sroberta-onnx/{model.onnx, tokenizer.json, meta.json}

필요 패키지(빌드 타임 전용): torch, sentence-transformers, onnx
검증 단계는 추가로 onnxruntime·tokenizers를 쓴다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 로컬에 GPU가 있어도 배포 대상은 CPU다. 내보내기 자체를 CPU에서 해 그래프를 일치시킨다.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

BASE_DIR   = Path(__file__).parent.parent
MODEL_NAME = "jhgan/ko-sroberta-multitask"
OUT_DIR    = Path(os.environ.get("ONNX_EMBED_DIR", str(BASE_DIR / "models" / "ko-sroberta-onnx")))

# 동등성 검증용 — 짧은 질의부터 max_seq_length를 넘겨 잘림 규칙까지 확인하는 긴 조문까지.
PROBES = [
    "건축법 제5조 적용의 완화 절차는?",
    "도시정비법상 조합설립인가 동의율 요건",
    "국토계획법 시행령 제25조 제3항 도시관리계획 경미한 변경",
    "다중이용업소 용도변경 시 필요한 절차는?",
    "",
    "제3조(적용의 완화) ① 허가권자는 다음 각 호의 어느 하나에 해당하는 대지나 건축물에 대하여는 "
    "이 법의 기준을 완화하여 적용할 것을 요청받은 경우 그 요청의 취지와 목적, 대지와 건축물의 "
    "구조·형태 및 주변 여건을 종합적으로 고려하여 완화 여부와 적용 범위를 결정할 수 있다. "
    "이 경우 허가권자는 건축위원회의 심의를 거쳐야 하며, 심의 결과를 요청인에게 문서로 통지하여야 한다. "
    "② 제1항에 따른 완화 적용을 요청하려는 자는 국토교통부령으로 정하는 바에 따라 완화 적용의 "
    "필요성을 소명하는 자료를 갖추어 허가권자에게 제출하여야 한다. 다만, 도시·군계획시설의 설치에 "
    "관한 사항으로서 관계 행정기관의 장과 협의를 마친 경우에는 그러하지 아니하다. "
    "③ 허가권자는 제1항에 따라 완화하여 적용하는 경우 대지의 조경, 건폐율, 용적률, 대지 안의 공지, "
    "건축물의 높이 제한 및 일조 등의 확보를 위한 건축물의 높이 제한에 관한 기준을 완화할 수 있다. " * 3,
]


def export() -> dict:
    import torch
    from sentence_transformers import SentenceTransformer

    print(f"[export] 모델 로드: {MODEL_NAME}")
    st = SentenceTransformer(MODEL_NAME, device="cpu")
    tr, pool = st[0], st[1]
    pcfg = pool.get_config_dict()
    # embedder.py의 OnnxEmbedder는 mean pooling을 하드코딩한다. 모델이 바뀌어 다른 풀링이
    # 되면 벡터가 조용히 어긋나므로 여기서 끊는다.
    if not pcfg.get("pooling_mode_mean_tokens"):
        raise SystemExit(f"[export] mean pooling이 아님 — embedder.py 수정 필요: {pcfg}")

    hf  = tr.auto_model.eval()
    tok = tr.tokenizer
    max_len = tr.max_seq_length
    print(f"[export] model_type={hf.config.model_type} max_seq_length={max_len} pooling=mean")

    enc = tok(["테스트 문장"], return_tensors="pt", padding=True,
              truncation=True, max_length=max_len)
    input_names = [k for k in ("input_ids", "attention_mask", "token_type_ids") if k in enc]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    onnx_path = OUT_DIR / "model.onnx"
    print(f"[export] ONNX 내보내는 중 → {onnx_path}")
    torch.onnx.export(
        hf, tuple(enc[k] for k in input_names), str(onnx_path),
        input_names=input_names, output_names=["last_hidden_state"],
        dynamic_axes={n: {0: "batch", 1: "seq"} for n in input_names + ["last_hidden_state"]},
        opset_version=17, do_constant_folding=True,
        dynamo=False,   # dynamo 경로는 onnxscript를 추가로 요구한다. 레거시 익스포터로 충분.
    )

    tok.backend_tokenizer.save(str(OUT_DIR / "tokenizer.json"))
    meta = {
        "model_name": MODEL_NAME,
        "inputs": input_names,
        "max_seq_length": max_len,
        "pooling": "mean",
        "normalize": True,
        "dim": int(pcfg["word_embedding_dimension"]),
    }
    (OUT_DIR / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[export] 완료 — model.onnx {onnx_path.stat().st_size / 1e6:.1f} MB")
    return meta


def verify() -> int:
    """torch 백엔드와 ONNX 백엔드의 벡터가 같은지 확인. 다르면 non-zero 반환."""
    import numpy as np
    sys.path.insert(0, str(BASE_DIR))
    from embedder import get_embedder

    print("\n[verify] 두 백엔드로 같은 문장을 임베딩해 대조")
    ref = np.array(get_embedder("torch").get_text_embedding_batch(PROBES), dtype=np.float64)
    got = np.array(get_embedder("onnx").get_text_embedding_batch(PROBES), dtype=np.float64)
    cos = (ref * got).sum(1)
    worst = float(cos.min())
    for c, t in zip(cos, PROBES):
        head = (t[:38] + "…") if len(t) > 38 else (t or "(빈 문자열)")
        print(f"  cos={c:.8f}  len={len(t):5d}  {head}")
    print(f"[verify] 최저 코사인 {worst:.8f} / 최대 절대오차 {np.abs(ref - got).max():.2e}")
    # 1e-5는 fp32 연산 순서 차이의 여유분 — 잘림 규칙이나 풀링이 어긋나면 이보다 훨씬 크게 벌어진다.
    if worst < 1 - 1e-5:
        print("[verify] 실패 — 벡터가 어긋난다. 이 상태로 배포하면 검색 품질이 바뀐다.")
        return 1
    print("[verify] 통과 — 기존 인덱스를 그대로 쓸 수 있다(재인덱싱 불요).")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-verify", action="store_true",
                    help="내보내기만 하고 torch 대조는 생략(빌드 타임 단축용)")
    args = ap.parse_args()
    export()
    sys.exit(0 if args.skip_verify else verify())
