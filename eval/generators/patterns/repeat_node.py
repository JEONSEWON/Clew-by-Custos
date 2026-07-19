"""repeat_node pattern.

Structure: root → start → analyze × N → finalize (N=3)
positive: the N analyze outputs are near-identical (only wording differs) → waste.
clean   : each of the N analyze steps makes real progress.

Topology (node sequence, span_kind, parent edge) is identical between
positive and clean.
Waste label: analyze occurrences #2 and later in the positive trace.
"""

from __future__ import annotations

from clew.model import Trace

from .base import GeneratedTrace, make_context, make_trace, span

PATTERN = "repeat_node"
N_REPEATS = 3


def _topology(ctx, outputs: list[str]) -> tuple[Trace, list[str]]:
    root_id = ctx.next_span_id()
    start_id = ctx.next_span_id()
    analyze_ids = [ctx.next_span_id() for _ in range(len(outputs))]
    finalize_id = ctx.next_span_id()
    total_sec = 2 * (len(outputs) + 2)

    spans = [
        span(
            ctx=ctx,
            span_id=root_id,
            parent_id=None,
            agent_or_node_id="run",
            span_kind="chain",
            start_sec=0,
            duration_sec=total_sec,
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
    ]
    for i, (sid, out) in enumerate(zip(analyze_ids, outputs)):
        spans.append(
            span(
                ctx=ctx,
                span_id=sid,
                parent_id=root_id,
                agent_or_node_id="analyze",
                span_kind="llm",
                start_sec=2 + i * 2,
                output_text=out,
            )
        )
    spans.append(
        span(
            ctx=ctx,
            span_id=finalize_id,
            parent_id=root_id,
            agent_or_node_id="finalize",
            span_kind="chain",
            start_sec=2 + len(outputs) * 2,
            output_text="report ready",
        )
    )
    return make_trace(ctx, spans), analyze_ids


def make_positive(*, trace_id: str, seed: int) -> GeneratedTrace:
    ctx = make_context(seed=seed, trace_id=trace_id)
    # Three paraphrases with the same meaning but different surface form
    # (word order, vocabulary, punctuation) — the near-duplicates you
    # actually see when an LLM redoes the same analysis.
    outputs = [
        "분석 결과: 핵심 요인은 A, B, C가 관측됨",
        "분석: 핵심 요인 A·B·C가 관찰됨",
        "재확인: 주요 요인은 여전히 A, B, C로 동일",
    ][:N_REPEATS]
    trace, analyze_ids = _topology(ctx, outputs)
    waste = analyze_ids[1:]
    origin = analyze_ids[0]
    near_dup = {wid: origin for wid in waste}
    return GeneratedTrace(
        trace=trace,
        waste_span_ids=waste,
        pattern=PATTERN,
        class_="positive",
        near_duplicate_of=near_dup,
    )


def make_clean(*, trace_id: str, seed: int) -> GeneratedTrace:
    ctx = make_context(seed=seed, trace_id=trace_id)
    outputs = [
        "1차: 데이터 5개 source 수집 완료",
        "2차: 상승 추세 식별, 변동성 0.18",
        "3차: 인과 가설 — A의 변화가 B를 0.7 강도로 견인",
    ][:N_REPEATS]
    trace, _ = _topology(ctx, outputs)
    return GeneratedTrace(
        trace=trace, waste_span_ids=[], pattern=PATTERN, class_="negative"
    )
