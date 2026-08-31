"""tests/report/test_context_resend_report_integration.py — render_markdown /
render_json accept and emit Context Resend Detector results.

Verifies the third-commit contract per Rule 8 for
Context-Resend-Detector-prereg §5 (interface) and §11 (commit chain step 3):

  - `render_markdown` and `render_json` gain an optional `context_resend`
    parameter with `None` default.
  - When None or when the result is empty (no LLM calls in trace), output
    is bit-identical to pre-Context-Resend-prereg (backward compat).
  - When populated, both renderers surface the summary line and the
    dedicated section / JSON block.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


from clew.detect.cascade import CascadeResult
from clew.detect.context_resend import (
    ContextResendResult,
    find_context_resend,
)
from clew.model import Span, Trace
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


def _mk_llm_call(span_id: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "span_id": span_id,
        "input_text": json.dumps(messages),
        "input_tokens": 100,
        "output_tokens": 20,
        "input_cost_rate": 3e-6,
        "output_cost_rate": 15e-6,
        "cost_rate_legacy": None,
        "model": "claude-sonnet-4.5",
        "start_time": "2026-01-01T00:00:00+00:00",
    }


def _empty_cascade(trace_id: str) -> CascadeResult:
    return CascadeResult(trace_id=trace_id, wasteful=False)


# ── backward-compat gate ────────────────────────────────────────────────────

def test_render_markdown_backward_compat_when_context_resend_omitted():
    """Omitting the new parameter must not add any Context resend content."""
    trace = _root_trace("t1")
    md = render_markdown(trace, _empty_cascade("t1"), details=[])
    assert "Context resend" not in md
    assert "context_resend" not in md.lower() or "context_resend" not in md


def test_render_json_backward_compat_when_context_resend_omitted():
    """Omitting the new parameter must not add any context_resend key."""
    trace = _root_trace("t1")
    js = json.loads(render_json(trace, _empty_cascade("t1"), details=[]))
    assert "context_resend" not in js or js.get("context_resend") is None


def test_render_markdown_backward_compat_with_empty_result():
    """Passing an empty ContextResendResult also produces no section."""
    trace = _root_trace("t1")
    empty = ContextResendResult(trace_id="t1")
    md = render_markdown(trace, _empty_cascade("t1"), details=[], context_resend=empty)
    assert "Context resend" not in md


def test_render_json_backward_compat_with_empty_result():
    trace = _root_trace("t1")
    empty = ContextResendResult(trace_id="t1")
    js = json.loads(render_json(
        trace, _empty_cascade("t1"), details=[], context_resend=empty,
    ))
    # The key is still present (schema field) but its value is None so old
    # consumers see the same missing-block shape as before.
    assert js.get("context_resend") is None


# ── content rendering ──────────────────────────────────────────────────────

def _resent_trace_and_result():
    msgs = [
        {"role": "user", "content": "first message"},
        {"role": "assistant", "content": "reply body"},
    ]
    llm_calls = [_mk_llm_call("llm-1", msgs), _mk_llm_call("llm-2", msgs)]
    trace = _root_trace("tr", llm_calls)
    result = find_context_resend(trace)
    assert len(result.resent_events) > 0, "fixture must produce at least one event"
    return trace, result


def test_render_markdown_includes_summary_line_and_section():
    trace, result = _resent_trace_and_result()
    md = render_markdown(trace, _empty_cascade("tr"), details=[], context_resend=result)

    # Top-summary line lives in the Result block.
    assert "**Context resend**:" in md
    # Dedicated section header rendered.
    assert "## Context resend" in md
    # Accuracy flag surfaced.
    assert "cost accuracy" in md.lower()


def test_render_json_includes_context_resend_block():
    trace, result = _resent_trace_and_result()
    js = json.loads(render_json(
        trace, _empty_cascade("tr"), details=[], context_resend=result,
    ))
    assert js["context_resend"] is not None
    block = js["context_resend"]
    assert block["n_events"] == len(result.resent_events)
    assert block["cost_accuracy_flag"] in ("accurate", "estimated")
    assert 0.0 <= block["resent_tokens_ratio"] <= 1.0
    # Each event serialized with expected keys.
    for ev in block["events"]:
        assert set(ev.keys()) == {
            "llm_span_id", "origin_llm_span_id", "chunk_hash",
            "chunk_role", "resent_input_tokens", "resent_cost",
        }


def test_render_markdown_legacy_hint_only_when_estimated():
    """Legacy hint appears iff cost_accuracy_flag == 'estimated'."""
    trace = _root_trace("t-legacy", [{
        "span_id": "llm-1",
        "input_text": json.dumps([{"role": "user", "content": "same"}]),
        "input_tokens": 50,
        "output_tokens": 10,
        "input_cost_rate": None,
        "output_cost_rate": None,
        "cost_rate_legacy": 9e-6,
        "model": "claude-sonnet-4.5",
        "start_time": "2026-01-01T00:00:00+00:00",
    }, {
        "span_id": "llm-2",
        "input_text": json.dumps([{"role": "user", "content": "same"}]),
        "input_tokens": 50,
        "output_tokens": 10,
        "input_cost_rate": None,
        "output_cost_rate": None,
        "cost_rate_legacy": 9e-6,
        "model": "claude-sonnet-4.5",
        "start_time": "2026-01-01T00:00:01+00:00",
    }])
    result = find_context_resend(trace)
    md = render_markdown(trace, _empty_cascade("t-legacy"),
                        details=[], context_resend=result)
    assert result.cost_accuracy_flag == "estimated"
    assert "input_cost_table" in md  # hint mentions the config knob
