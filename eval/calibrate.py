"""eval/calibrate.py — dev set(seed=7) 전용 파라미터 결정 (분포 분리 기반).

규율:
- dev set만 읽는다. 평가 set(seed=42) 경로 리터럴은 본문에 등장 금지(가드로 강제).
- φ 는 dev 라벨로 F1 을 *최대화* 하지 않는다. 두 분포의 *갭 중점* 으로 박는다.
  → dev 라벨에 직접 튜닝되는 과적합 차단.
- N 은 dev positive 트레이스에서 "낭비 candidate 가 같은 agent 의 몇 번째 등장이었나" 의 mode.
  → 라벨의 *구조 통계*만 사용(코사인·F1 무관).
- 결정값을 stdout + CALIBRATION_LOG.md 에 기록한다. 운영자가 그 값을
  CRITERIA_FROZEN.md "탐지 파라미터" 섹션에 *수동* 박고 커밋한 뒤에야 evaluate 가
  평가 set 을 처음 로딩한다.

분리 가드(평가 전에 raise 가능):
- gap_p10p90 = P10(중복 코사인) - P90(진전 코사인) > 0 (음수면 두 분포 겹침)
- Cohen's d (중복 vs 진전) ≥ 0.5
- dev_fpr_estimate (진전 쌍 중 cos ≥ φ 비율) ≤ 0.15 (CRITERIA GO_FPR=0.10 + 여유)
"""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from clew.detect.cascade import cascade
from clew.detect.semantic import Embedder, cosine
from clew.detect.structural import find_candidates
from clew.model import Span, Trace

DEV_TRACE_DIR = Path("eval/dev/seed-7/traces")
DEV_LABELS_PATH = Path("eval/dev/seed-7/labels.jsonl")

PRIMARY_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# 분리 가드 임계 (CRITERIA GO_FPR=0.10 + dev 추정 여유)
DEV_FPR_GUARD = 0.15
COHENS_D_GUARD = 0.5

# 후보 수집용 N — 가능한 모든 재등장을 다 쌍으로 만든다 (의미 분리 검증용)
N_FOR_PAIR_COLLECTION = 2


def _resolve_revision(model_id: str) -> str:
    from huggingface_hub import HfApi

    info = HfApi().model_info(model_id)
    return info.sha


def _load_dev_traces() -> list[Trace]:
    return [
        Trace.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(DEV_TRACE_DIR.glob("*.json"))
    ]


def _load_dev_labels() -> dict[str, dict]:
    out: dict[str, dict] = {}
    with DEV_LABELS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            out[row["trace_id"]] = row
    return out


def _percentile(values: list[float], p: float) -> float:
    """선형보간 percentile (stdlib only). p ∈ [0, 100]."""
    if not values:
        raise ValueError("cannot compute percentile of empty sequence")
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (p / 100.0)
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _cohens_d(a: list[float], b: list[float]) -> float:
    """Cohen's d — (mean_a - mean_b) / sqrt((var_a + var_b)/2). 표본 분산."""
    if len(a) < 2 or len(b) < 2:
        return 0.0
    var_a = statistics.variance(a)
    var_b = statistics.variance(b)
    pooled = math.sqrt((var_a + var_b) / 2.0)
    if pooled == 0.0:
        return math.inf if statistics.mean(a) != statistics.mean(b) else 0.0
    return (statistics.mean(a) - statistics.mean(b)) / pooled


def _summary(values: list[float]) -> dict:
    return {
        "count": len(values),
        "p10": round(_percentile(values, 10), 6) if values else None,
        "median": round(_percentile(values, 50), 6) if values else None,
        "p90": round(_percentile(values, 90), 6) if values else None,
        "mean": round(statistics.fmean(values), 6) if values else None,
    }


def collect_pair_cosines(
    traces: list[Trace], labels: dict[str, dict], embedder: Embedder
) -> tuple[list[float], list[float]]:
    """모든 dev 후보 쌍의 코사인을 (중복, 진전) 두 분포로 분류해 반환.

    - 중복(dup): trace.class == "positive" AND candidate.span_id ∈ waste_span_ids
    - 진전(prog): 그 외 모든 후보 쌍 (negative trace 전체 + positive trace 의 비-낭비 candidate)
    """
    dup_cos: list[float] = []
    prog_cos: list[float] = []
    for trace in traces:
        lbl = labels[trace.trace_id]
        waste_ids = set(lbl["waste_span_ids"])
        is_positive_trace = lbl["class"] == "positive"
        for origin, candidate in find_candidates(trace, n=N_FOR_PAIR_COLLECTION):
            cos = cosine(
                embedder.embed(origin.output_text),
                embedder.embed(candidate.output_text),
            )
            if is_positive_trace and candidate.span_id in waste_ids:
                dup_cos.append(cos)
            else:
                prog_cos.append(cos)
    return dup_cos, prog_cos


def choose_phi(dup: list[float], prog: list[float]) -> float:
    """φ = (P10(중복) + P90(진전)) / 2 — 두 분포 갭의 중점."""
    return (_percentile(dup, 10) + _percentile(prog, 90)) / 2.0


def separation_metrics(dup: list[float], prog: list[float], phi: float) -> dict:
    p10_dup = _percentile(dup, 10) if dup else None
    p90_prog = _percentile(prog, 90) if prog else None
    gap = (p10_dup - p90_prog) if (dup and prog) else None
    d = _cohens_d(dup, prog) if (dup and prog) else 0.0
    dev_fpr_estimate = (
        sum(1 for c in prog if c >= phi) / len(prog) if prog else 0.0
    )
    return {
        "gap_p10p90": round(gap, 6) if gap is not None else None,
        "cohens_d": round(d, 4),
        "dev_fpr_estimate": round(dev_fpr_estimate, 4),
        "dup_summary": _summary(dup),
        "prog_summary": _summary(prog),
    }


def trace_level_cascade_fpr(
    traces: list[Trace],
    labels: dict[str, dict],
    embedder: Embedder,
    n: int,
    phi: float,
) -> float:
    """CRITERIA C4 (보고만): dev 의 negative trace 중 cascade 가 wasteful=True 비율.

    낭비 쌍 ≥1 이면 trace flag (cascade.py 의 trace 판정 그대로).
    분모: dev negative trace 총수. 분자: cascade(...).wasteful=True 개수.
    """
    negatives = [t for t in traces if labels[t.trace_id]["class"] == "negative"]
    if not negatives:
        return 0.0
    flagged = sum(
        1 for t in negatives if cascade(t, embedder, n=n, phi=phi).wasteful
    )
    return flagged / len(negatives)


def choose_n(traces: list[Trace], labels: dict[str, dict]) -> int:
    """positive trace 에서 낭비 candidate 가 같은 agent 의 몇 번째 등장이었나의 mode."""
    occurrences_at_waste: list[int] = []
    for trace in traces:
        lbl = labels[trace.trace_id]
        if lbl["class"] != "positive":
            continue
        waste_ids = set(lbl["waste_span_ids"])
        ordered = sorted(trace.spans, key=lambda s: s.start_time)
        running: dict[str, int] = {}
        for s in ordered:
            running[s.agent_or_node_id] = running.get(s.agent_or_node_id, 0) + 1
            if s.span_id in waste_ids:
                occurrences_at_waste.append(running[s.agent_or_node_id])
    if not occurrences_at_waste:
        raise RuntimeError("no waste candidates found in dev positive traces — cannot choose N")
    mode_val, _ = Counter(occurrences_at_waste).most_common(1)[0]
    return int(mode_val)


def calibrate(embedder: Embedder) -> dict:
    """φ·N·분리 지표 + 가드 통과 여부를 결과 dict 로 반환 (raise 하지 않음).

    가드 위반 시에도 진단을 박을 수 있도록, raise 대신 result['guards_passed']/
    result['failures'] 로 신호한다. 운영자(main)가 동결 여부를 결정한다.
    """
    traces = _load_dev_traces()
    labels = _load_dev_labels()
    if len(traces) != len(labels):
        raise RuntimeError(f"dev set size mismatch: {len(traces)} traces vs {len(labels)} labels")

    dup, prog = collect_pair_cosines(traces, labels, embedder)
    if not dup:
        raise RuntimeError("no duplicate-pair cosines collected from dev set — labels or generator broken")
    if not prog:
        raise RuntimeError("no progression-pair cosines collected from dev set — generator structure too narrow")

    phi = choose_phi(dup, prog)
    sep = separation_metrics(dup, prog, phi)
    n = choose_n(traces, labels)
    trace_fpr = trace_level_cascade_fpr(traces, labels, embedder, n=n, phi=phi)

    failures: list[str] = []
    if sep["gap_p10p90"] is None or sep["gap_p10p90"] <= 0.0:
        failures.append(f"gap_p10p90={sep['gap_p10p90']} ≤ 0 (distributions overlap)")
    if sep["cohens_d"] < COHENS_D_GUARD:
        failures.append(f"cohens_d={sep['cohens_d']} < {COHENS_D_GUARD}")
    if sep["dev_fpr_estimate"] > DEV_FPR_GUARD:
        failures.append(
            f"dev_fpr_estimate={sep['dev_fpr_estimate']} > {DEV_FPR_GUARD} (CRITERIA GO_FPR=0.10)"
        )

    return {
        "model_name": embedder.model_name,
        "revision": embedder.revision,
        "phi": round(phi, 6),
        "n": n,
        "separation": sep,
        "trace_level_fpr": round(trace_fpr, 4),
        "guards_passed": not failures,
        "failures": failures,
    }


def _write_log(result: dict, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    sep = result["separation"]
    dup_s = sep["dup_summary"]
    prog_s = sep["prog_summary"]
    lines = [
        f"## calibration @ {ts}",
        "",
        f"- model: `{result['model_name']}`",
        f"- revision: `{result['revision']}`",
        f"- chosen φ: **{result['phi']}**",
        f"- chosen N: **{result['n']}**",
        "",
        "### separation",
        "",
        f"- gap (P10 dup − P90 prog): **{sep['gap_p10p90']}**  (must be > 0)",
        f"- Cohen's d: **{sep['cohens_d']}**  (must be ≥ {COHENS_D_GUARD})",
        f"- pair-level dev_fpr_estimate (진전 쌍 중 cos ≥ φ 비율): **{sep['dev_fpr_estimate']}**  (must be ≤ {DEV_FPR_GUARD})",
        f"- trace-level cascade FPR (C4, 보고만): **{result['trace_level_fpr']}**  (사전등록 목표 ≤ 0.10)",
        "",
        "### cosine distributions on dev set",
        "",
        "| 분포 | count | P10 | median | P90 | mean |",
        "|---|---|---|---|---|---|",
        f"| 중복(dup)  | {dup_s['count']}  | {dup_s['p10']}  | {dup_s['median']}  | {dup_s['p90']}  | {dup_s['mean']}  |",
        f"| 진전(prog) | {prog_s['count']} | {prog_s['p10']} | {prog_s['median']} | {prog_s['p90']} | {prog_s['mean']} |",
        "",
        "φ 는 P10(중복)과 P90(진전) 의 중점에 박혀, 두 분포가 P10/P90 으로 깨끗이 갈리면 dev_fpr_estimate ≈ 0 이 되어야 한다.",
        "",
    ]
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(model_id: str = PRIMARY_MODEL) -> int:
    revision = _resolve_revision(model_id)
    cache_dir = Path(".cache/embeddings")
    embedder = Embedder(model_name=model_id, revision=revision, cache_dir=cache_dir)
    result = calibrate(embedder)

    log_path = Path("validation/CALIBRATION_LOG.md")
    _write_log(result, log_path)

    sep = result["separation"]
    dup_s = sep["dup_summary"]
    prog_s = sep["prog_summary"]
    print(f"model:             {result['model_name']} @ {result['revision']}")
    print(f"chosen φ:          {result['phi']}")
    print(f"chosen N:          {result['n']}")
    print(f"gap (P10−P90):     {sep['gap_p10p90']}")
    print(f"Cohen's d:         {sep['cohens_d']}")
    print(f"dev_fpr_estimate:  {sep['dev_fpr_estimate']}  (pair-level, C3)")
    print(f"trace_level_fpr:   {result['trace_level_fpr']}  (cascade, C4 보고)")
    print("")
    print("cosine distributions on dev set:")
    print(f"  중복(dup)  count={dup_s['count']:>3}  P10={dup_s['p10']}  median={dup_s['median']}  P90={dup_s['p90']}  mean={dup_s['mean']}")
    print(f"  진전(prog) count={prog_s['count']:>3}  P10={prog_s['p10']}  median={prog_s['median']}  P90={prog_s['p90']}  mean={prog_s['mean']}")
    print("")
    print(f"guards: {'PASS' if result['guards_passed'] else 'FAIL'}")
    for f in result["failures"]:
        print(f"  - {f}")
    print(f"log: {log_path}")
    if not result["guards_passed"]:
        return 1
    print("")
    print("다음 단계: validation/CRITERIA_FROZEN.md '탐지 파라미터' 섹션에 위 φ/N/모델 값을")
    print("수동으로 박고 git commit + 'git tag stage2-params-freeze' 하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
