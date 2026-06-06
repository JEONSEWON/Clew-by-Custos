"""requery_known 패턴.

구조: root → start → lookup(tool) → process(chain) → lookup(tool) → finalize
positive: 2회차 lookup이 1회차와 동일 키 → 이미 가진 정보를 재조회.
clean   : 2회차 lookup이 다른 키 → 정상적인 2회 조회.

토폴로지는 positive/clean 동일(같은 노드 시퀀스·span_kind).
낭비 라벨: positive의 2회차 lookup.
"""

from __future__ import annotations

from clew.model import Trace

from .base import GeneratedTrace, make_context, make_trace, span

PATTERN = "requery_known"


def _topology(
    ctx,
    *,
    lookup1_input: str,
    lookup1_output: str,
    lookup2_input: str,
    lookup2_output: str,
) -> tuple[Trace, str]:
    root_id = ctx.next_span_id()
    start_id = ctx.next_span_id()
    l1_id = ctx.next_span_id()
    process_id = ctx.next_span_id()
    l2_id = ctx.next_span_id()
    finalize_id = ctx.next_span_id()

    spans = [
        span(
            ctx=ctx,
            span_id=root_id,
            parent_id=None,
            agent_or_node_id="run",
            span_kind="chain",
            start_sec=0,
            duration_sec=14,
            output_text="run complete",
        ),
        span(
            ctx=ctx,
            span_id=start_id,
            parent_id=root_id,
            agent_or_node_id="start",
            span_kind="chain",
            start_sec=1,
            output_text="initialize",
        ),
        span(
            ctx=ctx,
            span_id=l1_id,
            parent_id=root_id,
            agent_or_node_id="lookup",
            span_kind="tool",
            start_sec=2,
            input_text=lookup1_input,
            output_text=lookup1_output,
        ),
        span(
            ctx=ctx,
            span_id=process_id,
            parent_id=root_id,
            agent_or_node_id="process",
            span_kind="chain",
            start_sec=5,
            output_text="processed first result",
        ),
        span(
            ctx=ctx,
            span_id=l2_id,
            parent_id=root_id,
            agent_or_node_id="lookup",
            span_kind="tool",
            start_sec=8,
            input_text=lookup2_input,
            output_text=lookup2_output,
        ),
        span(
            ctx=ctx,
            span_id=finalize_id,
            parent_id=root_id,
            agent_or_node_id="finalize",
            span_kind="chain",
            start_sec=12,
            output_text="report ready",
        ),
    ]
    return make_trace(ctx, spans), l2_id


def make_positive(*, trace_id: str, seed: int) -> GeneratedTrace:
    ctx = make_context(seed=seed, trace_id=trace_id)
    trace, l2_id = _topology(
        ctx,
        lookup1_input="customer_id=12345",
        lookup1_output="name=Alice, plan=Pro, MRR=$59",
        lookup2_input="customer_id=12345",
        lookup2_output="name=Alice, plan=Pro, MRR=$59",
    )
    return GeneratedTrace(
        trace=trace, waste_span_ids=[l2_id], pattern=PATTERN, class_="positive"
    )


def make_clean(*, trace_id: str, seed: int) -> GeneratedTrace:
    ctx = make_context(seed=seed, trace_id=trace_id)
    trace, _ = _topology(
        ctx,
        lookup1_input="customer_id=12345",
        lookup1_output="name=Alice, plan=Pro, MRR=$59",
        lookup2_input="customer_id=67890",
        lookup2_output="name=Bob, plan=Free, MRR=$0",
    )
    return GeneratedTrace(
        trace=trace, waste_span_ids=[], pattern=PATTERN, class_="negative"
    )
