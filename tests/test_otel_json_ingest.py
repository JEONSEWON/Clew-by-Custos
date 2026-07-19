"""tests/test_otel_json_ingest.py — OTel SDK JSON entry-point tests (G1·G2·G4, §12).

Format A: span.to_json() array → ingest_from_otel_json → Trace.

G1: OTel JSON file → ingest_from_otel_json → Trace construction
G2: existing Clew Trace JSON → _load_trace_auto → Trace (backward compatibility)
G4: ReadableSpan path ≡ JSON path (equivalence)
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from clew.ingest.otel_json import (
    _OISpan,
    _SdkJsonSpan,
    _iso_to_ns,
    _parse_sdk_json,
    ingest_from_otel_json,
    ingest_from_openinference_json,
)
from clew.io import save_trace

# ── Shared fixture constants ────────────────────────────────────────────────

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


# Minimal valid trace: root(CHAIN) → researcher(CHAIN) → claude(LLM)
_ROOT   = _sdk_span("pipeline",   _TID, _S1, None, "CHAIN",
                    {"input.value": "q", "output.value": "root out"})
_WORKER = _sdk_span("researcher", _TID, _S2, _S1,  "CHAIN",
                    {"input.value": "q", "output.value": "research out"})
_LLM    = _sdk_span("claude",     _TID, _S3, _S2,  "LLM",
                    {"input.value": "q", "output.value": "llm out",
                     "llm.token_count.total": 50})

MINIMAL_SDK_JSON = [_ROOT, _WORKER, _LLM]


# ── 1. _iso_to_ns unit test ────────────────────────────────────────────────

def test_iso_to_ns_roundtrip():
    """ISO datetime → ns → datetime round-trip (within 1µs)."""
    from datetime import datetime, timezone
    from clew.ingest.langgraph import _ns_to_utc

    iso = "2026-06-20T10:54:26.378797Z"
    ns = _iso_to_ns(iso)
    dt = _ns_to_utc(ns)
    # Compare at microsecond granularity (allowing float precision slack)
    expected = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    diff_us = abs((dt - expected).total_seconds() * 1e6)
    assert diff_us < 1.0, f"round-trip error {diff_us:.3f}µs > 1µs"


# ── 2. _SdkJsonSpan shim unit tests ─────────────────────────────────────────

def test_shim_context_hex_parsing():
    """trace_id / span_id "0x..." hex → int conversion correctness."""
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
    """Flat dict attributes are passed through without transformation."""
    shim = _SdkJsonSpan(_LLM)
    assert shim.attributes["openinference.span.kind"] == "LLM"
    assert shim.attributes["llm.token_count.total"] == 50
    assert shim.attributes["output.value"] == "llm out"


# ── 3. ingest_from_otel_json integration test (G1) ──────────────────────────

def test_ingest_from_otel_json_file(tmp_path):
    """Format A JSON file → Trace construction (G1).

    After preprocess, llm span is removed; verify id·kind·name of remaining spans.
    """
    p = tmp_path / "trace.json"
    p.write_text(json.dumps(MINIMAL_SDK_JSON), encoding="utf-8")

    trace = ingest_from_otel_json(p)

    assert trace.trace_id  # non-empty
    # After preprocess: pipeline(CHAIN), researcher(CHAIN) — llm(claude) collapsed
    kinds = {s.span_kind for s in trace.spans}
    assert "llm" not in kinds  # verify collapse
    names = {s.agent_or_node_id for s in trace.spans}
    assert "pipeline" in names
    assert "researcher" in names


# ── 4. Assert preprocess runs exactly once ──────────────────────────────────

def test_preprocess_runs_exactly_once(tmp_path):
    """ingest_from_otel_json → ingest_otel_spans → preprocess_trace exactly once."""
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

    assert len(call_count) == 1, f"preprocess_trace called {len(call_count)} times (expected: 1)"


# ── 5. G4 equivalence test (ReadableSpan path ≡ JSON path) ──────────────────

def test_g4_equivalence(tmp_path):
    """Ingest the same spans via the ReadableSpan path and the Format A JSON path → equivalent.

    Assert the sets of (span_id · span_kind · agent_or_node_id) are identical.
    Skip if opentelemetry is not installed.
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

    # Path A: ingest ReadableSpan directly
    trace_a = ingest_otel_spans(raw_spans)

    # Path B: span.to_json() → JSON file → ingest_from_otel_json
    sdk_json = [json.loads(s.to_json()) for s in raw_spans]
    p = tmp_path / "spans.json"
    p.write_text(json.dumps(sdk_json), encoding="utf-8")
    trace_b = ingest_from_otel_json(p)

    def _key(s):
        return (s.span_id, s.span_kind, s.agent_or_node_id)

    assert set(_key(s) for s in trace_a.spans) == set(_key(s) for s in trace_b.spans), (
        f"Path A spans: {[_key(s) for s in trace_a.spans]}\n"
        f"Path B spans: {[_key(s) for s in trace_b.spans]}"
    )


# ── 6. Error cases ──────────────────────────────────────────────────────────

def test_missing_output_value_raises_clear_error(tmp_path):
    """Span missing output.value → ValueError, message contains the span name."""
    bad_span = _sdk_span("bad_node", _TID, _S1, None, "CHAIN",
                         {"input.value": "x"})  # output.value missing
    good_span = _sdk_span("good_node", _TID, _S2, _S1, "CHAIN",
                          {"input.value": "x", "output.value": "ok"})

    p = tmp_path / "trace.json"
    p.write_text(json.dumps([bad_span, good_span]), encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        ingest_from_otel_json(p)

    assert "bad_node" in str(exc_info.value)


def test_format_b_resource_spans_error(tmp_path):
    """Format B (resource_spans key) → clear error + conversion guidance."""
    proto_json = {"resource_spans": [{"scope_spans": [{"spans": []}]}]}
    p = tmp_path / "trace.json"
    p.write_text(json.dumps(proto_json), encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        ingest_from_otel_json(p)

    msg = str(exc_info.value)
    assert "resource_spans" in msg
    assert "미지원" in msg or "Format A" in msg


# ── 7. CLI _load_trace_auto tests (G1·G2) ───────────────────────────────────

def _get_load_trace_auto():
    mod = importlib.import_module("clew.__main__")
    return mod._load_trace_auto


def test_load_trace_auto_clew_format(tmp_path):
    """Existing Clew Trace JSON → _load_trace_auto → Trace (G2 backward compat)."""
    from clew.ingest.otel_json import ingest_from_otel_json as _ingest

    # Produce a valid Clew Trace JSON: build via Format A, then save_trace
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
    """Format A JSON → _load_trace_auto → Trace (G1 CLI path)."""
    p = tmp_path / "trace.json"
    p.write_text(json.dumps(MINIMAL_SDK_JSON), encoding="utf-8")

    load_auto = _get_load_trace_auto()
    trace = load_auto(p)

    assert trace.trace_id
    names = {s.agent_or_node_id for s in trace.spans}
    assert "pipeline" in names


def test_load_trace_auto_format_b_error(tmp_path):
    """resource_spans key → _load_trace_auto returns a clear error."""
    proto_json = {"resource_spans": []}
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(proto_json), encoding="utf-8")

    load_auto = _get_load_trace_auto()
    with pytest.raises(ValueError) as exc_info:
        load_auto(p)

    assert "resource_spans" in str(exc_info.value)
    assert "미지원" in str(exc_info.value)


# ── STAGE 14: Format C (OpenInference/TRAIL) — H1–H6 ────────────────────────

import warnings as _warnings_mod

_FIELD_TEST = Path(__file__).parent.parent / "field_test"
_TRAIL_PATH = _FIELD_TEST / "trail_sample.json"
_REAL_REQUERY_PATH = _FIELD_TEST / "real_requery_known.json"
_VERIFY_README_PATH = _FIELD_TEST / "verify_readme_output.json"

_OI_TID = "aabbccdd112233440000000011223344"
_OI_S1  = "0000000000000001"
_OI_S2  = "0000000000000002"
_OI_T0  = "2026-01-01T00:00:00.000000Z"
_OI_T1  = "2026-01-01T00:00:01.000000Z"


def _oi_raw(span_id, parent_span_id, name, kind, output, inp="q", children=None):
    return {
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "trace_id": _OI_TID,
        "span_name": name,
        "timestamp": _OI_T0,
        "duration": "PT1S",
        "span_attributes": {
            "openinference.span.kind": kind,
            "output.value": output,
            "input.value": inp,
        },
        "child_spans": children or [],
    }


def _oi_file(tmp_path, spans_list):
    p = tmp_path / "trace_c.json"
    p.write_text(json.dumps({"trace_id": _OI_TID, "spans": spans_list}), encoding="utf-8")
    return p


def _sdk_oi_span(name, span_id, parent_id, kind, output, inp="q"):
    return {
        "name": name,
        "context": {"trace_id": "0x" + _OI_TID, "span_id": "0x" + span_id, "trace_state": "[]"},
        "kind": "SpanKind.INTERNAL",
        "parent_id": ("0x" + parent_id) if parent_id else None,
        "start_time": _OI_T0,
        "end_time": _OI_T1,
        "status": {"status_code": "OK"},
        "attributes": {"openinference.span.kind": kind, "output.value": output, "input.value": inp},
        "events": [], "links": [],
        "resource": {"attributes": {"service.name": "test"}, "schema_url": ""},
    }


# H1 ─────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _TRAIL_PATH.exists(), reason="trail_sample.json missing")
def test_h1_trail_smoke():
    """TRAIL file → _load_trace_auto → returns Trace (H1)."""
    from clew.model import Trace
    load_auto = _get_load_trace_auto()
    with _warnings_mod.catch_warnings():
        _warnings_mod.simplefilter("ignore")
        trace = load_auto(_TRAIL_PATH)
    assert isinstance(trace, Trace)
    assert trace.trace_id
    assert len(trace.spans) > 0


@pytest.mark.skipif(not _TRAIL_PATH.exists(), reason="trail_sample.json missing")
def test_h1_trail_analyze_report():
    """TRAIL → cascade → render_markdown succeeds (H1)."""
    from clew.detect.cascade import cascade
    from clew.detect.semantic import Embedder
    from clew.report.markdown import render_markdown

    _PHI = 0.514345
    _N = 2
    _MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
    _REV = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
    _CACHE = Path.home() / ".cache" / "clew" / "embeddings"

    load_auto = _get_load_trace_auto()
    with _warnings_mod.catch_warnings():
        _warnings_mod.simplefilter("ignore")
        trace = load_auto(_TRAIL_PATH)

    embedder = Embedder(model_name=_MODEL, revision=_REV, cache_dir=_CACHE)
    cr = cascade(trace, embedder, n=_N, phi=_PHI)
    md = render_markdown(trace, cr, [], no_snippets=True)
    assert isinstance(md, str) and len(md) > 0


# H2 ─────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _REAL_REQUERY_PATH.exists(), reason="real_requery_known.json missing")
def test_h2_format_a_regression():
    """real_requery_known.json → _load_trace_auto → Trace (H2 regression)."""
    from clew.model import Trace
    load_auto = _get_load_trace_auto()
    trace = load_auto(_REAL_REQUERY_PATH)
    assert isinstance(trace, Trace)
    assert len(trace.spans) > 0


# H3 ─────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _VERIFY_README_PATH.exists(), reason="verify_readme_output.json missing")
def test_h3_serialized_trace_regression():
    """verify_readme_output.json → _load_trace_auto → Trace (H3 regression)."""
    from clew.model import Trace
    load_auto = _get_load_trace_auto()
    trace = load_auto(_VERIFY_README_PATH)
    assert isinstance(trace, Trace)
    assert len(trace.spans) > 0


# H5 — Format A ↔ Format C equivalence ──────────────────────────────────────

def _trace_a(tmp_path):
    spans = [
        _sdk_oi_span("root", _OI_S1, None,   "CHAIN", "hello root"),
        _sdk_oi_span("tool", _OI_S2, _OI_S1, "TOOL",  "hello tool"),
    ]
    p = tmp_path / "a.json"
    p.write_text(json.dumps(spans), encoding="utf-8")
    return ingest_from_otel_json(p)


def _trace_c(tmp_path):
    child = _oi_raw(_OI_S2, _OI_S1, "tool", "TOOL", "hello tool")
    root  = _oi_raw(_OI_S1, None,   "root", "CHAIN", "hello root", children=[child])
    return ingest_from_openinference_json(_oi_file(tmp_path, [root]))


def test_h5_equivalence_span_count(tmp_path):
    """Format A vs C — same span count (H5)."""
    (tmp_path / "a").mkdir(); (tmp_path / "c").mkdir()
    ta = _trace_a(tmp_path / "a")
    tc = _trace_c(tmp_path / "c")
    assert len(ta.spans) == len(tc.spans)


def test_h5_equivalence_span_kinds(tmp_path):
    """Format A vs C — same span_kind set (H5)."""
    (tmp_path / "a").mkdir(); (tmp_path / "c").mkdir()
    ta = _trace_a(tmp_path / "a")
    tc = _trace_c(tmp_path / "c")
    assert {s.span_kind for s in ta.spans} == {s.span_kind for s in tc.spans}


def test_h5_equivalence_output_text(tmp_path):
    """Format A vs C — same output_text set (H5)."""
    (tmp_path / "a").mkdir(); (tmp_path / "c").mkdir()
    ta = _trace_a(tmp_path / "a")
    tc = _trace_c(tmp_path / "c")
    assert {s.output_text for s in ta.spans} == {s.output_text for s in tc.spans}


# H6 — Broken Format C errors ───────────────────────────────────────────────

def test_h6_no_oi_spans_raises(tmp_path):
    """Only spans without openinference.span.kind → ValueError (H6)."""
    bad = {
        "span_id": _OI_S1, "parent_span_id": None, "trace_id": _OI_TID,
        "span_name": "wrapper", "timestamp": _OI_T0, "duration": "PT1S",
        "span_attributes": {"pat.some_key": "val"},
        "child_spans": [],
    }
    with pytest.raises(ValueError, match="OpenInference 스팬"):
        ingest_from_openinference_json(_oi_file(tmp_path, [bad]))


def test_h6_missing_output_value_raises(tmp_path):
    """When only OI spans missing output.value are present → ValueError (H6)."""
    no_out = _oi_raw(_OI_S1, None, "empty_node", "CHAIN", "")
    no_out["span_attributes"].pop("output.value")
    with pytest.raises(ValueError):
        with _warnings_mod.catch_warnings():
            _warnings_mod.simplefilter("ignore")
            ingest_from_openinference_json(_oi_file(tmp_path, [no_out]))


def test_h6_invalid_hex_span_id_raises(tmp_path):
    """Non-hex span_id → ValueError (H6)."""
    bad_hex = _oi_raw("ZZZZZZZZZZZZZZZZ", None, "bad_node", "CHAIN", "out")
    with pytest.raises(ValueError):
        ingest_from_openinference_json(_oi_file(tmp_path, [bad_hex]))


def test_h6_empty_spans_raises(tmp_path):
    """Empty spans array → ValueError (H6)."""
    p = tmp_path / "empty.json"
    p.write_text(json.dumps({"trace_id": _OI_TID, "spans": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        ingest_from_openinference_json(p)


# shim unit / CLI routing / preprocess ──────────────────────────────────────

def test_oi_shim_ids_and_parent():
    """_OISpan: hex ID parsing, root parent=None (§14)."""
    raw = _oi_raw(_OI_S1, None, "root", "CHAIN", "out")
    shim = _OISpan(raw, parent_int=None)
    assert shim.context.trace_id == int(_OI_TID, 16)
    assert shim.context.span_id  == int(_OI_S1, 16)
    assert shim.parent is None

    raw_child = _oi_raw(_OI_S2, _OI_S1, "child", "TOOL", "out2")
    shim_c = _OISpan(raw_child, parent_int=int(_OI_S1, 16))
    assert shim_c.parent is not None
    assert shim_c.parent.span_id == int(_OI_S1, 16)


def test_load_trace_auto_routes_oi_nested(tmp_path):
    """dict + span_attributes → ingest_from_openinference_json path (§14)."""
    child = _oi_raw(_OI_S2, _OI_S1, "tool", "TOOL", "hello tool")
    root  = _oi_raw(_OI_S1, None,   "root", "CHAIN", "hello root", children=[child])
    p = _oi_file(tmp_path, [root])

    with patch("clew.ingest.otel_json.ingest_from_openinference_json",
               wraps=ingest_from_openinference_json) as mock_fn:
        load_auto = _get_load_trace_auto()
        load_auto(p)

    mock_fn.assert_called_once()


def test_oi_preprocess_exactly_once(tmp_path):
    """ingest_from_openinference_json → preprocess_trace exactly once (§14)."""
    import clew.ingest.langgraph as lg_module

    call_count: list[int] = []
    original = lg_module.preprocess_trace

    def counting(trace):
        call_count.append(1)
        return original(trace)

    child = _oi_raw(_OI_S2, _OI_S1, "tool", "TOOL", "hello tool")
    root  = _oi_raw(_OI_S1, None,   "root", "CHAIN", "hello root", children=[child])

    with patch.object(lg_module, "preprocess_trace", side_effect=counting):
        ingest_from_openinference_json(_oi_file(tmp_path, [root]))

    assert len(call_count) == 1, f"preprocess_trace called {len(call_count)} times (expected: 1)"
