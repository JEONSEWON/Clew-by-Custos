"""패턴 생성기 공통 헬퍼.

전략: positive/clean 트윈은 *동일한 구조 토폴로지*(span_kind/agent_or_node_id/parent-child
시퀀스)를 갖고, **출력 텍스트의 의미적 진전 유무만** 차이를 갖는다. 그래야 구조 단독
탐지기가 패턴을 못 외워 자기기만(v1 재발)이 차단된다.

직접 합성 — 실제 LangGraph 실행이 아니라 정규 Trace 모델로 합성한다. 결정론·정확한
ground-truth·토폴로지 통제를 위해. (어댑터 자체는 단계 4에서 별도 검증됨.)
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from clew.model import Span, SpanKind, Trace

# 라벨 hint 금지 단어. 트레이스 본문에 들어가면 누수 — 테스트로 강제.
FORBIDDEN_HINTS = (
    "waste",
    "duplicate",
    "redundant",
    "loop",
    "positive",
    "negative",
    "control",
    "ground truth",
    "ground_truth",
)

UTC = timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass
class GenContext:
    """결정론적 생성 컨텍스트."""

    rng: random.Random
    trace_id: str
    t0: datetime = T0
    _counter: int = 0

    def next_span_id(self) -> str:
        self._counter += 1
        return f"s-{self._counter:04d}"

    def at(self, sec: int) -> datetime:
        return self.t0 + timedelta(seconds=sec)


@dataclass
class GeneratedTrace:
    trace: Trace
    waste_span_ids: list[str]
    pattern: str
    class_: Literal["positive", "negative"]
    # 낭비-라벨된 스팬 → 그 스팬의 *의미적 원본* 스팬 (현실성 가드 입력).
    # 예: repeat_node의 2회차 analyze는 1회차 analyze가 원본.
    # 비어있는 경우 가드 면제(requery_known은 byte-identical 재조회가 정상 신호).
    near_duplicate_of: dict[str, str] = field(default_factory=dict)


def make_context(*, seed: int, trace_id: str) -> GenContext:
    return GenContext(rng=random.Random(seed), trace_id=trace_id)


def span(
    *,
    ctx: GenContext,
    span_id: str,
    parent_id: str | None,
    agent_or_node_id: str,
    span_kind: SpanKind,
    start_sec: int,
    duration_sec: int = 1,
    input_text: str = "",
    output_text: str,
    token_count: int = 10,
    model: str = "fake-model",
    cost_rate: float = 1.0e-6,
) -> Span:
    return Span(
        trace_id=ctx.trace_id,
        span_id=span_id,
        parent_span_id=parent_id,
        agent_or_node_id=agent_or_node_id,
        span_kind=span_kind,
        start_time=ctx.at(start_sec),
        end_time=ctx.at(start_sec + duration_sec),
        input_text=input_text,
        output_text=output_text,
        token_count=token_count,
        model=model,
        cost_rate=cost_rate,
    )


def make_trace(ctx: GenContext, spans: list[Span]) -> Trace:
    """트레이스 본문에 패턴/라벨 hint 정보를 절대 넣지 않는다."""
    return Trace(
        trace_id=ctx.trace_id,
        spans=spans,
        metadata={"schema_version": "1.0", "source": "synthetic_generator"},
    )


def topology_signature(trace: Trace) -> list[tuple[str, str, str]]:
    """트레이스의 구조 토폴로지 시그니처.

    start_time 정렬 후, 각 스팬을 (agent_or_node_id, span_kind, parent_agent_or_node_id)
    튜플로 표현. positive와 clean 트윈이 *정확히 같은 시그니처*를 가져야 한다.
    """
    by_id = {s.span_id: s for s in trace.spans}
    ordered = sorted(trace.spans, key=lambda s: s.start_time)
    sig: list[tuple[str, str, str]] = []
    for s in ordered:
        parent_aid = by_id[s.parent_span_id].agent_or_node_id if s.parent_span_id else "<root>"
        sig.append((s.agent_or_node_id, s.span_kind, parent_aid))
    return sig
