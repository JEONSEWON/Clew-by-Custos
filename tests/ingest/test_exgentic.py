"""tests/ingest/test_exgentic.py — Exgentic parquet adapter contract.

Locks the pre-registered contract in
`docs/WASTE_RATE_EXGENTIC_ADAPTER_AMENDMENT_PREREG.md` §1.

Test categories (§5.2 of the prereg):
  (a) attribute namespace bridge (each §1.2 mapping line)
  (b) synthetic CHAIN root has null parent and envelope times
  (c) multi-`trace_id` collapses to primary, tie-break deterministic
  (d) chat-only scope — non-chat spans dropped by explicit rule
  (e) cache-tier None fields propagate
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

from clew.ingest.exgentic import (
    _pick_primary_trace_id,
    _synth_root_span_id,
    ingest_exgentic_row,
)


# ── Fixtures ────────────────────────────────────────────────────────────


def _mk_span(
    *,
    trace_id: str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    span_id: str = "1111111111111111",
    parent: str = "0000000000000000",
    start: str = "2026-04-12T07:27:42.923007+00:00",
    end: str = "2026-04-12T07:29:00.483000+00:00",
    model: str = "DeepSeek-V3.2",
    input_msgs: str = '[{"role":"user","content":"hello"}]',
    output_msgs: str = '[{"role":"assistant","content":"world"}]',
    input_tokens: int = 100,
    output_tokens: int = 10,
    op: str = "chat",
) -> dict[str, Any]:
    return {
        "span_id": span_id,
        "trace_id": trace_id,
        "parent_span_id": parent,
        "name": f"chat {model}",
        "kind": "SPAN_KIND_CLIENT",
        "start_time": start,
        "end_time": end,
        "status": {"code": 1, "message": ""},
        "attributes": {
            "gen_ai.operation.name": op,
            "gen_ai.request.model": model,
            "gen_ai.response.model": model,
            "gen_ai.input.messages": input_msgs,
            "gen_ai.output.messages": output_msgs,
            "gen_ai.usage.input_tokens": input_tokens,
            "gen_ai.usage.output_tokens": output_tokens,
        },
        "resource_attributes": {},
        "events": "[]",
    }


def _mk_row(spans: list[dict[str, Any]], **extra) -> dict[str, Any]:
    base = {
        "session_id": "sess-abc-001",
        "run_id": "run-xyz",
        "harness": "claude_code",
        "benchmark": "appworld",
        "benchmark_subset": "test_normal",
        "models": ["DeepSeek-V3.2"],
        "score": 0.5,
        "success": False,
        "status": "unfinished",
        "steps": 3,
        "action_count": 3,
        "agent_cost": 0.01,
        "benchmark_cost": 0.0,
        "execution_time": 12.3,
        "total_tokens": sum(
            (s.get("attributes") or {}).get("gen_ai.usage.input_tokens", 0)
            + (s.get("attributes") or {}).get("gen_ai.usage.output_tokens", 0)
            for s in spans
        ),
        "max_tokens": 0,
        "spans": spans,
        "collected_at": "2026-05-18T09:27:45.841329+00:00",
    }
    base.update(extra)
    return base


# ── (a) §1.2 attribute namespace bridge ────────────────────────────────


def test_bridge_input_tokens_populates_llm_calls():
    row = _mk_row([_mk_span(input_tokens=1234, output_tokens=56)])
    trace = ingest_exgentic_row(row)
    llm = trace.metadata["llm_calls"][0]
    assert llm["input_tokens"] == 1234
    assert llm["output_tokens"] == 56


def test_bridge_model_from_request_field():
    row = _mk_row([_mk_span(model="Kimi-K2.5")])
    trace = ingest_exgentic_row(row)
    assert trace.metadata["llm_calls"][0]["model"] == "Kimi-K2.5"
    assert trace.spans[1].model == "Kimi-K2.5"


def test_bridge_input_value_preserves_raw_json():
    payload = '[{"role":"user","parts":[{"type":"text","content":"ctx"}]}]'
    row = _mk_row([_mk_span(input_msgs=payload)])
    trace = ingest_exgentic_row(row)
    assert trace.metadata["llm_calls"][0]["input_text"] == payload
    assert trace.spans[1].input_text == payload


def test_bridge_output_value_preserves_raw_json():
    payload = '[{"role":"assistant","parts":[{"type":"text","content":"answer"}]}]'
    row = _mk_row([_mk_span(output_msgs=payload)])
    trace = ingest_exgentic_row(row)
    assert trace.spans[1].output_text == payload


def test_bridge_token_count_total_sum():
    row = _mk_row([_mk_span(input_tokens=200, output_tokens=25)])
    trace = ingest_exgentic_row(row)
    assert trace.spans[1].token_count == 225


# ── (b) §1.3 synthetic CHAIN root ──────────────────────────────────────


def test_synth_root_parent_is_null():
    row = _mk_row([_mk_span(), _mk_span(span_id="2222222222222222")])
    trace = ingest_exgentic_row(row)
    root = trace.spans[0]
    assert root.parent_span_id is None
    assert root.span_kind == "chain"


def test_synth_root_envelope_times():
    s1 = _mk_span(
        span_id="1111111111111111",
        start="2026-04-12T10:00:00+00:00",
        end="2026-04-12T10:01:00+00:00",
    )
    s2 = _mk_span(
        span_id="2222222222222222",
        start="2026-04-12T10:05:00+00:00",
        end="2026-04-12T10:07:00+00:00",
    )
    row = _mk_row([s1, s2])
    trace = ingest_exgentic_row(row)
    root = trace.spans[0]
    assert root.start_time == datetime(2026, 4, 12, 10, 0, 0, tzinfo=timezone.utc)
    assert root.end_time == datetime(2026, 4, 12, 10, 7, 0, tzinfo=timezone.utc)


def test_synth_root_span_id_deterministic():
    a = _synth_root_span_id("sess-42")
    b = _synth_root_span_id("sess-42")
    c = _synth_root_span_id("sess-99")
    assert a == b
    assert a != c
    assert len(a) == 16
    assert all(ch in "0123456789abcdef" for ch in a)


def test_chat_spans_reparented_to_synth_root():
    s = _mk_span()
    row = _mk_row([s])
    trace = ingest_exgentic_row(row)
    root_id = trace.spans[0].span_id
    chat = trace.spans[1]
    assert chat.parent_span_id == root_id
    assert chat.span_kind == "llm"


# ── (c) §1.4 multi trace_id resolution ─────────────────────────────────


def test_multi_trace_id_primary_is_majority_mode():
    tid_a = "a" * 32
    tid_b = "b" * 32
    row = _mk_row([
        _mk_span(trace_id=tid_a, span_id="1111111111111111"),
        _mk_span(trace_id=tid_a, span_id="2222222222222222"),
        _mk_span(trace_id=tid_b, span_id="3333333333333333"),
    ])
    trace = ingest_exgentic_row(row)
    assert trace.trace_id == tid_a
    assert trace.metadata["exgentic"]["trace_id_secondary_count"] == 1


def test_multi_trace_id_tiebreak_first_seen():
    """Equal counts → first-seen wins (deterministic tiebreak, §1.4)."""
    tid_a = "a" * 32
    tid_b = "b" * 32
    row = _mk_row([
        _mk_span(trace_id=tid_a, span_id="1111111111111111"),
        _mk_span(trace_id=tid_b, span_id="2222222222222222"),
    ])
    trace = ingest_exgentic_row(row)
    # a came first → wins the tie
    assert trace.trace_id == tid_a
    assert trace.metadata["exgentic"]["trace_id_secondary_count"] == 1


def test_multi_trace_id_all_single_secondary_count_zero():
    tid = "c" * 32
    row = _mk_row([
        _mk_span(trace_id=tid, span_id="1111111111111111"),
        _mk_span(trace_id=tid, span_id="2222222222222222"),
    ])
    trace = ingest_exgentic_row(row)
    assert trace.metadata["exgentic"]["trace_id_secondary_count"] == 0


def test_pick_primary_trace_id_pure_function():
    records = [
        {"trace_id": "a"},
        {"trace_id": "b"},
        {"trace_id": "b"},
    ]
    primary, secondary = _pick_primary_trace_id(records)
    assert primary == "b"
    assert secondary == 1


# ── (d) §1.5 chat-only scope ───────────────────────────────────────────


def test_non_chat_span_is_dropped():
    row = _mk_row([
        _mk_span(op="chat", span_id="1111111111111111"),
        _mk_span(op="execute_tool", span_id="2222222222222222"),
    ])
    trace = ingest_exgentic_row(row)
    # 1 CHAIN root + 1 chat span (execute_tool dropped)
    assert len(trace.spans) == 2
    assert trace.spans[0].span_kind == "chain"
    assert trace.spans[1].span_kind == "llm"
    assert trace.metadata["exgentic"]["dropped_non_chat_spans"] == 1


def test_all_non_chat_raises():
    row = _mk_row([
        _mk_span(op="invoke_agent", span_id="1111111111111111"),
        _mk_span(op="execute_tool", span_id="2222222222222222"),
    ])
    with pytest.raises(ValueError, match="non-chat"):
        ingest_exgentic_row(row)


def test_missing_op_name_still_accepted_as_chat():
    """§1.5: `gen_ai.operation.name` missing → default to chat (dataset guarantee)."""
    s = _mk_span()
    del s["attributes"]["gen_ai.operation.name"]
    row = _mk_row([s])
    trace = ingest_exgentic_row(row)
    assert len(trace.spans) == 2  # root + 1 chat
    assert trace.metadata["exgentic"]["dropped_non_chat_spans"] == 0


# ── (e) §1.2 cache-tier None propagation ───────────────────────────────


def test_cache_tier_fields_are_none():
    row = _mk_row([_mk_span()])
    trace = ingest_exgentic_row(row)
    llm = trace.metadata["llm_calls"][0]
    assert llm["input_tokens_cache_read"] is None
    assert llm["input_tokens_cache_write"] is None
    # uncached tier field mirrors input_tokens (all input is uncached)
    assert llm["input_tokens_uncached"] == llm["input_tokens"]


def test_cost_rate_none_when_model_absent_from_table():
    row = _mk_row([_mk_span(model="unknown-model-42")])
    trace = ingest_exgentic_row(row, input_cost_table={"other": 1.0}, output_cost_table={"other": 2.0})
    llm = trace.metadata["llm_calls"][0]
    assert llm["input_cost_rate"] is None
    assert llm["output_cost_rate"] is None


def test_cost_rate_populated_when_model_matches():
    row = _mk_row([_mk_span(model="DeepSeek-V3.2")])
    trace = ingest_exgentic_row(
        row,
        input_cost_table={"DeepSeek-V3.2": 0.28e-6},
        output_cost_table={"DeepSeek-V3.2": 0.42e-6},
    )
    llm = trace.metadata["llm_calls"][0]
    assert llm["input_cost_rate"] == 0.28e-6
    assert llm["output_cost_rate"] == 0.42e-6


# ── Error paths / edge cases ───────────────────────────────────────────


def test_empty_spans_raises():
    row = _mk_row([])
    with pytest.raises(ValueError, match="spans"):
        ingest_exgentic_row(row)


def test_metadata_records_session_provenance():
    row = _mk_row([_mk_span()])
    trace = ingest_exgentic_row(row)
    md = trace.metadata
    assert md["source"] == "exgentic_parquet"
    assert md["session_id"] == "sess-abc-001"
    assert md["benchmark"] == "appworld"
    assert md["harness"] == "claude_code"
    assert md["models"] == ["DeepSeek-V3.2"]


# ── End-to-end: context_resend detector consumes the output ────────────


def test_end_to_end_context_resend_runs_on_output():
    """Detector-facing shape: the produced Trace must be usable by
    `find_context_resend`. This is the acceptance test that binds the
    adapter to the metric pipeline (prereg §1.5 union numerator)."""
    from clew.detect.context_resend import find_context_resend

    # Two chat spans with overlapping input to make resend measurable
    input_a = json.dumps([
        {"role": "user", "content": "Please summarize the following: " + "x" * 400},
    ])
    input_b = json.dumps([
        {"role": "user", "content": "Please summarize the following: " + "x" * 400},
        {"role": "assistant", "content": "First summary"},
        {"role": "user", "content": "Now translate to French"},
    ])
    row = _mk_row([
        _mk_span(
            span_id="1111111111111111",
            start="2026-04-12T10:00:00+00:00",
            end="2026-04-12T10:00:10+00:00",
            input_msgs=input_a,
            input_tokens=200,
            output_tokens=20,
        ),
        _mk_span(
            span_id="2222222222222222",
            start="2026-04-12T10:00:30+00:00",
            end="2026-04-12T10:00:45+00:00",
            input_msgs=input_b,
            input_tokens=300,
            output_tokens=25,
        ),
    ])
    trace = ingest_exgentic_row(row)
    result = find_context_resend(trace)
    # The overlap should register as at least one resent chunk
    assert result.resent_input_tokens > 0
    assert result.total_llm_input_tokens == 500
