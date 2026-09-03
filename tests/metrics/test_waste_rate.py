"""tests/metrics/test_waste_rate.py — Waste-rate metric v1.

Locks the behaviour defined in `docs/WASTE_RATE_METRIC_PREREG.md` §7.1.

Fixtures are hand-constructed `Trace` objects with tool spans and
`metadata["llm_calls"]` populated. `Embedder._compute` is monkeypatched
with a deterministic hash-based fake vector — cascade never invokes
cosine on tool spans (tool branch uses sha256), so the fake vector
matters only for non-tool spans, of which the fixtures have none.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from clew.detect.semantic import Embedder
from clew.metrics.waste_rate import (
    DETECTOR_ORDER,
    SDR_THRESHOLD,
    PerDetectorMetric,
    WasteRateMetric,
    aggregate_sdr_at_10,
    compute_waste_rate,
)
from clew.model import Span, Trace


# ── helpers ─────────────────────────────────────────────────────────────────

def _ts(offset_sec: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset_sec)


def _root(trace_id: str = "t") -> Span:
    return Span(
        trace_id=trace_id,
        span_id="root",
        parent_span_id=None,
        agent_or_node_id="root",
        span_kind="chain",
        start_time=_ts(0),
        end_time=_ts(100),
        input_text="",
        output_text="[root]",
    )


def _tool_span(
    sid: str,
    agent: str,
    t: int,
    input_text: str,
    output_text: str,
    *,
    tokens: int = 10,
    cost_rate: float | None = 1e-6,
    trace_id: str = "t",
    parent: str = "root",
) -> Span:
    return Span(
        trace_id=trace_id,
        span_id=sid,
        parent_span_id=parent,
        agent_or_node_id=agent,
        span_kind="tool",
        start_time=_ts(t),
        end_time=_ts(t + 1),
        input_text=input_text,
        output_text=output_text,
        token_count=tokens,
        model="fake",
        cost_rate=cost_rate,
    )


def _mk_llm_call(
    span_id: str,
    input_text: str,
    *,
    input_tokens: int = 100,
    input_cost_rate: float | None = 3e-6,
    cost_rate_legacy: float | None = None,
) -> dict[str, Any]:
    return {
        "span_id": span_id,
        "input_text": input_text,
        "input_tokens": input_tokens,
        "input_cost_rate": input_cost_rate,
        "cost_rate_legacy": cost_rate_legacy,
        "model": "claude-sonnet-4.5",
        "start_time": "2026-01-01T00:00:01+00:00",
    }


def _fake_compute(self: Embedder, text: str) -> list[float]:
    h = hashlib.sha256(text.encode("utf-8")).digest()[:16]
    return [b / 255.0 for b in h]


@pytest.fixture
def embedder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Embedder:
    monkeypatch.setattr(Embedder, "_compute", _fake_compute)
    return Embedder(model_name="fake", revision="rev-0000", cache_dir=tmp_path)


# ── unit tests (prereg §7.1) ────────────────────────────────────────────────

def test_wr_char_single_detector_repeat(embedder: Embedder):
    """Two tool spans, same agent/input/output -> cascade flags second.

    WR_char = span2.output_bytes / total_input_bytes (from llm_call).
    Other detectors return 0 events.
    """
    root = _root()
    out = "same output payload"
    s1 = _tool_span("s1", "Read", t=1, input_text='{"path":"a"}', output_text=out)
    s2 = _tool_span("s2", "Read", t=2, input_text='{"path":"a"}', output_text=out)
    input_text_of_llm = "some input text here"
    trace = Trace(
        trace_id="t",
        spans=[root, s1, s2],
        metadata={"llm_calls": [_mk_llm_call("llm-1", input_text_of_llm)]},
    )

    m = compute_waste_rate(trace, embedder=embedder, n=2, phi=0.514345)

    total_bytes = len(input_text_of_llm.encode("utf-8"))
    waste_bytes_expected = len(out.encode("utf-8"))
    assert m.total_input_bytes == total_bytes
    assert m.per_detector["repeat"].waste_bytes == waste_bytes_expected
    assert m.per_detector["repeat"].wr_char == pytest.approx(
        waste_bytes_expected / total_bytes
    )
    # Redundant Read: same span pair on 'Read' → the standalone detector
    # also flags this pair (same target, no intervening write). Test 3
    # covers the overlap case explicitly; here we just assert repeat is
    # non-zero as promised.
    assert m.per_detector["repeat"].waste_bytes > 0


def test_wr_char_multiple_detectors_no_overlap(embedder: Embedder):
    """Two different span pairs → per-detector metrics separate, union sums both.

    We create a Read pair (redundant_read + repeat both flag)
    and separately a *side-effect* pair (duplicate_creation flags with
    'differ' entity IDs). The two pairs share no span_ids, so per-detector
    waste_bytes should not overlap.
    """
    root = _root()
    # Read pair (flagged by repeat via cascade AND by redundant_read).
    read_out = "read content"
    r1 = _tool_span("r1", "Read", t=1, input_text='{"path":"x"}', output_text=read_out)
    r2 = _tool_span("r2", "Read", t=2, input_text='{"path":"x"}', output_text=read_out)
    # Side-effect pair with differing entity IDs (canvas-canvas_create_course).
    # entity_id extractor uses path "id" — so output must be a JSON dict.
    create_out_1 = json.dumps({"id": "101", "name": "Course A"})
    create_out_2 = json.dumps({"id": "202", "name": "Course A"})
    c1 = _tool_span(
        "c1", "canvas-canvas_create_course", t=3,
        input_text=json.dumps({"name": "Course A"}), output_text=create_out_1,
    )
    c2 = _tool_span(
        "c2", "canvas-canvas_create_course", t=4,
        input_text=json.dumps({"name": "Course A"}), output_text=create_out_2,
    )
    trace = Trace(
        trace_id="t",
        spans=[root, r1, r2, c1, c2],
        metadata={"llm_calls": [_mk_llm_call("llm-1", "input body long enough for ratios")]},
    )

    m = compute_waste_rate(trace, embedder=embedder, n=2, phi=0.514345)

    assert m.per_detector["repeat"].flagged_span_ids == frozenset({"r2"})
    assert m.per_detector["redundant_read"].flagged_span_ids == frozenset({"r2"})
    assert m.per_detector["duplicate_creation"].flagged_span_ids == frozenset({"c2"})
    # Union spans = {r2, c2} (r2 counted once even though two detectors flag).
    expected_union_bytes = (
        len(read_out.encode("utf-8")) + len(create_out_2.encode("utf-8"))
    )
    assert m.union_waste_bytes == expected_union_bytes


def test_wr_char_multiple_detectors_with_overlap(embedder: Embedder):
    """Same Read pair flagged by repeat AND redundant_read → per-detector
    counts the bytes once each, union counts them once total (byte-unique)."""
    root = _root()
    out = "shared output"
    r1 = _tool_span("r1", "Read", t=1, input_text='{"path":"y"}', output_text=out)
    r2 = _tool_span("r2", "Read", t=2, input_text='{"path":"y"}', output_text=out)
    trace = Trace(
        trace_id="t",
        spans=[root, r1, r2],
        metadata={"llm_calls": [_mk_llm_call("llm-1", "some input here")]},
    )

    m = compute_waste_rate(trace, embedder=embedder, n=2, phi=0.514345)

    out_bytes = len(out.encode("utf-8"))
    assert m.per_detector["repeat"].waste_bytes == out_bytes
    assert m.per_detector["redundant_read"].waste_bytes == out_bytes
    # Union: r2 is in both flagged sets, but bytes count ONCE.
    assert m.union_waste_bytes == out_bytes


def test_wr_cost_uses_frozen_tie_break_order(embedder: Embedder):
    """When a span is flagged by both `repeat` and `redundant_read`,
    union_WR_cost attributes its cost to `repeat` (first in DETECTOR_ORDER).

    We can't observe the attribution directly (union_waste_cost is a sum),
    but we can assert: union_waste_cost equals the r2 span cost exactly
    once, regardless of overlap. Combined with the ordering, the frozen
    tie-break prevents double-counting the same span's cost."""
    root = _root()
    out = "shared"
    r1 = _tool_span("r1", "Read", t=1, input_text='{"path":"z"}', output_text=out,
                    tokens=1000, cost_rate=2e-6)
    r2 = _tool_span("r2", "Read", t=2, input_text='{"path":"z"}', output_text=out,
                    tokens=1000, cost_rate=2e-6)
    trace = Trace(
        trace_id="t",
        spans=[root, r1, r2],
        metadata={"llm_calls": [_mk_llm_call("llm-1", "abc", input_tokens=1000)]},
    )

    m = compute_waste_rate(trace, embedder=embedder, n=2, phi=0.514345)

    # r2 tokens * rate = 1000 * 2e-6 = 2e-3. Counted once in union despite
    # both detectors flagging.
    expected_span_cost = 1000 * 2e-6
    assert m.union_waste_cost == pytest.approx(expected_span_cost, rel=1e-9)
    # Sanity: DETECTOR_ORDER has repeat first (prereg §3).
    assert DETECTOR_ORDER[0] == "repeat"


def test_wr_char_empty_llm_calls_returns_none(embedder: Embedder):
    """Trace without llm_calls metadata → total_bytes == 0 → WR_char is None
    for every detector, `excluded_reason == "no_llm_calls"`."""
    root = _root()
    s1 = _tool_span("s1", "Read", t=1, input_text='{"p":1}', output_text="content")
    trace = Trace(trace_id="t", spans=[root, s1], metadata={})

    m = compute_waste_rate(trace, embedder=embedder, n=2, phi=0.514345)

    assert m.total_input_bytes == 0
    assert m.excluded_reason == "no_llm_calls"
    for det in DETECTOR_ORDER:
        assert m.per_detector[det].wr_char is None
    assert m.union_wr_char is None


def test_wr_cost_unpriced_model_returns_none(embedder: Embedder):
    """LLM calls exist but have no input cost rate → total_cost == 0 → WR_cost None."""
    root = _root()
    out = "content"
    s1 = _tool_span("s1", "Read", t=1, input_text='{"p":1}', output_text=out)
    s2 = _tool_span("s2", "Read", t=2, input_text='{"p":1}', output_text=out)
    unpriced_call = _mk_llm_call(
        "llm-1", "input text", input_cost_rate=None, cost_rate_legacy=None,
    )
    trace = Trace(
        trace_id="t",
        spans=[root, s1, s2],
        metadata={"llm_calls": [unpriced_call]},
    )

    m = compute_waste_rate(trace, embedder=embedder, n=2, phi=0.514345)

    assert m.total_input_cost == 0
    # WR_char is defined (bytes are present) — WR_cost is not.
    assert m.per_detector["repeat"].wr_char is not None
    assert m.per_detector["repeat"].wr_cost is None
    assert m.union_wr_cost is None


def test_sdr_at_10_threshold_boundary():
    """SDR threshold is exactly 0.10 (prereg §5, frozen).

    This is a constant lock: any drift changes the reported session
    detection rate on downstream measurement runs.
    """
    assert SDR_THRESHOLD == 0.10


def test_deterministic_repeat_produces_identical_record(embedder: Embedder):
    """Running the metric twice on the same trace produces byte-identical
    dataclass state (deterministic guarantee, prereg §8 of context_resend +
    §1 of waste_rate)."""
    root = _root()
    out = "deterministic output"
    s1 = _tool_span("s1", "Read", t=1, input_text='{"p":1}', output_text=out)
    s2 = _tool_span("s2", "Read", t=2, input_text='{"p":1}', output_text=out)
    trace = Trace(
        trace_id="t",
        spans=[root, s1, s2],
        metadata={"llm_calls": [_mk_llm_call("llm-1", "an input string")]},
    )

    m1 = compute_waste_rate(trace, embedder=embedder, n=2, phi=0.514345)
    m2 = compute_waste_rate(trace, embedder=embedder, n=2, phi=0.514345)

    assert repr(m1) == repr(m2)


def test_context_resend_chunk_bytes_do_not_dedup_against_tool_bytes(embedder: Embedder):
    """Prereg §4.2 caveat: context_resend chunk bytes live in a separate
    bucket from tool-span bytes. Union sums both without cross-category
    dedup.

    Fixture: two tool spans creating a Repeat flag (span bytes) AND two
    LLM calls with an identical chunk (chunk bytes). We assert union
    equals the sum, not a max/intersection.
    """
    root = _root()
    tool_out = "tool payload"
    s1 = _tool_span("s1", "Read", t=1, input_text='{"p":1}', output_text=tool_out)
    s2 = _tool_span("s2", "Read", t=2, input_text='{"p":1}', output_text=tool_out)
    shared_chunk = {"role": "user", "content": "repeated intent"}
    llm_calls = [
        _mk_llm_call("llm-1", json.dumps([shared_chunk])),
        _mk_llm_call("llm-2", json.dumps([shared_chunk])),
    ]
    trace = Trace(
        trace_id="t",
        spans=[root, s1, s2],
        metadata={"llm_calls": llm_calls},
    )

    m = compute_waste_rate(trace, embedder=embedder, n=2, phi=0.514345)

    span_bytes = len(tool_out.encode("utf-8"))
    # The chunk hash equals sha256 of the sort_keys=True re-serialization.
    canonical_chunk = json.dumps(shared_chunk, sort_keys=True, ensure_ascii=False)
    chunk_bytes = len(canonical_chunk.encode("utf-8"))
    # Union = tool bucket + chunk bucket, no dedup.
    assert m.per_detector["repeat"].waste_bytes == span_bytes
    assert m.per_detector["context_resend"].waste_bytes == chunk_bytes
    assert m.union_waste_bytes == span_bytes + chunk_bytes


# ── union_wr_cost spec compliance (§14 Amendment) ──────────────────────────

def test_union_wr_cost_uses_per_span_waste_cost_from_detector(embedder: Embedder):
    """Regression: pre-§14, union re-derived span cost from `span.token_count
    × cost_rate`, yielding 0 on tool spans (LLM tokens live on the parent
    LLM call). This dropped `redundant_read`'s non-zero waste_cost from
    `union_waste_cost` entirely.

    Fixture: two `Read` spans, same target, *different* outputs → cascade
    (`repeat`) skips (sha256 differs); redundant_read fires (interval-clean
    re-read on same target). span.token_count is 0 on both. Detector's own
    cost model uses output-text tokens × next-turn rate, so its `waste_cost`
    is non-zero. Union must reflect it via `waste_cost_by_span[r2]`.
    """
    root = _root()
    r1 = _tool_span("r1", "Read", t=1, input_text='{"path":"a.py"}',
                    output_text="content A", tokens=0)
    r2 = _tool_span("r2", "Read", t=3, input_text='{"path":"a.py"}',
                    output_text="content B", tokens=0)
    trace = Trace(
        trace_id="t",
        spans=[root, r1, r2],
        metadata={"llm_calls": [_mk_llm_call("llm-1", "x", input_tokens=1000)]},
    )
    m = compute_waste_rate(trace, embedder=embedder, n=2, phi=0.514345)

    # Repeat did not fire (different outputs).
    assert m.per_detector["repeat"].waste_cost == 0.0
    # Redundant_read fired and priced r2 via its own cost model.
    rr_cost = m.per_detector["redundant_read"].waste_cost
    assert rr_cost > 0.0
    assert m.per_detector["redundant_read"].waste_cost_by_span.get("r2") == rr_cost
    # Union preserves redundant_read's contribution (pre-fix this was 0).
    assert m.union_waste_cost == pytest.approx(rr_cost)


def test_waste_cost_by_span_sum_matches_detector_total(embedder: Embedder):
    """Invariant: for every span-level detector, sum of `waste_cost_by_span`
    equals `waste_cost` and every `flagged_span_id` has an entry."""
    root = _root()
    out = "shared"
    r1 = _tool_span("r1", "Read", t=1, input_text='{"path":"z"}', output_text=out,
                    tokens=1000, cost_rate=2e-6)
    r2 = _tool_span("r2", "Read", t=2, input_text='{"path":"z"}', output_text=out,
                    tokens=1000, cost_rate=2e-6)
    trace = Trace(
        trace_id="t",
        spans=[root, r1, r2],
        metadata={"llm_calls": [_mk_llm_call("llm-1", "abc", input_tokens=1000)]},
    )
    m = compute_waste_rate(trace, embedder=embedder, n=2, phi=0.514345)

    for det in ("repeat", "redundant_read", "duplicate_creation"):
        pd = m.per_detector[det]
        assert sum(pd.waste_cost_by_span.values()) == pytest.approx(pd.waste_cost)
        for sid in pd.flagged_span_ids:
            assert sid in pd.waste_cost_by_span


# ── aggregate_sdr_at_10 (corpus-level API) ─────────────────────────────────

def _mk_metric(
    trace_id: str,
    *,
    union_wr_char: float | None = 0.0,
    per_detector_wr_char: dict[str, float | None] | None = None,
    excluded_reason: str | None = None,
) -> WasteRateMetric:
    """Hand-build a WasteRateMetric for aggregation-logic unit tests."""
    det_char = per_detector_wr_char or {}
    per_det = {
        det: PerDetectorMetric(
            detector=det,
            waste_bytes=0,
            waste_cost=0.0,
            wr_char=det_char.get(det),
            wr_cost=None,
        )
        for det in DETECTOR_ORDER
    }
    return WasteRateMetric(
        trace_id=trace_id,
        total_input_bytes=1000,
        total_input_cost=1.0,
        per_detector=per_det,
        union_waste_bytes=0,
        union_waste_cost=0.0,
        union_wr_char=union_wr_char,
        union_wr_cost=None,
        excluded_reason=excluded_reason,
    )


def test_aggregate_sdr_at_10_basic_union_ratio():
    """3 traces (0.05, 0.15, 0.20 union_wr_char) → union_sdr_at_10 = 2/3."""
    metrics = [
        _mk_metric("t1", union_wr_char=0.05),
        _mk_metric("t2", union_wr_char=0.15),
        _mk_metric("t3", union_wr_char=0.20),
    ]
    agg = aggregate_sdr_at_10(metrics)
    assert agg["union_sdr_at_10"] == pytest.approx(2 / 3)


def test_aggregate_sdr_at_10_boundary_is_inclusive():
    """A trace with wr_char exactly 0.10 counts toward the numerator (>=)."""
    metrics = [_mk_metric("t1", union_wr_char=SDR_THRESHOLD)]
    agg = aggregate_sdr_at_10(metrics)
    assert agg["union_sdr_at_10"] == 1.0


def test_aggregate_sdr_at_10_excluded_traces_dropped_from_denominator():
    """`excluded_reason` traces don't count in numerator OR denominator."""
    metrics = [
        _mk_metric("t1", union_wr_char=0.15),
        _mk_metric("t2", union_wr_char=None, excluded_reason="no_llm_calls"),
    ]
    agg = aggregate_sdr_at_10(metrics)
    assert agg["union_sdr_at_10"] == 1.0  # 1 hit / 1 included


def test_aggregate_sdr_at_10_all_excluded_returns_none():
    """When every input trace is excluded, all keys are None (denominator 0)."""
    metrics = [
        _mk_metric("t1", excluded_reason="no_llm_calls"),
        _mk_metric("t2", excluded_reason="no_llm_calls"),
    ]
    agg = aggregate_sdr_at_10(metrics)
    for det in DETECTOR_ORDER:
        assert agg[f"{det}_sdr_at_10"] is None
    assert agg["union_sdr_at_10"] is None


def test_aggregate_sdr_at_10_none_wr_char_not_counted():
    """A None wr_char (undefined for that trace) contributes 0 to numerator."""
    metrics = [
        _mk_metric("t1", union_wr_char=None),
        _mk_metric("t2", union_wr_char=0.20),
    ]
    agg = aggregate_sdr_at_10(metrics)
    assert agg["union_sdr_at_10"] == 0.5


def test_aggregate_sdr_at_10_per_detector_independent():
    """Each detector's SDR@10 is computed from its own wr_char, not union's."""
    metrics = [
        _mk_metric(
            "t1",
            union_wr_char=0.20,
            per_detector_wr_char={
                "repeat": 0.15,
                "context_resend": 0.05,
                "redundant_read": None,
                "duplicate_creation": 0.0,
            },
        ),
    ]
    agg = aggregate_sdr_at_10(metrics)
    assert agg["repeat_sdr_at_10"] == 1.0
    assert agg["context_resend_sdr_at_10"] == 0.0
    assert agg["redundant_read_sdr_at_10"] == 0.0
    assert agg["duplicate_creation_sdr_at_10"] == 0.0
    assert agg["union_sdr_at_10"] == 1.0


# ── WR_COST_PRICE_BASIS_AMENDMENT_PREREG §2 ────────────────────────────────

def _tiered_call(
    span_id: str,
    input_text: str,
    *,
    uncached: int,
    cache_read: int,
    cache_write: int = 0,
    model: str = "claude-sonnet-4.5",
):
    """A call that records how its input was billed, the way Claude Code does."""
    return {
        "span_id": span_id,
        "input_text": input_text,
        "input_tokens": uncached + cache_read + cache_write,
        "input_tokens_uncached": uncached,
        "input_tokens_cache_read": cache_read,
        "input_tokens_cache_write": cache_write,
        "input_cost_rate": 3e-6,
        "cost_rate_legacy": None,
        "model": model,
        "start_time": "2026-01-01T00:00:01+00:00",
    }


def test_denominator_prices_cache_reads_at_the_cache_read_rate(embedder: Embedder):
    """The defect this amendment exists for: 90% of this call's input is a
    cache read, billed at a tenth, and the denominator has to say so."""
    from clew.cost.pricing import get_pricing
    from clew.metrics.waste_rate import _compute_total_input

    call = _tiered_call("llm-1", "x", uncached=1_000, cache_read=9_000)
    trace = Trace(trace_id="t", spans=[_root()], metadata={"llm_calls": [call]})

    _bytes, cost = _compute_total_input(trace)

    pricing = get_pricing("claude-sonnet-4.5")
    billed = (1_000 * pricing.base_input_per_mtok
              + 9_000 * pricing.cache_read_per_mtok) / 1_000_000.0
    assert cost == pytest.approx(billed)

    # And what it used to be: every tier at the base rate, which is the bill
    # for a session that never cached anything.
    no_cache = 10_000 * pricing.base_input_per_mtok / 1_000_000.0
    assert no_cache > cost * 3


def test_numerator_and_denominator_price_the_same_token_the_same_way(embedder: Embedder):
    """§4 of the amendment in one assertion: a call whose input is entirely
    resent must come out at a ratio of 1, whatever the tier mix. Under the old
    denominator this call scored 0.30."""
    from clew.detect.context_resend import input_cost_for_call
    from clew.metrics.waste_rate import _compute_total_input

    call = _tiered_call("llm-1", "x", uncached=1_000, cache_read=9_000)
    trace = Trace(trace_id="t", spans=[_root()], metadata={"llm_calls": [call]})

    _bytes, denominator = _compute_total_input(trace)
    assert denominator == pytest.approx(input_cost_for_call(call))


def test_a_call_without_tiers_is_priced_exactly_as_before(embedder: Embedder):
    """Adapters that record no tiers cannot express the two bases, so nothing
    about them moves. `input_tokens * input_cost_rate`, as it always was."""
    from clew.metrics.waste_rate import _compute_total_input

    call = _mk_llm_call("llm-1", "x", input_tokens=500, input_cost_rate=3e-6)
    trace = Trace(trace_id="t", spans=[_root()], metadata={"llm_calls": [call]})

    _bytes, cost = _compute_total_input(trace)
    assert cost == pytest.approx(500 * 3e-6)


def test_the_toolathlon_shape_does_not_move(embedder: Embedder):
    """P4. Toolathlon sets uncached to everything and both cache fields to 0,
    which is a tier split that happens to be flat -- so the new denominator has
    to return the base-rate figure the old one did."""
    from clew.cost.pricing import get_pricing
    from clew.metrics.waste_rate import _compute_total_input

    call = _tiered_call("llm-1", "x", uncached=4_000, cache_read=0, cache_write=0)
    trace = Trace(trace_id="t", spans=[_root()], metadata={"llm_calls": [call]})

    _bytes, cost = _compute_total_input(trace)
    base = get_pricing("claude-sonnet-4.5").base_input_per_mtok
    assert cost == pytest.approx(4_000 * base / 1_000_000.0)


def test_the_exgentic_shape_does_not_move(embedder: Embedder):
    """P5. Exgentic sets uncached to everything and leaves both cache fields
    None, which is still a tier split and still flat."""
    from clew.cost.pricing import get_pricing
    from clew.metrics.waste_rate import _compute_total_input

    call = _mk_llm_call("llm-1", "x", input_tokens=4_000)
    call["input_tokens_uncached"] = 4_000
    call["input_tokens_cache_read"] = None
    call["input_tokens_cache_write"] = None
    trace = Trace(trace_id="t", spans=[_root()], metadata={"llm_calls": [call]})

    _bytes, cost = _compute_total_input(trace)
    base = get_pricing("claude-sonnet-4.5").base_input_per_mtok
    assert cost == pytest.approx(4_000 * base / 1_000_000.0)


def test_a_call_with_no_rate_and_no_tiers_still_contributes_nothing(embedder: Embedder):
    """The exclusion §1.2 of the metric prereg defines is not collateral of
    this amendment. Pricing every call through the tier function would have
    resolved this model to the default rate and quietly included a trace the
    frozen rule excludes."""
    from clew.metrics.waste_rate import _compute_total_input

    call = _mk_llm_call("llm-1", "x", input_cost_rate=None, cost_rate_legacy=None)
    trace = Trace(trace_id="t", spans=[_root()], metadata={"llm_calls": [call]})

    _bytes, cost = _compute_total_input(trace)
    assert cost == 0.0


def test_tiers_without_a_rate_contribute_nothing(embedder: Embedder):
    """WR_COST_PRICE_BASIS_AMENDMENT_2 §2, and the exact case the first gate
    missed. Exgentic fills the tier fields as uncached-only and leaves the rate
    None when the model is not a key in the table it was handed. Pricing that
    through the tier function resolves the model through `get_pricing`, which
    soft-fails to the Sonnet default -- 8,622 of Corpus C's 10,056 traces
    joined an aggregate they had always been excluded from."""
    from clew.metrics.waste_rate import _compute_total_input

    call = _tiered_call("llm-1", "x", uncached=112_814, cache_read=0,
                        model="DeepSeek-V3.2")
    call["input_cost_rate"] = None
    trace = Trace(trace_id="t", spans=[_root()], metadata={"llm_calls": [call]})

    _bytes, cost = _compute_total_input(trace)
    assert cost == 0.0


def test_a_priced_call_with_tiers_is_still_priced_by_them(embedder: Embedder):
    """The narrowing must not take the amendment with it: a call the adapter
    priced still gets the tier-aware figure, not the flat one."""
    from clew.cost.pricing import get_pricing
    from clew.metrics.waste_rate import _compute_total_input

    call = _tiered_call("llm-1", "x", uncached=1_000, cache_read=9_000)
    trace = Trace(trace_id="t", spans=[_root()], metadata={"llm_calls": [call]})

    _bytes, cost = _compute_total_input(trace)
    pricing = get_pricing("claude-sonnet-4.5")
    billed = (1_000 * pricing.base_input_per_mtok
              + 9_000 * pricing.cache_read_per_mtok) / 1_000_000.0
    assert cost == pytest.approx(billed)


def test_every_waste_cost_is_a_float_even_when_it_is_zero(embedder: Embedder):
    """`PerDetectorMetric.waste_cost` is annotated `float`; a zero must be one.

    `sum({}.values())` returns the int `0`, so a detector that flagged nothing
    handed back an int through a field typed float. Measured 2026-09-03 on a
    zero-waste trace: `repeat`, `redundant_read` and `duplicate_creation` all
    came back `0` as int while `context_resend` came back `0.0`.

    The JSON boundary already coerced with `float()`, so no serialized byte
    moved -- verified identical on a zero-waste trace and on a 1.46 MB real
    session. This asserts the in-memory type, which is what the annotation
    promises and what any consumer reading the dataclass directly gets.
    """
    trace = Trace(trace_id="t", spans=[_root()], metadata={})
    wr = compute_waste_rate(trace, embedder=embedder, n=2, phi=0.514345)

    for name, pm in wr.per_detector.items():
        assert isinstance(pm.waste_cost, float), (
            f"per_detector[{name}].waste_cost is {type(pm.waste_cost).__name__}, "
            "not float"
        )
    assert isinstance(wr.union_waste_cost, float)
