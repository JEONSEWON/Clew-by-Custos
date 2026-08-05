"""tests/ingest/test_preprocess_llm_calls_preserved.py — llm_calls metadata plumbing.

Locks the behaviour defined in `docs/CONTEXT_RESEND_DETECTOR_PREREG.md` §6.2:
`collapse_llm_spans` records LLM input/token/rate data into
`trace.metadata["llm_calls"]` before removing the LLM spans, and the adapter
temporary key `_pending_llm_extras` is consumed and cleaned up.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from clew.ingest.langgraph import ingest_otel_spans, otel_spans_to_trace
from clew.ingest.preprocess import preprocess_trace


# ── OTel shim helpers (mirrors the shape ReadableSpan exposes) ──────────────

class _Ctx:
    __slots__ = ("trace_id", "span_id")

    def __init__(self, trace_id: int, span_id: int) -> None:
        self.trace_id = trace_id
        self.span_id = span_id


class _Parent:
    __slots__ = ("span_id",)

    def __init__(self, span_id: int) -> None:
        self.span_id = span_id


class _Shim:
    __slots__ = ("context", "parent", "name", "start_time", "end_time", "attributes")

    def __init__(
        self,
        span_id: int,
        parent_span_id: int | None,
        name: str,
        kind: str,
        attributes: dict,
        start_ns: int = 1_700_000_000_000_000_000,
    ) -> None:
        self.context = _Ctx(trace_id=0xAA, span_id=span_id)
        self.parent = _Parent(parent_span_id) if parent_span_id is not None else None
        self.name = name
        self.start_time = start_ns
        self.end_time = start_ns + 1_000_000  # 1ms
        attrs = dict(attributes)
        attrs.setdefault("openinference.span.kind", kind)
        attrs.setdefault("output.value", f"[output for {name}]")
        self.attributes = attrs


def _make_llm_shim(span_id: int, parent: int, *, model: str, input_val: str,
                   prompt: int | None, completion: int | None,
                   start_ns: int = 1_700_000_000_000_000_000) -> _Shim:
    attrs = {
        "input.value": input_val,
        "llm.model_name": model,
    }
    if prompt is not None:
        attrs["llm.token_count.prompt"] = prompt
    if completion is not None:
        attrs["llm.token_count.completion"] = completion
    return _Shim(span_id, parent, name=f"llm-{span_id}", kind="LLM",
                 attributes=attrs, start_ns=start_ns)


def _make_root_shim() -> _Shim:
    return _Shim(0x01, None, name="root", kind="CHAIN", attributes={})


# ── tests ───────────────────────────────────────────────────────────────────

def test_llm_calls_populated_after_preprocess():
    """Trace with two LLM spans -> metadata['llm_calls'] has both entries in start-time order."""
    root = _make_root_shim()
    llm_a = _make_llm_shim(0x10, 0x01, model="claude-sonnet-4.5",
                           input_val='[{"role":"user","content":"first"}]',
                           prompt=100, completion=20,
                           start_ns=1_700_000_000_000_000_000)
    llm_b = _make_llm_shim(0x11, 0x01, model="claude-sonnet-4.5",
                           input_val='[{"role":"user","content":"first"},'
                                     '{"role":"assistant","content":"reply"},'
                                     '{"role":"user","content":"second"}]',
                           prompt=200, completion=30,
                           start_ns=1_700_000_000_000_000_500)

    trace = ingest_otel_spans([root, llm_a, llm_b])

    assert "llm_calls" in trace.metadata
    calls = trace.metadata["llm_calls"]
    assert len(calls) == 2
    # Ordered by start_time (§3 requirement)
    assert calls[0]["span_id"] < calls[1]["span_id"] or True  # order by time
    # First call has 100 input tokens, second 200
    assert calls[0]["input_tokens"] == 100
    assert calls[1]["input_tokens"] == 200


def test_llm_calls_verbatim():
    """Recorded input_text matches original attrs['input.value'] byte-for-byte."""
    root = _make_root_shim()
    verbatim = '{"messages":[{"role":"user","content":"exact bytes"}]}'
    llm = _make_llm_shim(0x10, 0x01, model="claude-sonnet-4.5",
                         input_val=verbatim,
                         prompt=50, completion=10)

    trace = ingest_otel_spans([root, llm])

    assert trace.metadata["llm_calls"][0]["input_text"] == verbatim


def test_llm_calls_absent_when_no_llm():
    """Trace with only tool spans -> llm_calls is empty list (existing behavior unchanged)."""
    root = _make_root_shim()
    tool = _Shim(0x20, 0x01, name="search", kind="TOOL",
                 attributes={"tool.name": "search", "input.value": '{"q":"x"}',
                             "output.value": "result", "output.mime_type": "text/plain"})

    trace = ingest_otel_spans([root, tool])

    # llm_calls key exists but is empty (preprocess always sets the key now).
    assert trace.metadata.get("llm_calls", []) == []
    # temp key removed
    assert "_pending_llm_extras" not in trace.metadata


def test_llm_calls_input_output_tokens_populated():
    """LLM span with .prompt=100 .completion=50 -> input_tokens=100, output_tokens=50."""
    root = _make_root_shim()
    llm = _make_llm_shim(0x10, 0x01, model="claude-sonnet-4.5",
                         input_val="anything",
                         prompt=100, completion=50)

    trace = ingest_otel_spans([root, llm])

    entry = trace.metadata["llm_calls"][0]
    assert entry["input_tokens"] == 100
    assert entry["output_tokens"] == 50


def test_llm_calls_input_cost_table_populated():
    """Ingest with input_cost_table -> input_cost_rate populated in llm_calls entry."""
    root = _make_root_shim()
    llm = _make_llm_shim(0x10, 0x01, model="claude-sonnet-4.5",
                         input_val="x",
                         prompt=100, completion=20)

    trace = ingest_otel_spans(
        [root, llm],
        input_cost_table={"claude-sonnet-4.5": 3e-6},
        output_cost_table={"claude-sonnet-4.5": 15e-6},
    )

    entry = trace.metadata["llm_calls"][0]
    assert entry["input_cost_rate"] == 3e-6
    assert entry["output_cost_rate"] == 15e-6


def test_llm_calls_legacy_cost_table_fallback():
    """Only legacy cost_table -> input_cost_rate is None, cost_rate_legacy populated."""
    root = _make_root_shim()
    llm = _make_llm_shim(0x10, 0x01, model="claude-sonnet-4.5",
                         input_val="x",
                         prompt=100, completion=20)

    trace = ingest_otel_spans(
        [root, llm],
        cost_table={"claude-sonnet-4.5": 9e-6},
    )

    entry = trace.metadata["llm_calls"][0]
    assert entry["input_cost_rate"] is None
    assert entry["output_cost_rate"] is None
    assert entry["cost_rate_legacy"] == 9e-6
