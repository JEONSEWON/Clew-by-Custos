"""eval/evaluate.py — 2단계 평가 진입점.

★ 유일한 라벨 reader. cascade/structural/semantic 에는 라벨을 인자로도 안 넘긴다.

★ 평가 set(seed=42) 접근 순서 강제:
   1) CRITERIA_FROZEN.md 의 '탐지 파라미터' 섹션이 TBD 면 즉시 RuntimeError → 평가 set 미접근.
   2) EVAL_RUNS.md 의 GREY 행 수가 3 초과면 KILL 로 즉시 RuntimeError → 4번째 시도 차단.
   3) 위 두 게이트를 통과한 뒤에야 EVAL_TRACE_DIR / EVAL_LABELS_PATH 를 처음 읽는다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EVAL_TRACE_DIR = Path("eval/traces")
EVAL_LABELS_PATH = Path("eval/labels.jsonl")
CRITERIA_PATH = Path("validation/CRITERIA_FROZEN.md")
EVAL_RUNS_PATH = Path("validation/EVAL_RUNS.md")

GO_F1 = 0.80
GO_FPR = 0.10
KILL_F1 = 0.60
KILL_FPR = 0.25
GREY_BUDGET = 3


@dataclass
class FrozenParams:
    phi: float
    n: int
    model_name: str
    revision: str


def load_labels(path: Path = EVAL_LABELS_PATH) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        out[rec["trace_id"]] = rec
    return out


def _load_frozen_params(criteria_path: Path = CRITERIA_PATH) -> FrozenParams:
    text = criteria_path.read_text(encoding="utf-8")
    if "<2단계 동결 시점 채움>" in text:
        raise RuntimeError(
            "stage 2 parameters not frozen in CRITERIA_FROZEN.md; refuse to read eval set"
        )
    # 단순 행 기반 파서: "φ ... : <value>" / "반복 임계 N: <value>" / "임베딩 모델 ... : <name> @ revision <sha>"
    phi = _parse_phi(text)
    n = _parse_n(text)
    model_name, revision = _parse_model(text)
    return FrozenParams(phi=phi, n=n, model_name=model_name, revision=revision)


def _parse_phi(text: str) -> float:
    m = re.search(r"φ[^:]*:\s*([0-9]*\.?[0-9]+)", text)
    if not m:
        raise RuntimeError("CRITERIA_FROZEN.md: φ value not found in 탐지 파라미터")
    return float(m.group(1))


def _parse_n(text: str) -> int:
    m = re.search(r"반복 임계\s*N\s*:\s*([0-9]+)", text)
    if not m:
        raise RuntimeError("CRITERIA_FROZEN.md: 반복 임계 N value not found")
    return int(m.group(1))


def _parse_model(text: str) -> tuple[str, str]:
    m = re.search(r"임베딩 모델[^:]*:\s*([\w\-/.]+)\s*@\s*revision\s+([0-9a-f]{40})", text)
    if not m:
        raise RuntimeError("CRITERIA_FROZEN.md: 임베딩 모델 @ revision <40-hex> not found")
    return m.group(1), m.group(2)


def _grey_count(runs_path: Path = EVAL_RUNS_PATH) -> int:
    if not runs_path.exists():
        return 0
    n = 0
    for line in runs_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("|") and "GREY" in line:
            n += 1
    return n


def _trace_level_metrics(results: list, labels: dict[str, dict[str, Any]]) -> dict[str, float]:
    tp = fp = tn = fn = 0
    for r in results:
        actual_pos = labels[r.trace_id]["class"] == "positive"
        pred_pos = r.wasteful
        if pred_pos and actual_pos:
            tp += 1
        elif pred_pos and not actual_pos:
            fp += 1
        elif not pred_pos and actual_pos:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn, "f1": f1, "fpr": fpr}


def _per_pattern_metrics(
    results: list, labels: dict[str, dict[str, Any]]
) -> dict[str, dict]:
    """labels의 pattern 필드로 그루핑 → 패턴별 TP/FP/FN/TN/TPR/FPR."""
    buckets: dict[str, dict] = {}
    for r in results:
        lbl = labels[r.trace_id]
        key = lbl["pattern"] if lbl["pattern"] else "_control"
        b = buckets.setdefault(key, {"tp": 0, "fp": 0, "tn": 0, "fn": 0})
        actual_pos = lbl["class"] == "positive"
        pred_pos = r.wasteful
        if pred_pos and actual_pos:
            b["tp"] += 1
        elif pred_pos:
            b["fp"] += 1
        elif actual_pos:
            b["fn"] += 1
        else:
            b["tn"] += 1
    out: dict[str, dict] = {}
    for key, c in buckets.items():
        tpr = c["tp"] / (c["tp"] + c["fn"]) if (c["tp"] + c["fn"]) else 0.0
        fpr = c["fp"] / (c["fp"] + c["tn"]) if (c["fp"] + c["tn"]) else 0.0
        out[key] = {**c, "tpr": tpr, "fpr": fpr}
    return out


def _verdict(f1: float, fpr: float) -> str:
    if f1 >= GO_F1 and fpr <= GO_FPR:
        return "GO"
    if f1 < KILL_F1 or fpr > KILL_FPR:
        return "KILL"
    return "GREY"


def evaluate(embedder_factory=None, *, criteria_path: Path = CRITERIA_PATH,
             runs_path: Path = EVAL_RUNS_PATH,
             trace_dir: Path = EVAL_TRACE_DIR,
             labels_path: Path = EVAL_LABELS_PATH) -> dict[str, Any]:
    """평가 set 단 1회 측정. embedder_factory 가 None 이면 production Embedder 사용."""
    from clew.detect.cascade import cascade
    from clew.detect.semantic import Embedder
    from clew.model import Trace

    params = _load_frozen_params(criteria_path)
    grey_used = _grey_count(runs_path)
    if grey_used >= GREY_BUDGET:
        raise RuntimeError(f"KILL: 회색지대 예산 N={GREY_BUDGET} 소진 ({grey_used} GREY runs 이미 기록됨)")

    if embedder_factory is None:
        embedder = Embedder(
            model_name=params.model_name, revision=params.revision,
            cache_dir=Path(".cache/embeddings"),
        )
    else:
        embedder = embedder_factory(params)

    traces: list[Trace] = []
    for p in sorted(trace_dir.glob("*.json")):
        traces.append(Trace.model_validate_json(p.read_text(encoding="utf-8")))
    labels = load_labels(labels_path)

    results = [cascade(t, embedder, n=params.n, phi=params.phi) for t in traces]
    metrics = _trace_level_metrics(results, labels)
    per_pattern = _per_pattern_metrics(results, labels)
    verdict = _verdict(metrics["f1"], metrics["fpr"])

    return {
        "phi": params.phi,
        "n": params.n,
        "model": f"{params.model_name}@{params.revision}",
        "f1": metrics["f1"],
        "fpr": metrics["fpr"],
        "tp": metrics["tp"], "fp": metrics["fp"], "tn": metrics["tn"], "fn": metrics["fn"],
        "verdict": verdict,
        "per_pattern": per_pattern,
    }


def _append_run(result: dict[str, Any], runs_path: Path = EVAL_RUNS_PATH) -> None:
    if not runs_path.exists():
        header = (
            "# EVAL_RUNS.md — 평가 set 실행 기록\n\n"
            "회색지대 GREY 행이 3 초과면 4번째 evaluate 실행이 차단된다.\n\n"
            "| run | date | phi | N | model@rev | f1 | fpr | verdict |\n"
            "|---|---|---|---|---|---|---|---|\n"
        )
        runs_path.parent.mkdir(parents=True, exist_ok=True)
        runs_path.write_text(header, encoding="utf-8")

    existing = [
        l for l in runs_path.read_text(encoding="utf-8").splitlines()
        if l.startswith("|") and not l.startswith("|---") and not l.startswith("| run ")
    ]
    run_no = len(existing) + 1
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = (
        f"| {run_no} | {ts} | {result['phi']} | {result['n']} | "
        f"{result['model']} | {result['f1']:.4f} | {result['fpr']:.4f} | {result['verdict']} |\n"
    )
    with runs_path.open("a", encoding="utf-8") as f:
        f.write(row)


def main() -> int:
    result = evaluate()
    print(f"phi={result['phi']}  N={result['n']}  model={result['model']}")
    print(f"TP={result['tp']} FP={result['fp']} TN={result['tn']} FN={result['fn']}")
    print(f"F1={result['f1']:.4f}  FPR={result['fpr']:.4f}  verdict={result['verdict']}")
    _UNCOVERED = {"regen_handoff"}
    print()
    print(f"{'pattern':<18} {'TP':>4} {'FP':>4} {'FN':>4} {'TN':>4}  {'TPR':>6}  {'FPR':>6}")
    for pat, m in sorted(result["per_pattern"].items()):
        tag = "  [uncovered]" if pat in _UNCOVERED else ""
        print(
            f"{pat:<18} {m['tp']:>4} {m['fp']:>4} {m['fn']:>4} {m['tn']:>4}"
            f"  {m['tpr']:>6.3f}  {m['fpr']:>6.3f}{tag}"
        )
    _append_run(result)
    return 0 if result["verdict"] != "KILL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
