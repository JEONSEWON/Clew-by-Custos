"""src/clew/capture.py — LangGraph 앱 실행 → OTel 캡처 → Trace 저장 헬퍼.

LangGraph 전용 경로: compiled app.invoke() → InMemorySpanExporter → ingest_otel_spans.
범용 경로(OTel SDK JSON 파일 → Trace)는 이 함수를 거치지 않는다.
  → clew.ingest.otel_json.ingest_from_otel_json(path) 사용.

사용 예:
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
    """LangGraph 앱 실행 → ingest_otel_spans → trace.json 저장.

    LangGraph 전용. 범용 파일 입력은 ingest_from_otel_json()을 사용.

    Args:
        app: compiled LangGraph app (app.invoke 가능한 객체).
        inputs: app.invoke()에 전달할 입력 dict.
        out_path: trace.json 저장 경로.
        cost_table: 모델명 → 토큰당 비용 매핑 (optional).

    Returns:
        저장된 Trace 객체.
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
            "pip install 'clew[adapter]'"
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
