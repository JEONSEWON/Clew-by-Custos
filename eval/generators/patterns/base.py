"""Common helpers for pattern generators.

Strategy: positive/clean twins share an *identical structural topology*
(span_kind / agent_or_node_id / parent-child sequence) and differ **only**
in whether the output text carries semantic progression. That way a
structural-only detector cannot memorize the pattern — the v1
self-deception failure mode is blocked.

Direct synthesis — we build canonical Trace models rather than actually
running LangGraph. For determinism, exact ground-truth, and topology
control. (The adapter itself is validated separately in stage 4.)
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from clew.model import Span, SpanKind, Trace

# Forbidden label-hint words. If any appears in a trace body it's a leak —
# enforced by test.
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
    """Deterministic generation context."""

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
    # Waste-labeled span → its *semantic origin* span (input to the realism guard).
    # e.g. in repeat_node, the 2nd analyze's origin is the 1st analyze.
    # Empty means the guard is skipped (requery_known's byte-identical
    # re-lookup is the normal signal).
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
    """Never put pattern/label-hint info into the trace body."""
    return Trace(
        trace_id=ctx.trace_id,
        spans=spans,
        metadata={"schema_version": "1.0", "source": "synthetic_generator"},
    )


def topology_signature(trace: Trace) -> list[tuple[str, str, str]]:
    """Structural topology signature of a trace.

    After ordering by start_time, each span is represented as a
    (agent_or_node_id, span_kind, parent_agent_or_node_id) tuple. The
    positive and clean twins must have *exactly the same signature*.
    """
    by_id = {s.span_id: s for s in trace.spans}
    ordered = sorted(trace.spans, key=lambda s: s.start_time)
    sig: list[tuple[str, str, str]] = []
    for s in ordered:
        parent_aid = by_id[s.parent_span_id].agent_or_node_id if s.parent_span_id else "<root>"
        sig.append((s.agent_or_node_id, s.span_kind, parent_aid))
    return sig
