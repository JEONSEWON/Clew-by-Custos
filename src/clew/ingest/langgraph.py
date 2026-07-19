"""OTel/OpenInference span adapter - ReadableSpan list -> canonical Trace.

Takes the OTel ReadableSpan list emitted by apps instrumented with
`openinference-instrumentation-*` (LangGraph included) and converts to `clew.model.Trace`. (Stage 1 - plan §2)

LangGraph is one example of a supported framework. Accepts spans from any
framework using OpenInference instrumentation (CrewAI, AutoGen, LlamaIndex, etc.).

Design decisions:
- Single trace_id enforced (ValueError if multiple mixed in).
- Single root enforced (multi-root is instrumentation misconfiguration -
  do not synthesize a root to avoid placeholder output_text noise).
- cost_rate is looked up from externally-injected `cost_table` (outside OTel standard,
  avoids polluting the trace body).
- span_kind mapping: LLM->llm, TOOL->tool, CHAIN/RUNNABLE->chain, AGENT->agent, others->chain.
- If output_text is empty, the adapter raises an explicit ValueError (friendlier than the canonical model validator).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from clew.ingest.preprocess import preprocess_trace
from clew.model import Span, SpanKind, Trace

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import ReadableSpan


_KIND_MAP: dict[str, SpanKind] = {
    "LLM": "llm",
    "TOOL": "tool",
    "CHAIN": "chain",
    "RUNNABLE": "chain",
    "AGENT": "agent",
}


def _hex_trace(int_id: int) -> str:
    return f"{int_id:032x}"


def _hex_span(int_id: int) -> str:
    return f"{int_id:016x}"


def _ns_to_utc(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _kind_of(attrs: dict[str, Any]) -> SpanKind:
    raw = attrs.get("openinference.span.kind")
    if isinstance(raw, str) and raw in _KIND_MAP:
        return _KIND_MAP[raw]
    return "chain"


def _token_count_of(attrs: dict[str, Any]) -> int | None:
    v = attrs.get("llm.token_count.total")
    return int(v) if v is not None else None


def _model_of(attrs: dict[str, Any]) -> str | None:
    v = attrs.get("llm.model_name") or attrs.get("llm.provider")
    return str(v) if v is not None else None


def otel_spans_to_trace(
    spans: Sequence["ReadableSpan"],
    *,
    cost_table: dict[str, float] | None = None,
    source_tag: str = "otel_adapter",
) -> Trace:
    """OTel ReadableSpan list -> canonical `Trace`.

    Raises:
        ValueError: spans empty / multiple trace_ids / multiple roots / empty output.value.
    """
    if not spans:
        raise ValueError("no spans provided to adapter")

    trace_id_ints = {s.context.trace_id for s in spans}
    if len(trace_id_ints) != 1:
        raise ValueError(
            f"adapter expects single trace_id, got {len(trace_id_ints)}"
        )
    trace_id_hex = _hex_trace(next(iter(trace_id_ints)))

    converted: list[Span] = []
    for s in spans:
        attrs: dict[str, Any] = dict(s.attributes or {})
        output_text = _coerce_text(attrs.get("output.value"))
        if not output_text.strip():
            raise ValueError(
                f"span {s.name!r} (span_id={_hex_span(s.context.span_id)}) has empty "
                "output.value — adapter refuses to construct invalid Span"
            )

        model = _model_of(attrs)
        cost_rate: float | None = None
        if cost_table and model and model in cost_table:
            cost_rate = float(cost_table[model])

        converted.append(
            Span(
                trace_id=trace_id_hex,
                span_id=_hex_span(s.context.span_id),
                parent_span_id=(
                    _hex_span(s.parent.span_id) if s.parent is not None else None
                ),
                agent_or_node_id=s.name or "anonymous",
                span_kind=_kind_of(attrs),
                start_time=_ns_to_utc(s.start_time),
                end_time=_ns_to_utc(s.end_time),
                input_text=_coerce_text(attrs.get("input.value")),
                output_text=output_text,
                token_count=_token_count_of(attrs),
                model=model,
                cost_rate=cost_rate,
            )
        )

    roots = [s for s in converted if s.parent_span_id is None]
    if len(roots) != 1:
        raise ValueError(
            f"adapter expects exactly one root span, got {len(roots)} — multi-root "
            "traces indicate instrumentation misconfiguration; fix upstream rather "
            "than synthesizing a root"
        )

    return Trace(
        trace_id=trace_id_hex,
        spans=converted,
        metadata={"source": source_tag, "schema_version": "1.0"},
    )


def ingest_otel_spans(
    spans: Sequence["ReadableSpan"],
    *,
    cost_table: dict[str, float] | None = None,
    source_tag: str = "otel_adapter",
) -> Trace:
    """Official ingest path = otel_spans_to_trace() + preprocess_trace().

    Production/field use must go through this function.
    otel_spans_to_trace() is for raw conversion only (testing/debugging).
    """
    return preprocess_trace(
        otel_spans_to_trace(spans, cost_table=cost_table, source_tag=source_tag)
    )
