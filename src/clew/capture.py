"""src/clew/capture.py — LangGraph app execution -> OTel capture -> Trace saving helper.

LangGraph-specific path: compiled app.invoke() -> InMemorySpanExporter -> ingest_otel_spans.
The general-purpose path (OTel SDK JSON file -> Trace) does not go through this function.
  -> Use clew.ingest.otel_json.ingest_from_otel_json(path).

Usage example:
    from clew.capture import capture_langgraph
    trace = capture_langgraph(app, {"topic": "..."}, Path("trace.json"))
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from clew.ingest.langgraph import ingest_otel_spans
from clew.io import save_trace
from clew.model import Trace

if TYPE_CHECKING:
    pass


def capture_langgraph(
    app: Any,
    inputs: dict[str, Any],
    out_path: Path,
    *,
    cost_table: dict[str, float] | None = None,
) -> Trace:
    """LangGraph app execution -> ingest_otel_spans -> save trace.json.

    LangGraph-specific. For general-purpose file input use ingest_from_otel_json().

    Args:
        app: compiled LangGraph app (an object that supports app.invoke).
        inputs: input dict to pass to app.invoke().
        out_path: path to save trace.json.
        cost_table: model name -> cost-per-token mapping (optional).

    Returns:
        The saved Trace object.
    """
    try:
        from openinference.instrumentation.langchain import LangChainInstrumentor
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )
    except ImportError as e:
        raise ImportError(
            "capture_to_file requires the 'adapter' extra: "
            "pip install 'boxdawn[adapter]'"
        ) from e

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    instrumentor = LangChainInstrumentor()
    instrumentor.instrument(tracer_provider=provider, skip_dep_check=True)
    try:
        app.invoke(inputs)
        provider.force_flush()
        raw_spans = list(exporter.get_finished_spans())
    finally:
        instrumentor.uninstrument()

    trace = ingest_otel_spans(raw_spans, cost_table=cost_table)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    save_trace(trace, out_path)
    return trace


capture_to_file = capture_langgraph
