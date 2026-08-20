"""tests/report/test_cost_summary.py — Cost Attribution Completion prereg §6.2.

Locks the TraceCostSummary aggregation + report presence.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

from clew.detect.cascade import CascadeResult
from clew.detect.context_resend import ContextResendResult, ResentEvent
from clew.model import Span, Trace
from clew.report._model import TraceCostSummary, build_cost_summary
from clew.report.json_report import render_json
from clew.report.markdown import render_markdown


def _root_trace(trace_id: str, llm_calls: list[dict[str, Any]] | None = None) -> Trace:
    root = Span(
        trace_id=trace_id,
        span_id="root",
        parent_span_id=None,
        agent_or_node_id="root",
        span_kind="chain",
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        input_text="",
        output_text="[root]",
    )
    md: dict[str, Any] = {}
    if llm_calls is not None:
        md["llm_calls"] = llm_calls
    return Trace(trace_id=trace_id, spans=[root], metadata=md)


def _empty_cascade(trace_id: str) -> CascadeResult:
    return CascadeResult(trace_id=trace_id, wasteful=False)


def _tier_split_call(input_tokens: int, cache_read: int, cache_write: int,
                     model: str = "claude-sonnet-4-5") -> dict[str, Any]:
    """Build an llm_calls entry with tier-split token fields."""
    uncached = input_tokens - cache_read - cache_write
    return {
        "span_id": f"llm-{input_tokens}",
        "input_text": "[]",
        "input_tokens": input_tokens,
        "output_tokens": 100,
        "input_tokens_uncached": uncached,
        "input_tokens_cache_read": cache_read,
        "input_tokens_cache_write": cache_write,
        "input_cost_rate": None,
        "output_cost_rate": None,
        "cost_rate_legacy": None,
        "model": model,
        "start_time": "2026-01-01T00:00:00+00:00",
    }


# ── build_cost_summary aggregation ──────────────────────────────────────────

def test_cost_summary_sums_across_detectors():
    """Cascade + context_resend contributions combine into total_waste_cost."""
    trace = _root_trace("t1", [_tier_split_call(1000, 500, 100)])
    cascade = CascadeResult(
        trace_id="t1", wasteful=True, waste_span_ids=["s1"],
        waste_tokens=100, waste_cost=0.5,
    )
    resend = ContextResendResult(trace_id="t1", resent_cost=0.3)

    summary = build_cost_summary(trace, cascade, resend)

    assert summary.total_waste_cost == pytest.approx(0.8)
    assert summary.detector_breakdown["provable_duplicate"] == pytest.approx(0.5)
    assert summary.detector_breakdown["context_resend"] == pytest.approx(0.3)


def test_waste_ratio_computed():
    """waste_ratio = waste / analyzed when analyzed > 0."""
    trace = _root_trace("t2", [_tier_split_call(1000, 0, 0)])
    # Sonnet 4.5 at $3/M input → 1000 tokens = $0.003. Output 100 × $15/M = $0.0015.
    # Total analyzed = $0.0045.
    cascade = CascadeResult(
        trace_id="t2", wasteful=True, waste_span_ids=[],
        waste_tokens=0, waste_cost=0.001,
    )
    summary = build_cost_summary(trace, cascade, None)

    assert summary.total_analyzed_cost == pytest.approx(0.0045)
    assert summary.total_waste_cost == pytest.approx(0.001)
    assert summary.waste_ratio == pytest.approx(0.001 / 0.0045, rel=1e-6)


def test_waste_ratio_zero_when_no_llm():
    """No LLM calls → waste_ratio degrades to 0.0 without crash."""
    trace = _root_trace("t3", [])
    summary = build_cost_summary(trace, None, None)

    assert summary.total_analyzed_cost == 0.0
    assert summary.waste_ratio == 0.0
    # prereg 5.1 reads "accurate" iff every LLM call had tier-split tokens;
    # with no LLM calls that is vacuously true.
    assert summary.accuracy_flag == "accurate"


def test_accuracy_flag_accurate():
    """All llm_calls have tier-split → flag is 'accurate'."""
    trace = _root_trace("t4", [
        _tier_split_call(1000, 500, 100),
        _tier_split_call(2000, 800, 200),
    ])
    summary = build_cost_summary(trace, None, None)
    assert summary.accuracy_flag == "accurate"


def test_accuracy_flag_estimated_when_legacy_fallback():
    """One call lacks tier-split AND explicit rate → flag is 'estimated'."""
    call_split = _tier_split_call(1000, 500, 100)
    call_legacy = {
        "span_id": "llm-legacy",
        "input_text": "[]",
        "input_tokens": 500,
        "output_tokens": 50,
        "input_tokens_uncached": None,
        "input_tokens_cache_read": None,
        "input_tokens_cache_write": None,
        "input_cost_rate": None,
        "output_cost_rate": None,
        "cost_rate_legacy": 9e-6,
        "model": "claude-sonnet-4-5",
        "start_time": "2026-01-01T00:00:01+00:00",
    }
    trace = _root_trace("t5", [call_split, call_legacy])
    summary = build_cost_summary(trace, None, None)
    assert summary.accuracy_flag == "estimated"


# ── report presence ─────────────────────────────────────────────────────────

def test_markdown_summary_section_present():
    """Rendered markdown has '## Cost summary' with expected fields."""
    trace = _root_trace("t6", [_tier_split_call(1000, 500, 100)])
    cascade = CascadeResult(
        trace_id="t6", wasteful=True, waste_span_ids=["s"],
        waste_tokens=100, waste_cost=0.5,
    )
    md = render_markdown(trace, cascade, details=[])

    assert "## Cost summary" in md
    assert "**Total analyzed**" in md
    assert "**Total waste (detected)**" in md
    assert "**Cost accuracy**" in md


def test_json_cost_summary_block_present():
    """Rendered JSON has top-level 'cost_summary' with expected shape."""
    trace = _root_trace("t7", [_tier_split_call(1000, 500, 100)])
    cascade = CascadeResult(
        trace_id="t7", wasteful=True, waste_span_ids=["s"],
        waste_tokens=100, waste_cost=0.5,
    )
    js = json.loads(render_json(trace, cascade, details=[]))

    assert "cost_summary" in js
    block = js["cost_summary"]
    for k in ("total_llm_input_cost", "total_llm_output_cost",
              "total_tool_cost", "total_analyzed_cost", "total_waste_cost",
              "waste_ratio", "accuracy_flag", "detector_breakdown"):
        assert k in block, f"missing key {k} in cost_summary block"
    assert block["accuracy_flag"] in ("accurate", "estimated")
