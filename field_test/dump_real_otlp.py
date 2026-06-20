"""field_test/dump_real_otlp.py — OTel SDK 실제 직렬화 경로 탐색 (1회용).

API 호출 없음. FakeListLLM + repeat_node 그래프(루프 2회)로 raw ReadableSpan을 생성하고
OTel SDK가 실제로 내보내는 JSON 구조를 두 가지 경로로 덤프한다.

출력:
  field_test/dump_sdk_json.json   — span.to_json() 경로 (SDK 자체 직렬화)
  field_test/dump_otlp.json       — OTLP-JSON 경로 (exporter 내부 직렬화, 가능할 때)

실행:
  uv run field_test/dump_real_otlp.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TypedDict

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from langchain_core.language_models.fake import FakeListLLM
from langgraph.graph import END, StateGraph
from openinference.instrumentation.langchain import LangChainInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

FIELD_DIR = Path(__file__).parent


class _State(TypedDict):
    topic: str
    research: str
    loop_count: int


def _capture_spans() -> list:
    """FakeListLLM repeat_node 그래프 → raw ReadableSpan 리스트 (API 호출 없음)."""
    responses = [
        "멀티에이전트 AI에서 토큰 낭비 주요 원인: (1) 중복 조회 (2) 출력 재생성 (3) 루프 미종료",
        "AI 멀티에이전트 시스템의 낭비 원인 요약: (1) 중복 조회 (2) 결과 재작성 (3) 무한 반복",
    ]
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    instrumentor = LangChainInstrumentor()
    instrumentor.instrument(tracer_provider=provider, skip_dep_check=True)
    try:
        llm = FakeListLLM(responses=responses)

        def researcher_node(state: _State) -> dict:
            out = llm.invoke(f"주제: {state['topic']}")
            return {"research": out, "loop_count": state.get("loop_count", 0) + 1}

        def should_loop(state: _State) -> str:
            return "researcher" if state["loop_count"] < 2 else END

        g = StateGraph(_State)
        g.add_node("researcher", researcher_node)
        g.set_entry_point("researcher")
        g.add_conditional_edges(
            "researcher", should_loop, {"researcher": "researcher", END: END}
        )
        app = g.compile()
        app.invoke({"topic": "테스트 주제", "research": "", "loop_count": 0})
        provider.force_flush()
        return list(exporter.get_finished_spans())
    finally:
        instrumentor.uninstrument()


def _dump_sdk_json(spans: list, out_path: Path) -> None:
    """경로 A: span.to_json() — OTel SDK 자체 직렬화."""
    data = [json.loads(s.to_json()) for s in spans]
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[A] SDK JSON written: {out_path}")
    print(f"    span count: {len(data)}")
    if data:
        first = data[0]
        print(f"    top-level keys: {list(first.keys())}")


def _dump_otlp_json(spans: list, out_path: Path) -> None:
    """경로 B: OTLP-JSON — encode_spans + MessageToJson 경로."""
    try:
        from opentelemetry.exporter.otlp.proto.common._internal.trace_encoder import (
            encode_spans,
        )
        from google.protobuf.json_format import MessageToDict
    except ImportError as e:
        print(f"[B] 필요 패키지 없음 — 경로 B 스킵: {e}")
        return

    proto_msg = encode_spans(spans)
    data = MessageToDict(proto_msg, preserving_proto_field_name=True)

    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[B] OTLP JSON written: {out_path}")
    resource_spans = data.get("resource_spans", data.get("resourceSpans", []))
    print(f"    top-level keys: {list(data.keys())}")
    if resource_spans:
        scope_spans = resource_spans[0].get("scope_spans", resource_spans[0].get("scopeSpans", []))
        if scope_spans:
            first_span = scope_spans[0].get("spans", [{}])[0]
            print(f"    first span keys: {list(first_span.keys())}")
            if "attributes" in first_span and first_span["attributes"]:
                print(f"    first attr sample: {first_span['attributes'][0]}")


def _print_span_detail(spans: list) -> None:
    """ReadableSpan 객체 속성 직접 출력 — shim 설계 검증용."""
    print("\n=== ReadableSpan 객체 속성 직접 검사 ===")
    for i, s in enumerate(spans[:3]):
        print(f"\n--- span[{i}]: {s.name!r} ---")
        print(f"  context.trace_id type : {type(s.context.trace_id).__name__}")
        print(f"  context.trace_id value: {s.context.trace_id!r}")
        print(f"  context.span_id  type : {type(s.context.span_id).__name__}")
        print(f"  context.span_id  value: {s.context.span_id!r}")
        parent = s.parent
        if parent is not None:
            print(f"  parent.span_id   type : {type(parent.span_id).__name__}")
            print(f"  parent.span_id   value: {parent.span_id!r}")
        else:
            print("  parent: None (root)")
        print(f"  start_time type : {type(s.start_time).__name__}")
        print(f"  start_time value: {s.start_time!r}")
        print(f"  end_time   value: {s.end_time!r}")
        attrs = dict(s.attributes or {})
        print(f"  attributes type : {type(s.attributes).__name__}")
        print(f"  attributes keys : {list(attrs.keys())}")
        for k in ["openinference.span.kind", "input.value", "output.value",
                  "llm.token_count.total", "llm.model_name"]:
            if k in attrs:
                v = attrs[k]
                print(f"    [{k}] type={type(v).__name__!r} val={str(v)[:60]!r}")


def main() -> None:
    print("=== dump_real_otlp.py — OTel 직렬화 경로 탐색 ===\n")
    print("[*] FakeListLLM repeat_node 그래프 실행 중...")
    spans = _capture_spans()
    print(f"[*] 캡처된 span 수: {len(spans)}\n")

    _print_span_detail(spans)

    print("\n=== 직렬화 경로 A: span.to_json() ===")
    sdk_path = FIELD_DIR / "dump_sdk_json.json"
    _dump_sdk_json(spans, sdk_path)

    # SDK JSON 첫 span 상세 출력
    sdk_data = json.loads(sdk_path.read_text(encoding="utf-8"))
    if sdk_data:
        print("\n  첫 번째 span (SDK JSON) 전체 구조:")
        print(json.dumps(sdk_data[0], indent=4, ensure_ascii=False)[:2000])

    print("\n=== 직렬화 경로 B: OTLP exporter ===")
    otlp_path = FIELD_DIR / "dump_otlp.json"
    _dump_otlp_json(spans, otlp_path)


if __name__ == "__main__":
    main()
