"""tests/test_otel_json_ingest.py — OTel SDK JSON 진입점 테스트 (G1·G2·G4, §12).

Format A: span.to_json() 배열 → ingest_from_otel_json → Trace.

G1: OTel JSON 파일 → ingest_from_otel_json → Trace 생성
G2: 기존 Clew Trace JSON → _load_trace_auto → Trace (하위 호환)
G4: ReadableSpan 경로 ≡ JSON 경로 (동치성)
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from clew.ingest.otel_json import _SdkJsonSpan, _iso_to_ns, _parse_sdk_json, ingest_from_otel_json
from clew.io import save_trace

# ── 공통 픽스처 상수 ────────────────────────────────────────────────────────

_TID = "0xaabbccdd112233440000000011223344"
_S1  = "0x0000000000000001"
_S2  = "0x0000000000000002"
_S3  = "0x0000000000000003"

_T0 = "2026-01-01T00:00:00.000000Z"
_T1 = "2026-01-01T00:00:01.000000Z"
_T2 = "2026-01-01T00:00:02.000000Z"


def _sdk_span(
    name: str,
    trace_id: str,
    span_id: str,
    parent_id: str | None,
    kind: str,
    attrs: dict[str, Any],
    start: str = _T0,
    end: str = _T1,
) -> dict[str, Any]:
    return {
        "name": name,
        "context": {"trace_id": trace_id, "span_id": span_id, "trace_state": "[]"},
        "kind": "SpanKind.INTERNAL",
        "parent_id": parent_id,
        "start_time": start,
        "end_time": end,
        "status": {"status_code": "OK"},
        "attributes": {**attrs, "openinference.span.kind": kind},
        "events": [],
        "links": [],
        "resource": {"attributes": {"service.name": "test"}, "schema_url": ""},
    }


# 최소 유효 트레이스: root(CHAIN) → researcher(CHAIN) → claude(LLM)
_ROOT   = _sdk_span("pipeline",   _TID, _S1, None, "CHAIN",
                    {"input.value": "q", "output.value": "root out"})
_WORKER = _sdk_span("researcher", _TID, _S2, _S1,  "CHAIN",
                    {"input.value": "q", "output.value": "research out"})
_LLM    = _sdk_span("claude",     _TID, _S3, _S2,  "LLM",
                    {"input.value": "q", "output.value": "llm out",
                     "llm.token_count.total": 50})

MINIMAL_SDK_JSON = [_ROOT, _WORKER, _LLM]


# ── 1. _iso_to_ns 단위 테스트 ────────────────────────────────────────────────

def test_iso_to_ns_roundtrip():
    """ISO datetime → ns → datetime 왕복 (1µs 이내)."""
    from datetime import datetime, timezone
    from clew.ingest.langgraph import _ns_to_utc

    iso = "2026-06-20T10:54:26.378797Z"
    ns = _iso_to_ns(iso)
    dt = _ns_to_utc(ns)
    # microsecond 단위 비교 (float 정밀도 한계 허용)
    expected = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    diff_us = abs((dt - expected).total_seconds() * 1e6)
    assert diff_us < 1.0, f"왕복 오차 {diff_us:.3f}µs > 1µs"


# ── 2. _SdkJsonSpan shim 단위 테스트 ────────────────────────────────────────

def test_shim_context_hex_parsing():
    """trace_id / span_id "0x..." hex → int 변환 정확성."""
    shim = _SdkJsonSpan(_ROOT)
    # "0xaabbccdd112233440000000011223344" → int
    expected_tid = int("aabbccdd112233440000000011223344", 16)
    expected_sid = int("0000000000000001", 16)
    assert shim.context.trace_id == expected_tid
    assert shim.context.span_id == expected_sid


def test_shim_parent_present():
    """parent_id "0x..." → _Parent(int span_id)."""
    shim = _SdkJsonSpan(_WORKER)
    assert shim.parent is not None
    assert shim.parent.span_id == int("0000000000000001", 16)


def test_shim_parent_null():
    """parent_id: null → self.parent is None."""
    shim = _SdkJsonSpan(_ROOT)
    assert shim.parent is None


def test_shim_attributes_passthrough():
    """flat dict attributes가 변환 없이 그대로 전달됨."""
    shim = _SdkJsonSpan(_LLM)
    assert shim.attributes["openinference.span.kind"] == "LLM"
    assert shim.attributes["llm.token_count.total"] == 50
    assert shim.attributes["output.value"] == "llm out"


# ── 3. ingest_from_otel_json 통합 테스트 (G1) ───────────────────────────────

def test_ingest_from_otel_json_file(tmp_path):
    """Format A JSON 파일 → Trace 생성 (G1).

    preprocess 후 llm span 제거, 나머지 spans의 id·kind·name 확인.
    """
    p = tmp_path / "trace.json"
    p.write_text(json.dumps(MINIMAL_SDK_JSON), encoding="utf-8")

    trace = ingest_from_otel_json(p)

    assert trace.trace_id  # 비어있지 않음
    # preprocess 후: pipeline(CHAIN), researcher(CHAIN) — llm(claude) collapse됨
    kinds = {s.span_kind for s in trace.spans}
    assert "llm" not in kinds  # collapse 확인
    names = {s.agent_or_node_id for s in trace.spans}
    assert "pipeline" in names
    assert "researcher" in names


# ── 4. preprocess 정확히 1회 단언 ────────────────────────────────────────────

def test_preprocess_runs_exactly_once(tmp_path):
    """ingest_from_otel_json → ingest_otel_spans → preprocess_trace 정확히 1회."""
    import clew.ingest.langgraph as lg_module

    call_count: list[int] = []
    original = lg_module.preprocess_trace

    def counting(trace):
        call_count.append(1)
        return original(trace)

    p = tmp_path / "trace.json"
    p.write_text(json.dumps(MINIMAL_SDK_JSON), encoding="utf-8")

    with patch.object(lg_module, "preprocess_trace", side_effect=counting):
        ingest_from_otel_json(p)

    assert len(call_count) == 1, f"preprocess_trace가 {len(call_count)}회 호출됨 (기대: 1)"


# ── 5. G4 동치성 테스트 (ReadableSpan 경로 ≡ JSON 경로) ─────────────────────

def test_g4_equivalence(tmp_path):
    """동일 스팬을 ReadableSpan 경로 / Format A JSON 경로로 각각 ingest → 동치.

    span_id · span_kind · agent_or_node_id 세트가 일치함을 단언.
    opentelemetry 미설치 시 skip.
    """
    pytest.importorskip("opentelemetry.sdk.trace")
    pytest.importorskip("openinference.instrumentation.langchain")
    pytest.importorskip("langgraph.graph")
    pytest.importorskip("langchain_core.language_models.fake")

    from langchain_core.language_models.fake import FakeListLLM
    from langgraph.graph import END, StateGraph
    from openinference.instrumentation.langchain import LangChainInstrumentor
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from typing import TypedDict

    from clew.ingest.langgraph import ingest_otel_spans

    class _State(TypedDict):
        topic: str
        out: str

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    instrumentor = LangChainInstrumentor()
    instrumentor.instrument(tracer_provider=provider, skip_dep_check=True)
    try:
        llm = FakeListLLM(responses=["test output from llm"])

        def node(state: _State) -> dict:
            return {"out": llm.invoke(state["topic"])}

        g = StateGraph(_State)
        g.add_node("worker", node)
        g.set_entry_point("worker")
        g.add_edge("worker", END)
        g.compile().invoke({"topic": "test", "out": ""})
        provider.force_flush()
        raw_spans = list(exporter.get_finished_spans())
    finally:
        instrumentor.uninstrument()

    # 경로 A: ReadableSpan 직접 ingest
    trace_a = ingest_otel_spans(raw_spans)

    # 경로 B: span.to_json() → JSON 파일 → ingest_from_otel_json
    sdk_json = [json.loads(s.to_json()) for s in raw_spans]
    p = tmp_path / "spans.json"
    p.write_text(json.dumps(sdk_json), encoding="utf-8")
    trace_b = ingest_from_otel_json(p)

    def _key(s):
        return (s.span_id, s.span_kind, s.agent_or_node_id)

    assert set(_key(s) for s in trace_a.spans) == set(_key(s) for s in trace_b.spans), (
        f"경로 A spans: {[_key(s) for s in trace_a.spans]}\n"
        f"경로 B spans: {[_key(s) for s in trace_b.spans]}"
    )


# ── 6. 에러 케이스 ───────────────────────────────────────────────────────────

def test_missing_output_value_raises_clear_error(tmp_path):
    """output.value 없는 스팬 → ValueError, 메시지에 span name 포함."""
    bad_span = _sdk_span("bad_node", _TID, _S1, None, "CHAIN",
                         {"input.value": "x"})  # output.value 누락
    good_span = _sdk_span("good_node", _TID, _S2, _S1, "CHAIN",
                          {"input.value": "x", "output.value": "ok"})

    p = tmp_path / "trace.json"
    p.write_text(json.dumps([bad_span, good_span]), encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        ingest_from_otel_json(p)

    assert "bad_node" in str(exc_info.value)


def test_format_b_resource_spans_error(tmp_path):
    """Format B (resource_spans 키) → 명확한 에러 + 변환 안내."""
    proto_json = {"resource_spans": [{"scope_spans": [{"spans": []}]}]}
    p = tmp_path / "trace.json"
    p.write_text(json.dumps(proto_json), encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        ingest_from_otel_json(p)

    msg = str(exc_info.value)
    assert "resource_spans" in msg
    assert "미지원" in msg or "Format A" in msg


# ── 7. CLI _load_trace_auto 테스트 (G1·G2) ───────────────────────────────────

def _get_load_trace_auto():
    mod = importlib.import_module("clew.__main__")
    return mod._load_trace_auto


def test_load_trace_auto_clew_format(tmp_path):
    """기존 Clew Trace JSON → _load_trace_auto → Trace (G2 하위 호환)."""
    from clew.ingest.otel_json import ingest_from_otel_json as _ingest

    # 유효한 Clew Trace JSON 생성: Format A 로 만든 후 save_trace
    p_sdk = tmp_path / "spans.json"
    p_sdk.write_text(json.dumps(MINIMAL_SDK_JSON), encoding="utf-8")
    trace_orig = ingest_from_otel_json(p_sdk)

    clew_path = tmp_path / "clew_trace.json"
    save_trace(trace_orig, clew_path)

    load_auto = _get_load_trace_auto()
    trace_loaded = load_auto(clew_path)

    assert trace_loaded.trace_id == trace_orig.trace_id
    assert len(trace_loaded.spans) == len(trace_orig.spans)


def test_load_trace_auto_format_a(tmp_path):
    """Format A JSON → _load_trace_auto → Trace (G1 CLI 경로)."""
    p = tmp_path / "trace.json"
    p.write_text(json.dumps(MINIMAL_SDK_JSON), encoding="utf-8")

    load_auto = _get_load_trace_auto()
    trace = load_auto(p)

    assert trace.trace_id
    names = {s.agent_or_node_id for s in trace.spans}
    assert "pipeline" in names


def test_load_trace_auto_format_b_error(tmp_path):
    """resource_spans 키 → _load_trace_auto가 명확한 에러 반환."""
    proto_json = {"resource_spans": []}
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(proto_json), encoding="utf-8")

    load_auto = _get_load_trace_auto()
    with pytest.raises(ValueError) as exc_info:
        load_auto(p)

    assert "resource_spans" in str(exc_info.value)
    assert "미지원" in str(exc_info.value)
