"""repeat_node 패턴.

구조: root → start → analyze ×N → finalize (N=3)
positive: analyze N회 출력이 서로 거의 동일 (단어만 약간 다름) → 낭비.
clean   : analyze N회 매 회 실제 진전.

토폴로지(노드 시퀀스·span_kind·parent edge)는 positive/clean 동일.
낭비 라벨: positive의 2회차 이후 analyze.
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
    # 의미는 같고 표면(어순·어휘·구두점)만 다른 3개 패러프레이즈 —
    # LLM이 같은 분석을 다시 했을 때 실제로 나오는 near-duplicate.
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
