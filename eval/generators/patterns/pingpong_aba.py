"""pingpong_aba 패턴.

구조: root → start → A → B → A → B → finalize (A·B 각 2회씩 핑퐁)
positive: 2회차 A,B가 1회차의 작업/결론을 반복.
clean   : A·B의 매 방문이 의미적 진전(다음 라운드는 이전 결과 위에 쌓임).

토폴로지는 positive/clean 동일.
낭비 라벨: positive의 2회차 A, 2회차 B.
"""

from __future__ import annotations

from clew.model import Trace

from .base import GeneratedTrace, make_context, make_trace, span

PATTERN = "pingpong_aba"


def _topology(ctx, outs: dict[str, str]) -> tuple[Trace, dict[str, str]]:
    root_id = ctx.next_span_id()
    start_id = ctx.next_span_id()
    a1_id = ctx.next_span_id()
    b1_id = ctx.next_span_id()
    a2_id = ctx.next_span_id()
    b2_id = ctx.next_span_id()
    finalize_id = ctx.next_span_id()

    spans = [
        span(
            ctx=ctx,
            span_id=root_id,
            parent_id=None,
            agent_or_node_id="run",
            span_kind="chain",
            start_sec=0,
            duration_sec=16,
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
            span_id=a1_id,
            parent_id=root_id,
            agent_or_node_id="A",
            span_kind="llm",
            start_sec=2,
            output_text=outs["a1"],
        ),
        span(
            ctx=ctx,
            span_id=b1_id,
            parent_id=root_id,
            agent_or_node_id="B",
            span_kind="llm",
            start_sec=5,
            output_text=outs["b1"],
        ),
        span(
            ctx=ctx,
            span_id=a2_id,
            parent_id=root_id,
            agent_or_node_id="A",
            span_kind="llm",
            start_sec=8,
            output_text=outs["a2"],
        ),
        span(
            ctx=ctx,
            span_id=b2_id,
            parent_id=root_id,
            agent_or_node_id="B",
            span_kind="llm",
            start_sec=11,
            output_text=outs["b2"],
        ),
        span(
            ctx=ctx,
            span_id=finalize_id,
            parent_id=root_id,
            agent_or_node_id="finalize",
            span_kind="chain",
            start_sec=14,
            output_text="report ready",
        ),
    ]
    # ids 매핑(역할명 → span_id) 반환 — 호출자가 near_duplicate_of 등 구성용.
    ids = {"a1": a1_id, "b1": b1_id, "a2": a2_id, "b2": b2_id}
    return make_trace(ctx, spans), ids


def make_positive(*, trace_id: str, seed: int) -> GeneratedTrace:
    ctx = make_context(seed=seed, trace_id=trace_id)
    # 2회차가 1회차의 같은 결론을 표면만 바꿔 다시 말함 (LLM 재호출의 전형적 형태).
    outs = {
        "a1": "A 제안: 캠페인 X를 4분기 우선 항목으로 추진",
        "b1": "B 응답: 캠페인 X에 동의",
        "a2": "A: X 우선 항목 추진 입장은 그대로",
        "b2": "B: X 동의 입장은 변함없음",
    }
    trace, ids = _topology(ctx, outs)
    waste = [ids["a2"], ids["b2"]]
    near_dup = {ids["a2"]: ids["a1"], ids["b2"]: ids["b1"]}
    return GeneratedTrace(
        trace=trace,
        waste_span_ids=waste,
        pattern=PATTERN,
        class_="positive",
        near_duplicate_of=near_dup,
    )


def make_clean(*, trace_id: str, seed: int) -> GeneratedTrace:
    ctx = make_context(seed=seed, trace_id=trace_id)
    outs = {
        "a1": "A 제안: 캠페인 X 우선, 예산 1억",
        "b1": "B 반응: X 동의하되 예산은 8천만으로 축소 제안",
        "a2": "A 수정: 8천만 수락, 대신 기간 6주로 연장",
        "b2": "B 합의: 8천만·6주·KPI 클릭률 1.4% 목표로 확정",
    }
    trace, _ = _topology(ctx, outs)
    return GeneratedTrace(
        trace=trace, waste_span_ids=[], pattern=PATTERN, class_="negative"
    )
