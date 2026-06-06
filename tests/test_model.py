"""tests/test_model.py — 정규 스팬 모델 스키마 검증."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from clew.model import Span, Trace

UTC = timezone.utc
T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def _span(
    *,
    trace_id: str = "t-1",
    span_id: str = "s-1",
    parent_span_id: str | None = None,
    agent_or_node_id: str = "root",
    span_kind: str = "chain",
    start: datetime = T0,
    end: datetime | None = None,
    input_text: str = "",
    output_text: str = "ok",
    token_count: int | None = None,
    model: str | None = None,
    cost_rate: float | None = None,
) -> Span:
    return Span(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        agent_or_node_id=agent_or_node_id,
        span_kind=span_kind,  # type: ignore[arg-type]
        start_time=start,
        end_time=end or start + timedelta(seconds=1),
        input_text=input_text,
        output_text=output_text,
        token_count=token_count,
        model=model,
        cost_rate=cost_rate,
    )


def test_output_text_required_non_empty():
    with pytest.raises(ValidationError):
        _span(output_text="")
    with pytest.raises(ValidationError):
        _span(output_text="   \n\t  ")


def test_span_kind_rejects_unknown():
    with pytest.raises(ValidationError):
        _span(span_kind="router")  # type: ignore[arg-type]


def test_naive_datetime_rejected():
    naive = datetime(2026, 1, 1, 0, 0, 0)  # tzinfo=None
    with pytest.raises(ValidationError):
        _span(start=naive, end=naive + timedelta(seconds=1))


def test_end_time_before_start_time_rejected():
    with pytest.raises(ValidationError):
        _span(start=T0, end=T0 - timedelta(seconds=1))


def test_negative_token_count_rejected():
    with pytest.raises(ValidationError):
        _span(token_count=-1)


def test_negative_cost_rate_rejected():
    with pytest.raises(ValidationError):
        _span(cost_rate=-0.001)


def test_extra_field_rejected():
    with pytest.raises(ValidationError):
        Span(  # type: ignore[call-arg]
            trace_id="t-1",
            span_id="s-1",
            parent_span_id=None,
            agent_or_node_id="root",
            span_kind="chain",
            start_time=T0,
            end_time=T0 + timedelta(seconds=1),
            input_text="",
            output_text="ok",
            unknown_field="oops",
        )


def test_trace_id_mismatch_rejected():
    s = _span(trace_id="t-1")
    with pytest.raises(ValidationError):
        Trace(trace_id="t-2", spans=[s])


def test_duplicate_span_id_rejected():
    s1 = _span(span_id="s-1")
    s2 = _span(span_id="s-1", start=T0 + timedelta(seconds=2))
    with pytest.raises(ValidationError):
        Trace(trace_id="t-1", spans=[s1, s2])


def test_orphan_span_rejected():
    root = _span(span_id="s-1")
    orphan = _span(span_id="s-2", parent_span_id="ghost", start=T0 + timedelta(seconds=1))
    with pytest.raises(ValidationError):
        Trace(trace_id="t-1", spans=[root, orphan])


def test_multiple_roots_rejected():
    r1 = _span(span_id="s-1")
    r2 = _span(span_id="s-2", start=T0 + timedelta(seconds=1))
    with pytest.raises(ValidationError):
        Trace(trace_id="t-1", spans=[r1, r2])


def test_no_root_rejected():
    s1 = _span(span_id="s-1", parent_span_id="s-2")
    s2 = _span(span_id="s-2", parent_span_id="s-1", start=T0 + timedelta(seconds=1))
    with pytest.raises(ValidationError):
        Trace(trace_id="t-1", spans=[s1, s2])


def test_cycle_in_parent_chain_rejected():
    root = _span(span_id="s-0")
    a = _span(span_id="s-a", parent_span_id="s-b", start=T0 + timedelta(seconds=1))
    b = _span(span_id="s-b", parent_span_id="s-a", start=T0 + timedelta(seconds=2))
    with pytest.raises(ValidationError):
        Trace(trace_id="t-1", spans=[root, a, b])


def test_empty_spans_rejected():
    with pytest.raises(ValidationError):
        Trace(trace_id="t-1", spans=[])


def test_valid_trace_builds_tree():
    root = _span(span_id="s-0", agent_or_node_id="root")
    c1 = _span(
        span_id="s-1",
        parent_span_id="s-0",
        start=T0 + timedelta(seconds=1),
        agent_or_node_id="A",
    )
    c2 = _span(
        span_id="s-2",
        parent_span_id="s-0",
        start=T0 + timedelta(seconds=2),
        agent_or_node_id="B",
    )
    g1 = _span(
        span_id="s-3",
        parent_span_id="s-1",
        start=T0 + timedelta(seconds=3),
        agent_or_node_id="A.x",
    )

    trace = Trace(trace_id="t-1", spans=[c2, root, g1, c1])  # 순서 섞어서 입력
    tree = trace.build_tree()

    assert tree.span.span_id == "s-0"
    assert [c.span.span_id for c in tree.children] == ["s-1", "s-2"]
    assert [g.span.span_id for g in tree.children[0].children] == ["s-3"]
    assert tree.children[1].children == []


def test_optional_fields_default_to_none():
    s = _span()
    assert s.token_count is None
    assert s.model is None
    assert s.cost_rate is None
