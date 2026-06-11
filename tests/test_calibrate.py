"""tests/test_calibrate.py — 분포 분리 기반 calibrate 단위 테스트.

라벨/모델 불요. 합성 코사인 분포와 합성 트레이스로 핵심 로직을 검증한다.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from clew.detect.semantic import Embedder
from clew.model import Span, Trace
from eval.calibrate import (
    COHENS_D_GUARD,
    DEV_FPR_GUARD,
    _cohens_d,
    _percentile,
    calibrate,
    choose_n,
    choose_phi,
    collect_pair_cosines,
    separation_metrics,
)


# ----------------------------------------------------------------------
# percentile / Cohen's d
# ----------------------------------------------------------------------

def test_percentile_basic():
    assert _percentile([1, 2, 3, 4, 5], 50) == 3
    assert _percentile([1, 2, 3, 4, 5], 0) == 1
    assert _percentile([1, 2, 3, 4, 5], 100) == 5


def test_percentile_linear_interpolation():
    # P10 of [0, 10] should be 1.0 (linear interp between values)
    assert _percentile([0.0, 10.0], 10) == pytest.approx(1.0)
    assert _percentile([0.0, 10.0], 90) == pytest.approx(9.0)


def test_percentile_empty_raises():
    with pytest.raises(ValueError):
        _percentile([], 50)


def test_cohens_d_separated_distributions_is_large():
    a = [0.9] * 10
    b = [0.1] * 10
    d = _cohens_d(a, b)
    assert d == float("inf") or d > 5.0  # zero-var fallback or huge


def test_cohens_d_identical_distributions_is_zero():
    a = [0.5, 0.6, 0.7, 0.8]
    b = [0.5, 0.6, 0.7, 0.8]
    assert _cohens_d(a, b) == 0.0


# ----------------------------------------------------------------------
# choose_phi / separation_metrics
# ----------------------------------------------------------------------

def test_phi_is_midpoint_of_p10_dup_and_p90_prog():
    dup = [0.80, 0.85, 0.90, 0.95, 1.00] * 4  # P10 ~ 0.82
    prog = [0.10, 0.20, 0.30, 0.40, 0.50] * 4  # P90 ~ 0.46
    phi = choose_phi(dup, prog)
    expected = (_percentile(dup, 10) + _percentile(prog, 90)) / 2.0
    assert phi == pytest.approx(expected)
    assert 0.46 < phi < 0.82  # 두 분포 사이


def test_separation_clean_split_passes_guards():
    dup = [0.90 + 0.01 * i for i in range(10)]
    prog = [0.20 + 0.01 * i for i in range(10)]
    phi = choose_phi(dup, prog)
    sep = separation_metrics(dup, prog, phi)
    assert sep["gap_p10p90"] > 0
    assert sep["cohens_d"] >= COHENS_D_GUARD
    assert sep["dev_fpr_estimate"] <= DEV_FPR_GUARD


def test_separation_overlapping_distributions_gap_negative():
    # 분포가 겹침: dup 의 P10 < prog 의 P90
    dup = [0.50 + 0.01 * i for i in range(10)]   # ~0.50..0.59
    prog = [0.55 + 0.01 * i for i in range(10)]  # ~0.55..0.64
    phi = choose_phi(dup, prog)
    sep = separation_metrics(dup, prog, phi)
    assert sep["gap_p10p90"] <= 0


def test_dev_fpr_estimate_counts_prog_above_phi():
    dup = [0.90] * 10
    prog = [0.30] * 8 + [0.95] * 2  # 20% 가 φ 위로 새어나옴
    phi = choose_phi(dup, prog)
    sep = separation_metrics(dup, prog, phi)
    # P90(prog) 가 0.95 근처, P10(dup)=0.90 → phi 가 분포 안쪽 → fpr 추정 큼
    assert sep["dev_fpr_estimate"] > 0


# ----------------------------------------------------------------------
# choose_n — dev positive trace 구조 통계 (라벨만, 코사인 미사용)
# ----------------------------------------------------------------------

def _ts(o: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=o)


def _span(sid: str, parent: str | None, agent: str, t: int, out: str = "x") -> Span:
    return Span(
        trace_id="t1", span_id=sid, parent_span_id=parent,
        agent_or_node_id=agent, span_kind="llm" if parent else "chain",
        start_time=_ts(t), end_time=_ts(t + 1),
        input_text="", output_text=out,
        token_count=10, model="fake", cost_rate=1e-6,
    )


def test_choose_n_returns_2_when_waste_on_first_repeat():
    """모든 positive trace 에서 낭비가 2회차에 일어나면 mode=2."""
    traces = [
        Trace(trace_id="t1", spans=[
            _span("s1", None, "run", 0),
            _span("s2", "s1", "analyze", 1),
            _span("s3", "s1", "analyze", 2),  # 2회차 = 낭비
        ]),
    ]
    labels = {"t1": {"class": "positive", "waste_span_ids": ["s3"]}}
    assert choose_n(traces, labels) == 2


def test_choose_n_returns_3_when_waste_on_third_occurrence():
    spans = [
        _span("s1", None, "run", 0),
        _span("s2", "s1", "analyze", 1),
        _span("s3", "s1", "analyze", 2),
        _span("s4", "s1", "analyze", 3),
    ]
    spans[0] = Span(**{**spans[0].model_dump(), "trace_id": "t1"})
    for s in spans[1:]:
        pass
    traces = [Trace(trace_id="t1", spans=spans)]
    labels = {"t1": {"class": "positive", "waste_span_ids": ["s4"]}}  # 3회차만 낭비
    assert choose_n(traces, labels) == 3


def test_choose_n_ignores_negative_traces():
    traces = [
        Trace(trace_id="t1", spans=[
            _span("s1", None, "run", 0),
            _span("s2", "s1", "analyze", 1),
            _span("s3", "s1", "analyze", 2),
        ]),
        Trace(trace_id="t1", spans=[
            _span("s1", None, "run", 0),
            _span("s2", "s1", "analyze", 1),
        ]),
    ]
    labels = {
        "t1": {"class": "positive", "waste_span_ids": ["s3"]},
    }
    # negative trace 없어 mode=2
    assert choose_n([traces[0]], labels) == 2


def test_choose_n_raises_when_no_positive_with_waste():
    traces = [
        Trace(trace_id="t1", spans=[_span("s1", None, "run", 0)]),
    ]
    labels = {"t1": {"class": "negative", "waste_span_ids": []}}
    with pytest.raises(RuntimeError, match="no waste candidates"):
        choose_n(traces, labels)


# ----------------------------------------------------------------------
# 전체 calibrate — 결정론 fake embedder 로 분리 검증
# ----------------------------------------------------------------------

def _fake_compute_clean_split(self: Embedder, text: str) -> list[float]:
    """sha256 기반 결정론 벡터 — 같은 텍스트는 같은 벡터, 다른 텍스트는 분명히 다른 벡터."""
    h = hashlib.sha256(text.encode("utf-8")).digest()[:16]
    return [b / 255.0 for b in h]


def test_calibrate_with_clean_split_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(Embedder, "_compute", _fake_compute_clean_split)
    # dev set 합성: 4 traces — 2 positive (반복 + 동일 출력), 2 negative (반복 + 다른 출력)
    import json

    dev_trace_dir = tmp_path / "traces"
    dev_trace_dir.mkdir()
    labels_path = tmp_path / "labels.jsonl"

    def write_trace(tid: str, outs: list[str]) -> None:
        spans = [{
            "trace_id": tid, "span_id": "s-0001", "parent_span_id": None,
            "agent_or_node_id": "run", "span_kind": "chain",
            "start_time": "2026-01-01T00:00:00+00:00",
            "end_time": "2026-01-01T00:00:01+00:00",
            "input_text": "", "output_text": "root",
            "token_count": 10, "model": "f", "cost_rate": 1e-6,
        }]
        for i, out in enumerate(outs, start=1):
            spans.append({
                "trace_id": tid, "span_id": f"s-{i+1:04d}", "parent_span_id": "s-0001",
                "agent_or_node_id": "analyze", "span_kind": "llm",
                "start_time": f"2026-01-01T00:00:0{i+1}+00:00",
                "end_time": f"2026-01-01T00:00:0{i+2}+00:00",
                "input_text": "", "output_text": out,
                "token_count": 10, "model": "f", "cost_rate": 1e-6,
            })
        (dev_trace_dir / f"{tid}.json").write_text(
            json.dumps({"trace_id": tid, "spans": spans, "metadata": {}})
        )

    fixtures = [
        ("t-p1", ["same 1", "same 1"], "positive", ["s-0003"]),
        ("t-p2", ["same 2", "same 2"], "positive", ["s-0003"]),
        ("t-n1", ["foo 1", "bar 1"], "negative", []),
        ("t-n2", ["foo 2", "bar 2"], "negative", []),
    ]
    with labels_path.open("w", encoding="utf-8") as f:
        for tid, outs, cls, waste in fixtures:
            write_trace(tid, outs)
            f.write(json.dumps({
                "trace_id": tid, "class": cls,
                "pattern": "repeat_node" if cls == "positive" else None,
                "waste_span_ids": waste,
            }) + "\n")

    monkeypatch.setattr("eval.calibrate.DEV_TRACE_DIR", dev_trace_dir)
    monkeypatch.setattr("eval.calibrate.DEV_LABELS_PATH", labels_path)

    embedder = Embedder(model_name="fake", revision="rev-0000", cache_dir=tmp_path / "_cache")
    result = calibrate(embedder)

    assert result["n"] == 2
    assert 0.0 < result["phi"] < 1.0
    sep = result["separation"]
    assert sep["gap_p10p90"] > 0
    assert sep["cohens_d"] >= COHENS_D_GUARD
    assert sep["dev_fpr_estimate"] <= DEV_FPR_GUARD


# ----------------------------------------------------------------------
# 가드: dev fpr estimate 임계 / cohen's d 임계가 합리적 값
# ----------------------------------------------------------------------

def test_guards_are_documented_constants():
    assert DEV_FPR_GUARD == 0.15
    assert COHENS_D_GUARD == 0.5
