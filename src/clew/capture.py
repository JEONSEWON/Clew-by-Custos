"""src/clew/capture.py — OTel 캡처 → Trace 저장 헬퍼.

OpenInference 계측 LangGraph 앱에서:
  InMemorySpanExporter → ingest_otel_spans → (선택) trace.json 저장.

사용 예:
    from clew.capture import capture_to_file
    trace = capture_to_file(app, {"topic": "..."}, Path("trace.json"))
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from clew.ingest.langgraph import ingest_otel_spans
from clew.io import save_trace
from clew.model import Trace

if TYPE_CHECKING:
    pass


def capture_to_file(
    app: Any,
    inputs: dict[str, Any],
    out_path: Path,
    *,
    cost_table: dict[str, float] | None = None,
) -> Trace:
    """LangGraph 앱 실행 → ingest_otel_spans → trace.json 저장.

    OTel 계측(LangChainInstrumentor)은 호출자가 이미 설정했거나,
    이 함수가 임시 계측을 설정·해제한다.

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
