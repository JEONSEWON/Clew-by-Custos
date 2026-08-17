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

import json
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


def _agent_or_node_id_of(
    span_kind: SpanKind, span_name: str, attrs: dict[str, Any]
) -> str:
    """OpenInference span → Boxdawn agent_or_node_id (§4.2 of prereg).

    Priority per span_kind:
      tool   → attrs["tool.name"] → span_name → "anonymous"
      agent  → attrs["graph.node.id"] → span_name → "anonymous"
      llm    → span_name → "anonymous"   (unchanged)
      chain  → span_name → "anonymous"   (unchanged)
    """
    if span_kind == "tool":
        v = attrs.get("tool.name")
        if isinstance(v, str) and v:
            return v
    elif span_kind == "agent":
        v = attrs.get("graph.node.id")
        if isinstance(v, str) and v:
            return v
    return span_name or "anonymous"


def _extract_tool_output(attrs: dict[str, Any]) -> str:
    """OpenInference TOOL span → output.value with envelope unwrap (§4.3 of prereg).

    Observed schemas:
      LangChain: mime "application/json", value = {"type":"tool","data":{"content":"<orig>"}}
      CrewAI:    mime "text/plain",       value = "<orig>"

    Failure direction is safe (false negative, not false positive):
      Envelope unwrap failure → raw as-is. Two calls with matching raw still
      hash-equal downstream; two with differing raw still classify as non-waste.
    """
    raw = attrs.get("output.value", "")
    if not isinstance(raw, str):
        return str(raw) if raw is not None else ""
    mime = attrs.get("output.mime_type", "")

    if mime == "text/plain":
        return raw

    if mime == "application/json":
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw
        if (
            isinstance(obj, dict)
            and obj.get("type") == "tool"
            and isinstance(obj.get("data"), dict)
            and "content" in obj["data"]
        ):
            content = obj["data"]["content"]
            return content if isinstance(content, str) else str(content)
        return raw

    return raw


def _token_count_of(attrs: dict[str, Any]) -> int | None:
    v = attrs.get("llm.token_count.total")
    return int(v) if v is not None else None


def _token_count_prompt(attrs: dict[str, Any]) -> int | None:
    """OpenInference `llm.token_count.prompt` (input side). None if absent."""
    v = attrs.get("llm.token_count.prompt")
    return int(v) if v is not None else None


def _token_count_completion(attrs: dict[str, Any]) -> int | None:
    """OpenInference `llm.token_count.completion` (output side). None if absent."""
    v = attrs.get("llm.token_count.completion")
    return int(v) if v is not None else None


def _token_count_cache_read(attrs: dict[str, Any]) -> int | None:
    """OpenInference `llm.token_count.prompt.cache_read` (cache-hit input). None if absent.

    Per Cost Attribution Completion prereg §4: cache-hit tokens are billed at
    the provider's cache_read rate (10% of base on Anthropic; provider-specific
    on OpenAI/Google). Detectors that want tier-accurate cost read this via
    trace.metadata["llm_calls"][i]["input_tokens_cache_read"].
    """
    v = attrs.get("llm.token_count.prompt.cache_read")
    return int(v) if v is not None else None


def _token_count_cache_write(attrs: dict[str, Any]) -> int | None:
    """OpenInference `llm.token_count.prompt.cache_write` (cache-create input). None if absent.

    Anthropic bills 5m cache write at 125% of base, 1h at 200%. This adapter
    does not distinguish 5m vs 1h — the detector picks the 5m rate by default
    per prereg §4 (5m is Anthropic's default TTL when unspecified).
    """
    v = attrs.get("llm.token_count.prompt.cache_write")
    return int(v) if v is not None else None


def _model_of(attrs: dict[str, Any]) -> str | None:
    v = attrs.get("llm.model_name") or attrs.get("llm.provider")
    return str(v) if v is not None else None


def otel_spans_to_trace(
    spans: Sequence["ReadableSpan"],
    *,
    cost_table: dict[str, float] | None = None,
    input_cost_table: dict[str, float] | None = None,
    output_cost_table: dict[str, float] | None = None,
    source_tag: str = "otel_adapter",
) -> Trace:
    """OTel ReadableSpan list -> canonical `Trace`.

    Empty ``output.value`` on non-tool spans is now allowed through — the
    adapter no longer refuses such spans (R2 relaxation Part 2 prereg in
    this repo). Tool spans with empty output are still rejected downstream
    by ``Span``'s validator (Part 1: cascade sha256 gate constraint). The
    cascade layer handles empty non-tool output by skipping the pair
    before cosine (Part 1).

    Raises:
        ValueError: spans empty / multiple trace_ids / multiple roots.
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
    # Context Resend Detector prereg §3: capture LLM input/token/rate at ingest
    # time, keyed by span_id. Consumed by preprocess (collapse_llm_spans) to build
    # the final trace.metadata["llm_calls"] list before LLM spans are removed.
    llm_extras: dict[str, dict[str, Any]] = {}

    for s in spans:
        attrs: dict[str, Any] = dict(s.attributes or {})
        span_kind = _kind_of(attrs)
        span_name = s.name or "anonymous"

        if span_kind == "tool":
            output_text = _extract_tool_output(attrs)
        else:
            output_text = _coerce_text(attrs.get("output.value"))

        model = _model_of(attrs)
        cost_rate: float | None = None
        if cost_table and model and model in cost_table:
            cost_rate = float(cost_table[model])

        span_id_hex = _hex_span(s.context.span_id)

        if span_kind == "llm":
            input_cost_rate: float | None = None
            if input_cost_table and model and model in input_cost_table:
                input_cost_rate = float(input_cost_table[model])
            output_cost_rate: float | None = None
            if output_cost_table and model and model in output_cost_table:
                output_cost_rate = float(output_cost_table[model])
            llm_extras[span_id_hex] = {
                "input_tokens": _token_count_prompt(attrs),
                "output_tokens": _token_count_completion(attrs),
                # Cost Attribution Completion prereg §4 — tier-split fields.
                # Absent when the instrumentor did not emit cache breakdown.
                "input_tokens_cache_read": _token_count_cache_read(attrs),
                "input_tokens_cache_write": _token_count_cache_write(attrs),
                "input_cost_rate": input_cost_rate,
                "output_cost_rate": output_cost_rate,
            }

        converted.append(
            Span(
                trace_id=trace_id_hex,
                span_id=span_id_hex,
                parent_span_id=(
                    _hex_span(s.parent.span_id) if s.parent is not None else None
                ),
                agent_or_node_id=_agent_or_node_id_of(span_kind, span_name, attrs),
                span_kind=span_kind,
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

    metadata: dict[str, Any] = {"source": source_tag, "schema_version": "1.0"}
    if llm_extras:
        metadata["_pending_llm_extras"] = llm_extras

    return Trace(
        trace_id=trace_id_hex,
        spans=converted,
        metadata=metadata,
    )


def ingest_otel_spans(
    spans: Sequence["ReadableSpan"],
    *,
    cost_table: dict[str, float] | None = None,
    input_cost_table: dict[str, float] | None = None,
    output_cost_table: dict[str, float] | None = None,
    source_tag: str = "otel_adapter",
) -> Trace:
    """Official ingest path = otel_spans_to_trace() + preprocess_trace().

    Production/field use must go through this function.
    otel_spans_to_trace() is for raw conversion only (testing/debugging).

    `input_cost_table` / `output_cost_table` (Context Resend Detector prereg §4):
    per-model $/token rates for input and output sides separately. When
    provided, LLM call cost rates are populated per side in
    trace.metadata["llm_calls"]. When only the legacy `cost_table` is provided,
    the fallback path is used and the detector flags results as "estimated".
    """
    return preprocess_trace(
        otel_spans_to_trace(
            spans,
            cost_table=cost_table,
            input_cost_table=input_cost_table,
            output_cost_table=output_cost_table,
            source_tag=source_tag,
        )
    )
