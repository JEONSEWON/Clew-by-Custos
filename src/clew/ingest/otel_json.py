"""src/clew/ingest/otel_json.py — OTel SDK span.to_json() 배열 파일 → Trace.

지원 형식 (Format A):
  OTel SDK InMemorySpanExporter → span.to_json() 직렬화 결과 배열.
  최상위: list, 각 원소에 "context" 키.

  생성 방법:
    import json; from pathlib import Path
    spans = exporter.get_finished_spans()
    Path("trace.json").write_text(
        json.dumps([json.loads(s.to_json()) for s in spans])
    )

미지원 형식:
  - OTLP proto-JSON ("resource_spans" 키): 명확한 ValueError 반환.

기존 otel_spans_to_trace / ingest_otel_spans 시그니처·동작 불변.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clew.ingest.langgraph import ingest_otel_spans
from clew.model import Trace


class _Ctx:
    __slots__ = ("trace_id", "span_id")

    def __init__(self, trace_id: int, span_id: int) -> None:
        self.trace_id = trace_id
        self.span_id = span_id


class _Parent:
    __slots__ = ("span_id",)

    def __init__(self, span_id: int) -> None:
        self.span_id = span_id


def _iso_to_ns(ts: str) -> int:
    """ISO datetime string → 나노초 int (ReadableSpan.start_time 호환)."""
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return int(dt.timestamp() * 1e9)


class _SdkJsonSpan:
    """span.to_json() dict를 ReadableSpan 인터페이스로 감싸는 경량 shim.

    otel_spans_to_trace()가 접근하는 필드만 구현:
      .context.trace_id / .context.span_id (int)
      .parent  (.span_id int) or None
      .name (str)
      .start_time / .end_time (int nanoseconds)
      .attributes (dict or None)
    """

    __slots__ = ("context", "parent", "name", "start_time", "end_time", "attributes")

    def __init__(self, raw: dict[str, Any]) -> None:
        ctx = raw["context"]
        self.context = _Ctx(
            trace_id=int(ctx["trace_id"], 16),
            span_id=int(ctx["span_id"], 16),
        )
        parent_hex: str | None = raw.get("parent_id")
        self.parent = _Parent(int(parent_hex, 16)) if parent_hex else None
        self.name: str = raw.get("name") or "anonymous"
        self.start_time: int = _iso_to_ns(raw["start_time"])
        self.end_time: int = _iso_to_ns(raw["end_time"])
        self.attributes: dict[str, Any] = raw.get("attributes") or {}


def _parse_sdk_json(text: str) -> list[_SdkJsonSpan]:
    """Format A JSON text → _SdkJsonSpan 리스트."""
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 파싱 실패: {exc}") from exc

    if isinstance(obj, dict):
        if "resource_spans" in obj or "resourceSpans" in obj:
            raise ValueError(
                "OTLP proto-JSON 형식(resource_spans/resourceSpans 키)은 아직 미지원입니다.\n"
                "Format A(OTel SDK JSON 배열)로 변환 후 재시도하세요:\n"
                "  import json; from pathlib import Path\n"
                "  spans = exporter.get_finished_spans()\n"
                "  Path('trace.json').write_text(\n"
                "      json.dumps([json.loads(s.to_json()) for s in spans])\n"
                "  )"
            )
        raise ValueError(
            f"OTel SDK JSON은 스팬 배열(list)이어야 합니다. "
            f"최상위 키: {list(obj.keys())[:5]}"
        )

    if not isinstance(obj, list):
        raise ValueError(
            f"OTel SDK JSON은 스팬 배열(list)이어야 합니다. "
            f"실제 타입: {type(obj).__name__}"
        )

    return [_SdkJsonSpan(s) for s in obj]


def ingest_from_otel_json(
    path: Path,
    *,
    cost_table: dict[str, float] | None = None,
) -> Trace:
    """OTel SDK span.to_json() 배열 파일(Format A) → 정규 Trace.

    내부적으로 ingest_otel_spans()를 호출해 preprocess_trace가 정확히 1회 실행됨.

    Args:
        path: Format A JSON 파일 경로.
        cost_table: 모델명 → 토큰당 비용 (optional).

    Raises:
        ValueError: 빈 파일, 형식 오류, output.value 없는 스팬.
    """
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"{path}: 빈 파일")

    shims = _parse_sdk_json(text)
    return ingest_otel_spans(shims, cost_table=cost_table, source_tag="otel_json")
