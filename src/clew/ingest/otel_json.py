"""src/clew/ingest/otel_json.py — OTel JSON 파일 → Trace.

지원 형식:
  Format A (OTel SDK JSON 배열):
    OTel SDK InMemorySpanExporter → span.to_json() 직렬화 결과 배열.
    최상위: list, 각 원소에 "context" 키.

  Format C (OpenInference nested dict):
    {"trace_id": "hex", "spans": [루트 스팬, child_spans 중첩]}
    PatronusAI/TRAIL, Phoenix/OpenInference exporter 출력 형식.

미지원 형식:
  - OTLP proto-JSON ("resource_spans" 키): 명확한 ValueError 반환.

기존 otel_spans_to_trace / ingest_otel_spans 시그니처·동작 불변.
"""
from __future__ import annotations

import json
import re
import warnings
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


# ---------------------------------------------------------------------------
# Format C — OpenInference nested dict (PatronusAI/TRAIL 등)
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?$")
_SYN_XOR = 0xFEEDFEEDFEEDFEED  # synthetic root span_id용 XOR 마스크


def _iso_duration_to_ns(dur: str) -> int:
    """ISO 8601 duration 'PTxHxMxS' → 나노초."""
    m = _DURATION_RE.match(dur)
    if not m:
        raise ValueError(f"ISO 8601 duration 파싱 실패: {dur!r}")
    h = int(m.group(1) or 0)
    mi = int(m.group(2) or 0)
    s = float(m.group(3) or 0.0)
    return int((h * 3600 + mi * 60 + s) * 1_000_000_000)


class _OISpan:
    """OpenInference nested dict 스팬 → ReadableSpan 인터페이스 shim.

    otel_spans_to_trace()가 접근하는 필드만 구현:
      .context.trace_id / .context.span_id (int)
      .parent (.span_id int) or None
      .name (str)
      .start_time / .end_time (int nanoseconds)
      .attributes (dict) — span_attributes 그대로 (token_count는 _token_count_of가 int 변환)
    """

    __slots__ = ("context", "parent", "name", "start_time", "end_time", "attributes")

    def __init__(self, raw: dict[str, Any], parent_int: int | None) -> None:
        self.context = _Ctx(
            trace_id=int(raw["trace_id"], 16),
            span_id=int(raw["span_id"], 16),
        )
        self.parent = _Parent(parent_int) if parent_int is not None else None
        self.name: str = raw.get("span_name") or "anonymous"
        start_ns = _iso_to_ns(raw["timestamp"])
        self.start_time: int = start_ns
        self.end_time: int = start_ns + _iso_duration_to_ns(raw.get("duration", "PT0S"))
        self.attributes: dict[str, Any] = raw.get("span_attributes") or {}


def _flatten_oi(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """child_spans 재귀 평탄화 (DFS 순서)."""
    result: list[dict[str, Any]] = []
    for s in spans:
        result.append(s)
        result.extend(_flatten_oi(s.get("child_spans", [])))
    return result


def ingest_from_openinference_json(
    path: Path,
    *,
    cost_table: dict[str, float] | None = None,
) -> Trace:
    """OpenInference nested dict 파일(Format C) → 정규 Trace.

    지원 구조:
      {"trace_id": "hex32", "spans": [루트 스팬, child_spans 중첩]}
      1 파일 = 1 트레이스.

    처리 흐름:
      child_spans 재귀 평탄화 → openinference.span.kind 있는 OI 스팬만 추출
      → dangling parent 처리 (다중 루트 시 synthetic CHAIN 루트 삽입 + WARNING)
      → ingest_otel_spans(shims) 경유 → preprocess_trace 정확히 1회

    Raises:
        ValueError: 빈 파일, 형식 오류, OI 스팬 없음, output.value 없는 스팬.
    """
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"{path}: 빈 파일")

    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 파싱 실패: {exc}") from exc

    if not isinstance(obj, dict) or "spans" not in obj:
        raise ValueError(
            f"Format C: 최상위가 {{\"trace_id\":..., \"spans\":[...]}} dict여야 합니다. "
            f"실제 타입: {type(obj).__name__}"
        )

    tid_str: str = obj.get("trace_id", "")
    all_raws = _flatten_oi(obj.get("spans", []))
    if not all_raws:
        raise ValueError(f"{path}: spans 배열이 비어 있음")

    # openinference.span.kind 있는 스팬만 — Patronus 래퍼 스팬 제거
    oi_raws = [
        r for r in all_raws
        if "openinference.span.kind" in r.get("span_attributes", {})
    ]
    if not oi_raws:
        raise ValueError(
            f"{path}: OpenInference 스팬(openinference.span.kind 보유)이 없음 — "
            f"전체 {len(all_raws)}개 스팬 모두 미계측"
        )

    # output.value 없는 OI 스팬 — TRAIL 실데이터에 존재; WARNING 후 건너뜀
    no_output = [
        r for r in oi_raws
        if not (r.get("span_attributes", {}).get("output.value") or "").strip()
    ]
    if no_output:
        skipped_ids = ", ".join(
            f"{r['span_name']}({r['span_id']})" for r in no_output
        )
        warnings.warn(
            f"Format C ({path.name}): output.value 없는 OI 스팬 {len(no_output)}개 건너뜀 — "
            f"{skipped_ids}",
            stacklevel=2,
        )
        oi_raws = [r for r in oi_raws if r not in no_output]
    if not oi_raws:
        raise ValueError(f"{path}: output.value 있는 OI 스팬이 하나도 없음")

    oi_ids: set[str] = {r["span_id"] for r in oi_raws}

    # OI set 밖의 parent를 가진 스팬 = dangling (Patronus 래퍼 parent)
    dangling = [r for r in oi_raws if r.get("parent_span_id") not in oi_ids]

    if len(dangling) > 1:
        # 다중 dangling (다중 에이전트 — 예: CodeAgent + sibling LLM)
        # → synthetic CHAIN 루트를 삽입해 단일 루트 보장
        warnings.warn(
            f"Format C ({path.name}): {len(dangling)}개 dangling OI 루트 발견 "
            f"({[r['span_name'] for r in dangling]}). "
            "Synthetic CHAIN 루트를 삽입합니다.",
            stacklevel=2,
        )
        syn_id_int = int(tid_str[:16], 16) ^ _SYN_XOR
        syn_raw: dict[str, Any] = {
            "trace_id": tid_str,
            "span_id": f"{syn_id_int:016x}",
            "span_name": "[openinference-trace-root]",
            "timestamp": min(r["timestamp"] for r in dangling),
            "duration": "PT0S",
            "span_attributes": {
                "openinference.span.kind": "CHAIN",
                "output.value": "[openinference trace root]",
                "input.value": "",
            },
        }
        shims: list[_OISpan] = [_OISpan(syn_raw, parent_int=None)]
        for r in oi_raws:
            if r.get("parent_span_id") not in oi_ids:
                p_int: int | None = syn_id_int
            else:
                p_int = int(r["parent_span_id"], 16)
            shims.append(_OISpan(r, parent_int=p_int))
    else:
        # 0 or 1 dangling: dangling → parent=None (root), 나머지는 그대로
        shims = [
            _OISpan(
                r,
                parent_int=(
                    None
                    if r.get("parent_span_id") not in oi_ids
                    else int(r["parent_span_id"], 16)
                ),
            )
            for r in oi_raws
        ]

    return ingest_otel_spans(shims, cost_table=cost_table, source_tag="openinference_json")
