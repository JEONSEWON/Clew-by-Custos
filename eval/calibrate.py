"""eval/calibrate.py — dev-set (seed=7) parameter selection via distribution separation.

Discipline:
- Only reads the dev set. Eval-set (seed=42) path literals must not appear
  in this file (enforced by guard).
- φ is not chosen to *maximize* F1 on dev labels. It is pinned to the *midpoint*
  of the gap between the two distributions.
  → Prevents overfitting directly to dev labels.
- N is the mode of "which occurrence-index of the same agent held the waste
  candidate" across dev-positive traces.
  → Uses only the *structural statistics* of labels (no cosine, no F1).
- Chosen values are written to stdout + CALIBRATION_LOG.md. Only after the
  operator manually pins those values into the "Detection parameters" section
  of CRITERIA_FROZEN.md and commits does `evaluate` first load the eval set.

Separation guards (may raise before evaluation):
- gap_p10p90 = P10(dup cosine) - P90(prog cosine) > 0 (negative means overlap)
- Cohen's d (dup vs prog) ≥ 0.5
- dev_fpr_estimate (share of prog pairs with cos ≥ φ) ≤ 0.15
  (CRITERIA GO_FPR=0.10 + slack)
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

# Separation-guard thresholds (CRITERIA GO_FPR=0.10 + dev-estimate slack).
DEV_FPR_GUARD = 0.15
COHENS_D_GUARD = 0.5

# N for candidate collection — pair every possible re-appearance
# (used for semantic-separation validation).
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
    """Linearly-interpolated percentile (stdlib only). p ∈ [0, 100]."""
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
    """Cohen's d — (mean_a - mean_b) / sqrt((var_a + var_b)/2). Sample variance."""
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
    """Return the cosine of every dev candidate pair, split into two distributions
    (duplicate vs progression).

    - dup: trace.class == "positive" AND candidate.span_id ∈ waste_span_ids
    - prog: every other candidate pair (all negative traces + non-waste
      candidates in positive traces)
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
    """φ = (P10(dup) + P90(prog)) / 2 — the midpoint of the gap between the two distributions."""
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
    """CRITERIA C4 (report-only): share of dev negative traces where cascade
    returns wasteful=True.

    A trace is flagged if it has ≥1 waste pair (using cascade.py's trace-level
    verdict as-is). Denominator: total dev negative traces. Numerator: count
    of cascade(...).wasteful=True.
    """
    negatives = [t for t in traces if labels[t.trace_id]["class"] == "negative"]
    if not negatives:
        return 0.0
    flagged = sum(
        1 for t in negatives if cascade(t, embedder, n=n, phi=phi).wasteful
    )
    return flagged / len(negatives)


def choose_n(traces: list[Trace], labels: dict[str, dict]) -> int:
    """Mode of the same-agent occurrence-index at which a waste candidate
    appeared, across positive traces."""
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
    """Return φ, N, separation metrics, and guard status as a dict (never raises).

    On guard violation we still return a full diagnostic — the signal is
    result['guards_passed'] / result['failures'] rather than an exception.
    The operator (main) decides whether to freeze.
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
        f"- pair-level dev_fpr_estimate (share of progression pairs with cos ≥ φ): **{sep['dev_fpr_estimate']}**  (must be ≤ {DEV_FPR_GUARD})",
        f"- trace-level cascade FPR (C4, reporting only): **{result['trace_level_fpr']}**  (pre-registered target ≤ 0.10)",
        "",
        "### cosine distributions on dev set",
        "",
        "| distribution | count | P10 | median | P90 | mean |",
        "|---|---|---|---|---|---|",
        f"| duplicate (dup)  | {dup_s['count']}  | {dup_s['p10']}  | {dup_s['median']}  | {dup_s['p90']}  | {dup_s['mean']}  |",
        f"| progression (prog) | {prog_s['count']} | {prog_s['p10']} | {prog_s['median']} | {prog_s['p90']} | {prog_s['mean']} |",
        "",
        "φ is pinned to the midpoint between P10(dup) and P90(prog); if the two distributions separate cleanly at P10/P90 then dev_fpr_estimate ≈ 0 should hold.",
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
    print(f"trace_level_fpr:   {result['trace_level_fpr']}  (cascade, C4 report)")
    print("")
    print("cosine distributions on dev set:")
    print(f"  dup   count={dup_s['count']:>3}  P10={dup_s['p10']}  median={dup_s['median']}  P90={dup_s['p90']}  mean={dup_s['mean']}")
    print(f"  prog  count={prog_s['count']:>3}  P10={prog_s['p10']}  median={prog_s['median']}  P90={prog_s['p90']}  mean={prog_s['mean']}")
    print("")
    print(f"guards: {'PASS' if result['guards_passed'] else 'FAIL'}")
    for f in result["failures"]:
        print(f"  - {f}")
    print(f"log: {log_path}")
    if not result["guards_passed"]:
        return 1
    print("")
    print("Next step: manually pin the φ / N / model values above into the")
    print("'Detection parameters' section of validation/CRITERIA_FROZEN.md,")
    print("then git commit and `git tag stage2-params-freeze`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
