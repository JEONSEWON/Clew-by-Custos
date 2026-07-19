"""tests/test_cost_amplification.py — cost/amplification module unit tests.

Coverage:
- prev==next skip (recon: 94.3% of failures)
- range calculation (lower/upper = cache_read/base_input × amp_tokens)
- fallback path (missing usage → chars/1.3 approx flag)
- turns_after = cc_total_turns - cc_turn_index[sid]
- unknown model key raises
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from clew.cost.amplification import estimate_amplification
from clew.cost.pricing import get_pricing
from clew.detect.cascade import CascadeResult
from clew.model import Span, Trace


def _ts(o: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=o)


def _tool_span(sid: str, out: str = "payload") -> Span:
    return Span(
        trace_id="t",
        span_id=sid,
        parent_span_id="root",
        agent_or_node_id="Read",
        span_kind="tool",
        start_time=_ts(1),
        end_time=_ts(2),
        input_text="{}",
        output_text=out,
        token_count=None,
        model=None,
        cost_rate=None,
    )


def _root() -> Span:
    return Span(
        trace_id="t",
        span_id="root",
        parent_span_id=None,
        agent_or_node_id="[root]",
        span_kind="chain",
        start_time=_ts(0),
        end_time=_ts(10),
        input_text="",
        output_text="[root]",
    )


def _trace(spans: list[Span], meta: dict) -> Trace:
    return Trace(trace_id="t", spans=spans, metadata=meta)


def _cr(ids: list[str]) -> CascadeResult:
    return CascadeResult(
        trace_id="t",
        wasteful=bool(ids),
        waste_span_ids=ids,
    )


def test_range_calculation_matches_pricing():
    p = get_pricing("sonnet-4.5")
    spans = [_root(), _tool_span("s1")]
    meta = {
        "cc_turn_index": {"s1": 1},
        "cc_total_turns": 11,  # turns_after = 10
        "cc_usage_pair": {
            "s1": {
                "prev": {"cache_read_input_tokens": 100, "cache_creation_input_tokens": 50},
                "next": {"cache_read_input_tokens": 150, "cache_creation_input_tokens": 200},
            }
        },
    }
    est = estimate_amplification(_cr(["s1"]), _trace(spans, meta))
    assert est.n_events == 1
    ev = est.events[0]
    assert ev.waste_tokens == 200
    assert ev.turns_after == 10
    assert ev.amp_tokens == 2000
    assert ev.lower_usd == p.cache_read_cost(2000)
    assert ev.upper_usd == p.base_input_cost(2000)
    assert est.lower_usd < est.upper_usd
    assert est.approx_events == 0


def test_prev_equals_next_is_skipped():
    spans = [_root(), _tool_span("s1")]
    meta = {
        "cc_turn_index": {"s1": 1},
        "cc_total_turns": 5,
        "cc_usage_pair": {
            "s1": {
                "prev": {"cache_read_input_tokens": 100, "cache_creation_input_tokens": 50},
                "next": {"cache_read_input_tokens": 100, "cache_creation_input_tokens": 50},
            }
        },
    }
    est = estimate_amplification(_cr(["s1"]), _trace(spans, meta))
    assert est.n_events == 0
    assert est.n_skipped_prev_eq_next == 1
    assert est.lower_usd == 0.0
    assert est.upper_usd == 0.0


def test_missing_usage_falls_back_to_chars_with_approx_flag():
    output = "x" * 130  # → 130/1.3 = 100 tokens
    spans = [_root(), _tool_span("s1", out=output)]
    meta = {
        "cc_turn_index": {"s1": 2},
        "cc_total_turns": 4,  # turns_after = 2
        "cc_usage_pair": {
            "s1": {
                "prev": {"cache_read_input_tokens": 100, "cache_creation_input_tokens": 50},
                "next": {"cache_read_input_tokens": 150, "cache_creation_input_tokens": None},
            }
        },
    }
    est = estimate_amplification(_cr(["s1"]), _trace(spans, meta))
    assert est.n_events == 1
    ev = est.events[0]
    assert ev.tokens_are_approx is True
    assert ev.waste_tokens == 100
    assert ev.turns_after == 2
    assert ev.amp_tokens == 200
    assert est.approx_events == 1
    assert est.any_approx is True


def test_no_metadata_is_skipped():
    spans = [_root(), _tool_span("s1")]
    meta = {"cc_turn_index": {}, "cc_total_turns": 0, "cc_usage_pair": {}}
    est = estimate_amplification(_cr(["s1"]), _trace(spans, meta))
    assert est.n_events == 0
    assert est.n_skipped_no_metadata == 1


def test_last_turn_yields_zero_turns_after():
    spans = [_root(), _tool_span("s1")]
    meta = {
        "cc_turn_index": {"s1": 5},
        "cc_total_turns": 5,  # turns_after = 0
        "cc_usage_pair": {
            "s1": {
                "prev": {"cache_read_input_tokens": 100, "cache_creation_input_tokens": 50},
                "next": {"cache_read_input_tokens": 150, "cache_creation_input_tokens": 200},
            }
        },
    }
    est = estimate_amplification(_cr(["s1"]), _trace(spans, meta))
    assert est.n_events == 0
    assert est.lower_usd == 0.0


def test_multiple_events_aggregate():
    spans = [_root(), _tool_span("s1"), _tool_span("s2")]
    meta = {
        "cc_turn_index": {"s1": 1, "s2": 3},
        "cc_total_turns": 10,
        "cc_usage_pair": {
            "s1": {
                "prev": {"cache_read_input_tokens": 100, "cache_creation_input_tokens": 50},
                "next": {"cache_read_input_tokens": 150, "cache_creation_input_tokens": 200},
            },
            "s2": {
                "prev": {"cache_read_input_tokens": 200, "cache_creation_input_tokens": 100},
                "next": {"cache_read_input_tokens": 300, "cache_creation_input_tokens": 400},
            },
        },
    }
    est = estimate_amplification(_cr(["s1", "s2"]), _trace(spans, meta))
    assert est.n_events == 2
    # s1: 200 tok * (10-1)=9 turns = 1800
    # s2: 400 tok * (10-3)=7 turns = 2800
    assert est.total_amp_tokens == 1800 + 2800


def test_unknown_model_key_raises():
    import pytest as _pytest
    with _pytest.raises(KeyError):
        get_pricing("no-such-model")
