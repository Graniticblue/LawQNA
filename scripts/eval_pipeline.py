#!/usr/bin/env python3
"""
eval_pipeline.py — 법제처 회신 자동 평가 파이프라인 (Phase 1)

사용:
  python scripts/eval_pipeline.py --input data/qa_precedents/updates/법제처_24-0780.jsonl
  python scripts/eval_pipeline.py --all                  # updates/ 전체 평가
  python scripts/eval_pipeline.py --all --skip-existing  # 이미 평가된 파일 건너뜀
  python scripts/eval_pipeline.py --report               # 누적 결과 요약
  python scripts/eval_pipeline.py --report --low         # correctness < 0.7 케이스만
"""

import argparse
import importlib.util
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# ─── 경로 설정 ───────────────────────────────────────────────
BASE_DIR         = Path(__file__).parent.parent
PIPELINE_DIR     = BASE_DIR / "pipeline"
UPDATES_DIR      = BASE_DIR / "data" / "qa_precedents" / "updates"
EVAL_RESULTS_DIR = BASE_DIR / "data" / "eval_results"

sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(PIPELINE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

import os
GOOGLE_API_KEY    = os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL_NAME = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# Windows 콘솔 UTF-8
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")


# ============================================================
# Generator 싱글턴 (케이스마다 재초기화 방지)
# ============================================================

_gen_module   = None
_generator    = None


def _load_gen_module():
    global _gen_module
    if _gen_module is None:
        spec = importlib.util.spec_from_file_location(
            "gen06", PIPELINE_DIR / "06_Generator.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _gen_module = mod
    return _gen_module


def get_generator() -> object:
    global _generator
    if _generator is None:
        mod = _load_gen_module()
        print("검색 엔진 + 임베딩 모델 초기화 중... (최초 1회)")
        _generator = mod.Generator()
        print("초기화 완료.\n")
    return _generator


# ============================================================
# JSONL 파싱
# ============================================================

def load_case(jsonl_path: Path) -> dict | None:
    """법제처 회신 JSONL에서 첫 번째 레코드를 케이스로 파싱."""
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec      = json.loads(line)
            contents = rec.get("contents", [])
            if len(contents) < 2:
                continue
            return {
                "case_id":       rec.get("doc_code", jsonl_path.stem),
                "question":      contents[0]["parts"][0]["text"],
                "ground_truth":  contents[1]["parts"][0]["text"],
                "label_summary": rec.get("label_summary", ""),
                "doc_date":      rec.get("doc_date", ""),
                "source_file":   str(jsonl_path),
            }
    return None


# ============================================================
# LLM Judge
# ============================================================

JUDGE_SYSTEM = """당신은 대한민국 건축법규 AI 답변 평가 전문가입니다.
주어진 질문, 법제처 실제 회신(정답), AI 시스템 답변을 비교하여 아래 JSON 형식으로만 평가하세요.

## 평가 항목

correctness (0.0~1.0)
  AI의 최종 결론이 정답과 일치하는가.
  1.0 = 결론 완전 일치
  0.7 = 주요 결론 일치하나 일부 누락
  0.5 = 결론이 유보적이거나 부분 일치
  0.0 = 결론이 반대이거나 명백한 오류

coverage (0.0~1.0)
  정답의 핵심 법적 논거를 AI가 얼마나 포함했는가.
  1.0 = 핵심 논거 전부 포함
  0.5 = 핵심 논거 일부만 포함
  0.0 = 핵심 논거 대부분 누락

spurious_cite (true/false)
  AI가 [참조 자료 목록]에 없는 판례·해석례 번호를 사실처럼 인용했는가.
  단순히 "관련 대법원 판례" 같은 일반 표현은 해당 안 됨.

missing_articles (배열)
  정답이 인용한 법령 조문 중 AI 답변에서 다루지 않은 것.
  예: ["국토계획법 시행령 제93조제2항", "건축법 제2조제1항제8호"]
  없으면 []

missing_precedents (배열)
  정답이 인용한 해석례·판례 번호 중 AI 답변에서 누락된 것.
  예: ["법제처 14-0171", "대법원 2021두38932"]
  없으면 []

gap_type
  주된 실패 원인 (correctness >= 0.7이면 "none"):
  "retrieval_miss"  — 필요한 조문·해석례가 검색에서 누락됨
  "principle_gap"   — 검색은 됐으나 해석 원칙 미적용으로 결론 오류
  "reasoning_fail"  — 검색·원칙 모두 있는데 추론 과정에서 오류
  "none"            — 정상 처리

gap_detail (한 줄)
  실패 원인 구체 설명. none이면 "정상 처리".

## 출력 형식 (JSON만, 설명 없이)
```json
{
  "correctness": 0.0,
  "correctness_reason": "",
  "coverage": 0.0,
  "coverage_reason": "",
  "spurious_cite": false,
  "spurious_cite_detail": "",
  "missing_articles": [],
  "missing_precedents": [],
  "gap_type": "none",
  "gap_detail": "정상 처리"
}
```"""


def _extract_json(text: str) -> dict:
    """LLM 출력에서 JSON 객체 추출."""
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        raw = m.group(1)
    else:
        start = text.find('{')
        end   = text.rfind('}')
        raw   = text[start:end + 1] if start != -1 and end != -1 else "{}"
    try:
        return json.loads(raw)
    except Exception:
        return {"error": "parse_failed", "raw_snippet": text[:300]}


def run_judge(question: str, ground_truth: str, system_answer: str,
              retrieved_qa_ids: list[str], provider: str = "gemini") -> dict:
    """LLM judge 호출. temperature=0.1로 평가 일관성 확보."""
    mod = _load_gen_module()

    judge_input = f"""## 질문
{question}

## 정답 (법제처 실제 회신)
{ground_truth}

## AI 시스템 답변
{system_answer}

## AI가 검색한 해석례 목록 (doc_code)
{json.dumps(retrieved_qa_ids, ensure_ascii=False)}"""

    if provider == "claude" and ANTHROPIC_API_KEY:
        client = mod.get_claude_client()
        raw = mod.call_claude(client, JUDGE_SYSTEM, judge_input, temperature=0.1)
    else:
        client = mod.get_gemini_client()
        raw = mod.call_gemini(client, JUDGE_SYSTEM, judge_input, temperature=0.1)

    return _extract_json(raw)


# ============================================================
# 단일 케이스 평가
# ============================================================

def evaluate_case(case: dict, provider: str = "gemini",
                  verbose: bool = False) -> dict:
    """케이스 1건 평가."""
    gen = get_generator()

    # 시점 컷오프: 해당 회신일 이후의 해석례·판례는 그 시점에 존재하지 않았으므로
    # 검색에서 제외하고, 평가 대상 자기 자신도 제외(정답 누수 방지 = leave-one-out).
    t0     = time.time()
    result = gen.generate(
        query=case["question"],
        verbose=verbose,
        provider=provider,
        as_of_date=case.get("doc_date", ""),
        exclude_doc_codes={case["case_id"]},
    )
    elapsed = round(time.time() - t0, 1)

    # 검색 결과 요약 (직렬화용)
    retrieved_articles = [
        {"law": d.law_name, "article": d.article_no, "score_type": d.score_type}
        for d in result.get("law_docs", [])
    ]
    retrieved_qa_ids = [
        d.metadata.get("doc_code", "")
        for d in result.get("qa_docs", [])
        if d.metadata.get("doc_code")
    ]

    judge = run_judge(
        question=case["question"],
        ground_truth=case["ground_truth"],
        system_answer=result["answer"],
        retrieved_qa_ids=retrieved_qa_ids,
        provider=provider,
    )

    return {
        "case_id":            case["case_id"],
        "doc_date":           case.get("doc_date", ""),
        "label_summary":      case.get("label_summary", ""),
        "eval_timestamp":     datetime.now().isoformat(),
        "elapsed_sec":        elapsed,
        "provider":           provider,
        # 입력
        "question":           case["question"],
        "ground_truth":       case["ground_truth"],
        # 시스템 출력
        "system_answer":      result["answer"],
        "pass1_output":       result.get("pass1", ""),
        "relation_types":     result.get("relation_types", []),
        "law_hints":          result.get("law_hints", []),
        # 검색 결과
        "retrieved_articles": retrieved_articles,
        "retrieved_qa":       retrieved_qa_ids,
        "source_info":        result.get("source_info", {}),
        # 평가
        "scores":             judge,
    }


# ============================================================
# 배치 실행
# ============================================================

def run_batch(paths: list[Path], provider: str,
              skip_existing: bool, verbose: bool) -> list[dict]:
    EVAL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    all_results = []
    total = len(paths)

    for i, path in enumerate(paths, 1):
        case = load_case(path)
        if not case:
            print(f"[{i}/{total}] ⚠  파싱 실패: {path.name}")
            continue

        out_path = EVAL_RESULTS_DIR / f"{case['case_id']}_eval.json"

        if skip_existing and out_path.exists():
            print(f"[{i}/{total}] ↩  건너뜀: {case['case_id']}")
            with open(out_path, encoding="utf-8") as f:
                all_results.append(json.load(f))
            continue

        print(f"[{i}/{total}] ▶  평가 중: {case['case_id']} ...", end="", flush=True)

        try:
            eval_result = evaluate_case(case, provider=provider, verbose=verbose)

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(eval_result, f, ensure_ascii=False, indent=2)

            s    = eval_result.get("scores", {})
            corr = s.get("correctness", "?")
            cov  = s.get("coverage", "?")
            gap  = s.get("gap_type", "?")
            sec  = eval_result.get("elapsed_sec", "?")
            print(f"  corr={corr}  cov={cov}  gap={gap}  ({sec}s)")
            all_results.append(eval_result)

        except Exception as e:
            print(f"  ❌ 오류: {e}")
            import traceback
            if verbose:
                traceback.print_exc()

    return all_results


# ============================================================
# 요약 리포트
# ============================================================

def print_report(results: list[dict], show_low: bool = False):
    if not results:
        print("평가 결과 없음.")
        return

    total       = len(results)
    scores_list = [r.get("scores", {}) for r in results]

    corr_vals = [s["correctness"] for s in scores_list
                 if isinstance(s.get("correctness"), (int, float))]
    cov_vals  = [s["coverage"]    for s in scores_list
                 if isinstance(s.get("coverage"), (int, float))]
    spurious  = sum(1 for s in scores_list if s.get("spurious_cite"))

    gap_counts: dict[str, int] = {}
    for s in scores_list:
        g = s.get("gap_type", "unknown")
        gap_counts[g] = gap_counts.get(g, 0) + 1

    print(f"\n{'='*62}")
    print(f"Eval 요약  ({total}건  /  {datetime.now().strftime('%Y-%m-%d %H:%M')})")
    print(f"{'='*62}")

    if corr_vals:
        avg_c = sum(corr_vals) / len(corr_vals)
        high  = sum(1 for v in corr_vals if v >= 0.7)
        print(f"  Correctness 평균: {avg_c:.2f}  (≥0.7: {high}/{total}건)")
    if cov_vals:
        print(f"  Coverage 평균:    {sum(cov_vals)/len(cov_vals):.2f}")
    print(f"  거짓 인용 건수:    {spurious}건")

    print(f"\n갭 유형 분포:")
    for gtype, cnt in sorted(gap_counts.items(), key=lambda x: -x[1]):
        bar = "█" * cnt
        print(f"  {gtype:20s}  {cnt:3d}건  {bar}")

    # 자주 누락된 조문
    all_missing_arts: list[str] = []
    for r in results:
        all_missing_arts.extend(r.get("scores", {}).get("missing_articles", []))
    if all_missing_arts:
        from collections import Counter
        top = Counter(all_missing_arts).most_common(8)
        print(f"\n자주 누락된 조문 Top {len(top)}:")
        for art, cnt in top:
            print(f"  {cnt}건  {art}")

    # 자주 누락된 해석례
    all_missing_prec: list[str] = []
    for r in results:
        all_missing_prec.extend(r.get("scores", {}).get("missing_precedents", []))
    if all_missing_prec:
        from collections import Counter
        top = Counter(all_missing_prec).most_common(5)
        print(f"\n자주 누락된 해석례 Top {len(top)}:")
        for p, cnt in top:
            print(f"  {cnt}건  {p}")

    # 저성과 케이스
    low = [r for r in results
           if isinstance(r.get("scores", {}).get("correctness"), (int, float))
           and r["scores"]["correctness"] < 0.7]

    if low:
        print(f"\n⚠  correctness < 0.7 케이스 ({len(low)}건):")
        for r in sorted(low, key=lambda x: x["scores"].get("correctness", 0)):
            s   = r["scores"]
            cid = r["case_id"]
            c   = s.get("correctness", "?")
            g   = s.get("gap_type", "?")
            d   = s.get("gap_detail", "")[:55]
            print(f"  {cid:12s}  corr={c}  gap={g}  {d}")
            if show_low:
                print(f"             {s.get('correctness_reason','')[:80]}")


# ============================================================
# main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="eval_pipeline.py — 법제처 회신 자동 평가"
    )
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--input",  "-i", type=str,
                     help="단일 JSONL 파일 경로")
    grp.add_argument("--all",    "-a", action="store_true",
                     help="updates/ 전체 평가")
    grp.add_argument("--report", "-r", action="store_true",
                     help="기존 eval 결과 요약만 출력")

    parser.add_argument("--provider", default="gemini",
                        choices=["gemini", "claude", "gemma"],
                        help="사용할 LLM 프로바이더 (기본: gemini)")
    parser.add_argument("--skip-existing", action="store_true",
                        help="이미 평가된 케이스 건너뜀")
    parser.add_argument("--low",     action="store_true",
                        help="--report 시 저성과 케이스 상세 표시")
    parser.add_argument("--verbose", action="store_true",
                        help="Generator 내부 로그 출력")
    args = parser.parse_args()

    # 리포트 모드 (Generator 로드 불필요)
    if args.report:
        results = []
        for f in sorted(EVAL_RESULTS_DIR.glob("*_eval.json")):
            with open(f, encoding="utf-8") as fp:
                results.append(json.load(fp))
        print_report(results, show_low=args.low)
        return

    # 평가 대상 파일 수집
    if args.input:
        paths = [Path(args.input)]
        if not paths[0].exists():
            print(f"파일 없음: {paths[0]}")
            sys.exit(1)
    else:
        paths = sorted(UPDATES_DIR.glob("*.jsonl"))
        if not paths:
            print(f"평가할 파일 없음: {UPDATES_DIR}")
            sys.exit(1)

    print(f"평가 대상: {len(paths)}건  /  프로바이더: {args.provider}")
    results = run_batch(paths, args.provider, args.skip_existing, args.verbose)
    print_report(results, show_low=args.low)


if __name__ == "__main__":
    main()
