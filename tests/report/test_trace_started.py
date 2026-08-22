"""tests/report/test_trace_started.py — report carries when the trace ran.

Storage-layer consumers bucket time series on the trace's own start time when
present; `analyzed` alone puts a batch of old traces on the day they were
analyzed. Locks the field's presence, its value, and UTC normalisation.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from clew.detect.cascade import CascadeResult
from clew.model import Span, Trace
from clew.report.json_report import render_json


def _span(trace_id: str, span_id: str, parent: str | None, start: datetime) -> Span:
    return Span(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent,
        agent_or_node_id=span_id,
        span_kind="chain" if parent is None else "tool",
        start_time=start,
        end_time=start,
        input_text="",
        output_text="[x]",
    )


def _render(spans: list[Span], trace_id: str = "t1") -> dict:
    trace = Trace(trace_id=trace_id, spans=spans)
    cr = CascadeResult(trace_id=trace_id, wasteful=False)
    return json.loads(render_json(trace, cr, details=[]))


def test_trace_started_is_earliest_span_start() -> None:
    root = datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc)
    spans = [
        _span("t1", "root", None, root),
        _span("t1", "later", "root", root + timedelta(hours=2)),
    ]
    js = _render(spans)

    assert js["trace_started"] == "2026-03-04T05:06:07Z"


def test_trace_started_uses_earliest_even_when_not_the_root() -> None:
    root = datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc)
    spans = [
        _span("t1", "root", None, root),
        _span("t1", "earlier", "root", root - timedelta(minutes=30)),
    ]
    js = _render(spans)

    assert js["trace_started"] == "2026-03-04T04:36:07Z"


def test_trace_started_is_normalised_to_utc() -> None:
    kst = timezone(timedelta(hours=9))
    spans = [_span("t1", "root", None, datetime(2026, 3, 4, 14, 0, 0, tzinfo=kst))]
    js = _render(spans)

    assert js["trace_started"] == "2026-03-04T05:00:00Z"


def test_analyzed_still_present() -> None:
    """Backward compat: the pre-existing analysis timestamp is untouched."""
    spans = [_span("t1", "root", None, datetime(2026, 3, 4, tzinfo=timezone.utc))]
    js = _render(spans)

    assert "analyzed" in js
    assert js["analyzed"].endswith("Z")
    assert js["analyzed"] != js["trace_started"]
