"""tests/test_evaluate_reproducible.py — evaluate 결정론 + 동결 게이트.

(i)   동결 미완료 CRITERIA → evaluate 호출 시 RuntimeError, 평가 set 미접근
(ii)  GREY 행 3 초과 → 4번째 호출 차단
(iii) 동일 입력으로 2회 호출 → F1·FPR 비트 동일
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from clew.detect.semantic import Embedder
from eval.evaluate import _load_frozen_params, evaluate


def _ts(o: int) -> str:
    dt = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=o)
    return dt.isoformat().replace("+00:00", "Z")


def _trace_json(trace_id: str, agent_sequence: list[tuple[str, str]]) -> dict:
    spans = [
        {
            "trace_id": trace_id, "span_id": "s-0001", "parent_span_id": None,
            "agent_or_node_id": "run", "span_kind": "chain",
            "start_time": _ts(0), "end_time": _ts(1),
            "input_text": "", "output_text": "root",
            "token_count": 10, "model": "fake", "cost_rate": 1e-6,
        }
    ]
    for i, (agent, out) in enumerate(agent_sequence, start=1):
        spans.append({
            "trace_id": trace_id, "span_id": f"s-{i+1:04d}", "parent_span_id": "s-0001",
            "agent_or_node_id": agent, "span_kind": "llm",
            "start_time": _ts(i + 1), "end_time": _ts(i + 2),
            "input_text": "", "output_text": out,
            "token_count": 10, "model": "fake", "cost_rate": 1e-6,
        })
    return {"trace_id": trace_id, "spans": spans, "metadata": {}}


def _write_mini_set(root: Path) -> tuple[Path, Path]:
    """positive(반복+동일출력) 2개 + negative(다양한출력) 2개."""
    trace_dir = root / "traces"
    trace_dir.mkdir(parents=True)
    fixtures = [
        ("t-0001", "positive", [("analyze", "same"), ("analyze", "same")]),
        ("t-0002", "negative", [("a", "x"), ("b", "y")]),
        ("t-0003", "positive", [("review", "dup"), ("review", "dup")]),
        ("t-0004", "negative", [("p", "alpha"), ("q", "beta")]),
    ]
    labels_path = root / "labels.jsonl"
    with labels_path.open("w", encoding="utf-8") as lf:
        for tid, cls, seq in fixtures:
            (trace_dir / f"{tid}.json").write_text(
                json.dumps(_trace_json(tid, seq)), encoding="utf-8"
            )
            lf.write(json.dumps({
                "trace_id": tid, "class": cls,
                "pattern": "repeat_node" if cls == "positive" else None,
                "waste_span_ids": ["s-0003"] if cls == "positive" else [],
            }) + "\n")
    return trace_dir, labels_path


def _frozen_criteria(path: Path, phi: float = 0.95, n: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sha = "0" * 40
    path.write_text(
        "# CRITERIA\n## 탐지 파라미터\n"
        f"- φ (의미 중복 코사인 임계): {phi}\n"
        f"- 반복 임계 N: {n}\n"
        f"- 임베딩 모델 (1개 고정): test-model @ revision {sha}\n",
        encoding="utf-8",
    )


def _unfrozen_criteria(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# CRITERIA\n## 탐지 파라미터\n"
        "- φ (의미 중복 코사인 임계): <2단계 동결 시점 채움>\n"
        "- 반복 임계 N: <2단계 동결 시점 채움>\n"
        "- 임베딩 모델 (1개 고정): <2단계 동결 시점 채움>\n",
        encoding="utf-8",
    )


def _fake_compute(self: Embedder, text: str) -> list[float]:
    h = hashlib.sha256(text.encode("utf-8")).digest()[:16]
    return [b / 255.0 for b in h]


def _factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Embedder, "_compute", _fake_compute)

    def make(params):
        return Embedder(
            model_name=params.model_name, revision=params.revision,
            cache_dir=tmp_path / "_cache",
        )

    return make


def test_unfrozen_criteria_blocks_eval_set_access(tmp_path: Path):
    """동결 안 된 CRITERIA → evaluate 호출 시 raise. 평가 set 미접근."""
    _unfrozen_criteria(tmp_path / "criteria.md")
    with pytest.raises(RuntimeError, match="not frozen"):
        _load_frozen_params(tmp_path / "criteria.md")


def test_evaluate_twice_same_metrics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """동일 입력 → evaluate 두 번 호출 → F1/FPR 비트 동일."""
    trace_dir, labels_path = _write_mini_set(tmp_path)
    criteria_path = tmp_path / "criteria.md"
    runs_path = tmp_path / "runs.md"
    _frozen_criteria(criteria_path, phi=0.99, n=2)
    factory = _factory(tmp_path, monkeypatch)

    r1 = evaluate(
        embedder_factory=factory,
        criteria_path=criteria_path, runs_path=runs_path,
        trace_dir=trace_dir, labels_path=labels_path,
    )
    r2 = evaluate(
        embedder_factory=factory,
        criteria_path=criteria_path, runs_path=runs_path,
        trace_dir=trace_dir, labels_path=labels_path,
    )
    assert r1["f1"] == r2["f1"]
    assert r1["fpr"] == r2["fpr"]
    assert r1["tp"] == r2["tp"] and r1["fp"] == r2["fp"]


def test_grey_budget_blocks_fourth_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """이미 3 GREY 행이 기록되어 있으면 4번째 evaluate 호출 즉시 raise."""
    trace_dir, labels_path = _write_mini_set(tmp_path)
    criteria_path = tmp_path / "criteria.md"
    runs_path = tmp_path / "runs.md"
    _frozen_criteria(criteria_path, phi=0.99, n=2)
    runs_path.write_text(
        "# runs\n\n| run | date | phi | N | m | f1 | fpr | verdict |\n"
        "|---|---|---|---|---|---|---|---|\n"
        "| 1 | 2026-06-01 | 0.9 | 2 | m | 0.7 | 0.2 | GREY |\n"
        "| 2 | 2026-06-02 | 0.9 | 2 | m | 0.7 | 0.2 | GREY |\n"
        "| 3 | 2026-06-03 | 0.9 | 2 | m | 0.7 | 0.2 | GREY |\n",
        encoding="utf-8",
    )
    factory = _factory(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="회색지대 예산"):
        evaluate(
            embedder_factory=factory,
            criteria_path=criteria_path, runs_path=runs_path,
            trace_dir=trace_dir, labels_path=labels_path,
        )


def test_evaluate_positive_dominated_fixture_yields_perfect_f1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """mini fixture 는 합성이라 동일 출력 페어가 명확 → F1=1.0, FPR=0.0."""
    trace_dir, labels_path = _write_mini_set(tmp_path)
    criteria_path = tmp_path / "criteria.md"
    runs_path = tmp_path / "runs.md"
    _frozen_criteria(criteria_path, phi=0.99, n=2)
    factory = _factory(tmp_path, monkeypatch)
    r = evaluate(
        embedder_factory=factory,
        criteria_path=criteria_path, runs_path=runs_path,
        trace_dir=trace_dir, labels_path=labels_path,
    )
    assert r["f1"] == pytest.approx(1.0)
    assert r["fpr"] == pytest.approx(0.0)
    assert r["verdict"] == "GO"


def test_per_pattern_keys_and_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """per_pattern 키 존재 + repeat_node tpr=1.0 + _control fpr=0.0."""
    trace_dir, labels_path = _write_mini_set(tmp_path)
    criteria_path = tmp_path / "criteria.md"
    runs_path = tmp_path / "runs.md"
    _frozen_criteria(criteria_path, phi=0.99, n=2)
    factory = _factory(tmp_path, monkeypatch)
    r = evaluate(
        embedder_factory=factory,
        criteria_path=criteria_path, runs_path=runs_path,
        trace_dir=trace_dir, labels_path=labels_path,
    )
    pp = r["per_pattern"]
    assert "repeat_node" in pp
    assert "_control" in pp
    assert pp["repeat_node"]["tpr"] == pytest.approx(1.0)
    assert pp["_control"]["fpr"] == pytest.approx(0.0)


def test_per_pattern_dev_direct(tmp_path: Path):
    """dev(seed=7) 트레이스·라벨로 _per_pattern_metrics 직접 검증.

    evaluate() 경유 금지 — _append_run / EVAL_RUNS.md 기록 회피.
    cascade + _per_pattern_metrics + _trace_level_metrics 직접 조합.
    """
    from clew.detect.cascade import cascade
    from clew.detect.semantic import Embedder
    from clew.model import Trace
    from eval.evaluate import (
        _load_frozen_params, _per_pattern_metrics, _trace_level_metrics, load_labels,
    )

    DEV_TRACE_DIR = Path("eval/dev/seed-7/traces")
    DEV_LABELS_PATH = Path("eval/dev/seed-7/labels.jsonl")
    CRITERIA_PATH = Path("validation/CRITERIA_FROZEN.md")

    if not DEV_TRACE_DIR.exists():
        pytest.skip("dev set not generated — run: python tasks.py generate-dev-set")

    params = _load_frozen_params(CRITERIA_PATH)
    embedder = Embedder(
        model_name=params.model_name,
        revision=params.revision,
        cache_dir=Path(".cache/embeddings"),
    )
    traces = [
        Trace.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(DEV_TRACE_DIR.glob("*.json"))
    ]
    labels = load_labels(DEV_LABELS_PATH)
    results = [cascade(t, embedder, n=params.n, phi=params.phi) for t in traces]

    pp = _per_pattern_metrics(results, labels)
    agg = _trace_level_metrics(results, labels)

    assert pp["repeat_node"]["tpr"] == pytest.approx(1.0)
    assert pp["pingpong_aba"]["tpr"] == pytest.approx(1.0)
    assert pp["requery_known"]["tpr"] == pytest.approx(1.0)
    assert pp["regen_handoff"]["tpr"] == pytest.approx(0.0)
    assert pp["_control"]["fpr"] == pytest.approx(0.0)
    assert agg["fp"] == 0
    assert agg["tp"] == 30
    assert agg["fn"] == 10
    assert agg["f1"] == pytest.approx(30 / 35)  # precision=1.0, recall=0.75 → F1=0.857
    assert agg["fpr"] == pytest.approx(0.0)
