"""LangGraph 어댑터 — OpenInference/OTel 스팬 → 정규 Trace.

`openinference-instrumentation-langchain`으로 계측된 LangGraph 실행이 내보내는 OTel
스팬을 받아 `clew.model.Trace`로 변환한다. (1단계 — plan §2)

설계 결정:
- 단일 trace_id 강제 (다중이 섞이면 ValueError).
- 단일 루트 강제 (다중 루트는 instrumentation misconfiguration — placeholder
  output_text 잡음을 피하려고 합성 루트를 만들지 않는다).
- cost_rate는 외부 주입 `cost_table`에서 lookup (OTel 표준 외 영역, 트레이스 본문
  오염 방지).
- span_kind 매핑: LLM→llm, TOOL→tool, CHAIN/RUNNABLE→chain, AGENT→agent, 그 외→chain.
- output_text가 비면 어댑터 단계에서 명시적 ValueError (정규 모델 validator보다 친절).
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
    source_tag: str = "langgraph_adapter",
) -> Trace:
    """OTel ReadableSpan 리스트 → 정규 `Trace`.

    Raises:
        ValueError: spans 비어있음 / 다중 trace_id / 다중 루트 / 비어있는 output.value.
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
    source_tag: str = "langgraph_adapter",
) -> Trace:
    """공식 인제스트 경로 = otel_spans_to_trace() + preprocess_trace().

    프로덕션/필드 사용은 반드시 이 함수를 쓴다.
    otel_spans_to_trace()는 raw 변환 전용(테스트·디버깅).
    """
    return preprocess_trace(
        otel_spans_to_trace(spans, cost_table=cost_table, source_tag=source_tag)
    )
