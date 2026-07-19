"""regen_handoff pattern.

Structure: root → start → A(llm) → B(llm) → finalize
positive: B semantically re-generates A's summary → waste.
clean   : B adds new information (next-step decision) on top of A's summary.

Topology is identical between positive and clean.
Waste label: B in the positive trace.
"""

from __future__ import annotations

from clew.model import Trace

from .base import GeneratedTrace, make_context, make_trace, span

PATTERN = "regen_handoff"


def _topology(ctx, a_out: str, b_out: str) -> tuple[Trace, str, str]:
    root_id = ctx.next_span_id()
    start_id = ctx.next_span_id()
    a_id = ctx.next_span_id()
    b_id = ctx.next_span_id()
    finalize_id = ctx.next_span_id()

    spans = [
        span(
            ctx=ctx,
            span_id=root_id,
            parent_id=None,
            agent_or_node_id="run",
            span_kind="chain",
            start_sec=0,
            duration_sec=12,
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
            span_id=a_id,
            parent_id=root_id,
            agent_or_node_id="A",
            span_kind="llm",
            start_sec=3,
            output_text=a_out,
        ),
        span(
            ctx=ctx,
            span_id=b_id,
            parent_id=root_id,
            agent_or_node_id="B",
            span_kind="llm",
            start_sec=6,
            output_text=b_out,
        ),
        span(
            ctx=ctx,
            span_id=finalize_id,
            parent_id=root_id,
            agent_or_node_id="finalize",
            span_kind="chain",
            start_sec=10,
            output_text="report ready",
        ),
    ]
    return make_trace(ctx, spans), a_id, b_id


def make_positive(*, trace_id: str, seed: int) -> GeneratedTrace:
    ctx = make_context(seed=seed, trace_id=trace_id)
    # B re-generates A's summary — same meaning, different surface form
    # (the real-world LLM re-generation pattern).
    a_out = "요약: 3분기 매출은 전분기 대비 12% 증가, 신규 가입자 8.4만 명."
    b_out = "정리: 3분기 매출 +12% (전분기 대비), 가입자 84,000명 증가."
    trace, a_id, b_id = _topology(ctx, a_out, b_out)
    return GeneratedTrace(
        trace=trace,
        waste_span_ids=[b_id],
        pattern=PATTERN,
        class_="positive",
        near_duplicate_of={b_id: a_id},
    )


def make_clean(*, trace_id: str, seed: int) -> GeneratedTrace:
    ctx = make_context(seed=seed, trace_id=trace_id)
    a_out = "요약: 3분기 매출은 전분기 대비 12% 증가, 신규 가입자 8.4만 명."
    b_out = (
        "권고: 매출 성장 견인을 위해 4분기 마케팅 예산을 18% 상향, 가입자 retention "
        "프로그램 신규 도입 — 예상 ROI 1.6배."
    )
    trace, _, _ = _topology(ctx, a_out, b_out)
    return GeneratedTrace(
        trace=trace, waste_span_ids=[], pattern=PATTERN, class_="negative"
    )
