"""tests/test_roundtrip.py — JSON 직렬화/역직렬화 라운드트립 동치 검증."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from clew.model import Span, Trace

UTC = timezone.utc
T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def _span(span_id: str, parent: str | None, offset: int, **kw) -> Span:
    return Span(
        trace_id=kw.pop("trace_id", "t-1"),
        span_id=span_id,
        parent_span_id=parent,
        agent_or_node_id=kw.pop("agent_or_node_id", span_id),
        span_kind=kw.pop("span_kind", "chain"),
        start_time=T0 + timedelta(seconds=offset),
        end_time=T0 + timedelta(seconds=offset + 1),
        input_text=kw.pop("input_text", ""),
        output_text=kw.pop("output_text", f"out-{span_id}"),
        token_count=kw.pop("token_count", None),
        model=kw.pop("model", None),
        cost_rate=kw.pop("cost_rate", None),
    )


def _assert_roundtrip(trace: Trace) -> None:
    raw = trace.model_dump_json()
    restored = Trace.model_validate_json(raw)
    assert restored == trace
    assert restored.model_dump_json() == raw  # 멱등


def test_roundtrip_minimal_trace():
    trace = Trace(trace_id="t-1", spans=[_span("s-0", None, 0)])
    _assert_roundtrip(trace)


def test_roundtrip_typical_trace():
    spans = [
        _span("s-0", None, 0, span_kind="chain"),
        _span("s-1", "s-0", 1, span_kind="llm", token_count=42, model="m"),
        _span("s-2", "s-0", 2, span_kind="tool"),
        _span("s-3", "s-1", 3, span_kind="agent"),
        _span("s-4", "s-1", 4, span_kind="llm"),
    ]
    trace = Trace(trace_id="t-1", spans=spans, metadata={"source": "test"})
    _assert_roundtrip(trace)


def test_roundtrip_unicode_output_text():
    trace = Trace(
        trace_id="t-한글-🧵",
        spans=[
            _span(
                "s-0",
                None,
                0,
                trace_id="t-한글-🧵",
                input_text="안녕하세요 — 입력",
                output_text="요약: 길을 찾는 실타래 🧶",
            )
        ],
    )
    _assert_roundtrip(trace)


def test_roundtrip_optional_fields_none():
    trace = Trace(trace_id="t-1", spans=[_span("s-0", None, 0)])
    restored = Trace.model_validate_json(trace.model_dump_json())
    s = restored.spans[0]
    assert s.token_count is None
    assert s.model is None
    assert s.cost_rate is None


def test_roundtrip_optional_fields_populated():
    spans = [
        _span("s-0", None, 0, token_count=12, model="claude", cost_rate=1.5e-6),
    ]
    trace = Trace(trace_id="t-1", spans=spans)
    restored = Trace.model_validate_json(trace.model_dump_json())
    s = restored.spans[0]
    assert s.token_count == 12
    assert s.model == "claude"
    assert s.cost_rate == 1.5e-6


def test_roundtrip_idempotent_twice():
    trace = Trace(
        trace_id="t-1",
        spans=[
            _span("s-0", None, 0),
            _span("s-1", "s-0", 1, span_kind="llm"),
        ],
    )
    raw1 = trace.model_dump_json()
    raw2 = Trace.model_validate_json(raw1).model_dump_json()
    raw3 = Trace.model_validate_json(raw2).model_dump_json()
    assert raw1 == raw2 == raw3


def test_timestamps_serialized_as_iso_utc():
    trace = Trace(trace_id="t-1", spans=[_span("s-0", None, 0)])
    raw = trace.model_dump_json()
    payload = json.loads(raw)
    ts = payload["spans"][0]["start_time"]
    assert "T" in ts
    assert ts.endswith("Z") or "+00:00" in ts


def test_metadata_roundtrips():
    trace = Trace(
        trace_id="t-1",
        spans=[_span("s-0", None, 0)],
        metadata={"source": "langgraph_adapter", "schema_version": "1.0", "nested": {"k": [1, 2]}},
    )
    _assert_roundtrip(trace)
