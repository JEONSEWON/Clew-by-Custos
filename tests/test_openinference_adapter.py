"""tests/test_openinference_adapter.py — OpenInference adapter regression + §5 gate.

Locks the mapping defined by docs/OPENINFERENCE_ADAPTER_PREREG.md §4:
  - `_agent_or_node_id_of` per span_kind:
      tool  → attrs["tool.name"] → span_name
      agent → attrs["graph.node.id"] → span_name
      llm / chain → span_name (unchanged)
  - `_extract_tool_output` TOOL span envelope shim (LangChain JSON wrap vs CrewAI raw).

Gates:
  §5.1 — existing LangGraph fixture must produce byte-identical
         (span_id, span_kind, agent_or_node_id) set under the new mapping.
  §7.2 — new LangChain / CrewAI fixtures regression.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from clew.ingest.langgraph import _agent_or_node_id_of, _extract_tool_output
from clew.ingest.otel_json import ingest_from_otel_json

# Fixture locations
FIXT_LC = Path(__file__).parent / "fixtures" / "openinference_langchain.json"
FIXT_CA = Path(__file__).parent / "fixtures" / "openinference_crewai.json"


# ── unit tests: mapping helper (§4.2) ────────────────────────────────────────

def test_agent_or_node_id_tool_prefers_tool_name():
    assert _agent_or_node_id_of("tool", "search_web.run", {"tool.name": "search_web"}) == "search_web"


def test_agent_or_node_id_tool_falls_back_to_span_name():
    assert _agent_or_node_id_of("tool", "search_web", {}) == "search_web"


def test_agent_or_node_id_tool_falls_back_when_tool_name_empty():
    assert _agent_or_node_id_of("tool", "search_web", {"tool.name": ""}) == "search_web"


def test_agent_or_node_id_agent_prefers_graph_node_id():
    assert _agent_or_node_id_of("agent", "Web Researcher._execute_core",
                                {"graph.node.id": "Web Researcher"}) == "Web Researcher"


def test_agent_or_node_id_agent_falls_back_to_span_name():
    assert _agent_or_node_id_of("agent", "solo_agent", {}) == "solo_agent"


def test_agent_or_node_id_chain_uses_span_name_unchanged():
    # Even if attrs contain tool.name, chain uses span_name (out-of-scope for tool mapping).
    assert _agent_or_node_id_of("chain", "pipeline", {"tool.name": "search_web"}) == "pipeline"


def test_agent_or_node_id_llm_uses_span_name_unchanged():
    assert _agent_or_node_id_of("llm", "claude", {"graph.node.id": "Whatever"}) == "claude"


def test_agent_or_node_id_missing_span_name_returns_anonymous():
    assert _agent_or_node_id_of("chain", "", {}) == "anonymous"


# ── unit tests: output envelope shim (§4.3) ──────────────────────────────────

def test_extract_tool_output_langchain_envelope():
    raw = json.dumps({"type": "tool", "data": {"content": "Result 1: hit"}})
    attrs = {"output.value": raw, "output.mime_type": "application/json"}
    assert _extract_tool_output(attrs) == "Result 1: hit"


def test_extract_tool_output_crewai_text_plain():
    attrs = {"output.value": "Result 1: hit", "output.mime_type": "text/plain"}
    assert _extract_tool_output(attrs) == "Result 1: hit"


def test_extract_tool_output_json_not_envelope_returns_raw():
    raw = json.dumps({"type": "ai", "content": "not-tool-envelope"})
    attrs = {"output.value": raw, "output.mime_type": "application/json"}
    assert _extract_tool_output(attrs) == raw


def test_extract_tool_output_invalid_json_returns_raw():
    attrs = {"output.value": "{not-json", "output.mime_type": "application/json"}
    assert _extract_tool_output(attrs) == "{not-json"


def test_extract_tool_output_no_mime_returns_raw():
    attrs = {"output.value": "opaque"}
    assert _extract_tool_output(attrs) == "opaque"


def test_extract_tool_output_none_returns_empty():
    assert _extract_tool_output({}) == ""


# ── §5.1 gate: MINIMAL_SDK_JSON stable under new mapping ─────────────────────
# The prereg calls out tests/test_otel_json_ingest.py::MINIMAL_SDK_JSON, which
# has no TOOL / AGENT spans — so the new mapping is a trivial no-op on it.
# This test locks that invariant.

def test_langgraph_minimal_fixture_stable_under_new_mapping(tmp_path):
    from tests.test_otel_json_ingest import MINIMAL_SDK_JSON  # noqa: PLC0415

    p = tmp_path / "trace.json"
    p.write_text(json.dumps(MINIMAL_SDK_JSON), encoding="utf-8")

    trace = ingest_from_otel_json(p)
    observed = {(s.span_id, s.span_kind, s.agent_or_node_id) for s in trace.spans}
    expected = {
        ("0000000000000001", "chain", "pipeline"),
        ("0000000000000002", "chain", "researcher"),
    }
    assert observed == expected, (
        f"§5.1 gate FAIL — existing LangGraph fixture output changed.\n"
        f"observed={sorted(observed)}\nexpected={sorted(expected)}"
    )


# ── §7.2 regression: LangChain fixture ───────────────────────────────────────

def _tool_spans(trace):
    return [s for s in trace.spans if s.span_kind == "tool"]


def _agent_spans(trace):
    return [s for s in trace.spans if s.span_kind == "agent"]


def test_ingest_openinference_langchain_fixture_schema():
    trace = ingest_from_otel_json(FIXT_LC)
    tool_spans = _tool_spans(trace)
    # Multiple search_web tool invocations in the fixture; all normalize to tool.name = "search_web"
    assert tool_spans, "expected at least one TOOL span in LangChain fixture"
    assert all(s.agent_or_node_id == "search_web" for s in tool_spans)


def test_ingest_openinference_langchain_fixture_envelope_unwrap():
    trace = ingest_from_otel_json(FIXT_LC)
    tool_spans = _tool_spans(trace)
    # Envelope must be unwrapped — content string surfaces, tool_call_id envelope disappears
    for s in tool_spans:
        assert "Result 1:" in s.output_text, f"envelope not unwrapped: {s.output_text[:120]!r}"
        assert "tool_call_id" not in s.output_text
        assert '"type": "tool"' not in s.output_text


def test_ingest_openinference_langchain_fixture_tool_output_sha256_matches():
    """Two search_web calls in LangChain fixture have distinct tool_call_id envelopes
    (call_1 vs call_2) — unwrapping should collapse them to identical sha256."""
    trace = ingest_from_otel_json(FIXT_LC)
    tool_spans = _tool_spans(trace)
    hashes = {hashlib.sha256(s.output_text.encode()).hexdigest() for s in tool_spans}
    # All tool call outputs unwrap to the same content
    assert len(hashes) == 1, (
        f"expected all tool outputs to unwrap to identical content, got {len(hashes)} distinct hashes"
    )


# ── §7.2 regression: CrewAI fixture ──────────────────────────────────────────

def test_ingest_openinference_crewai_fixture_schema():
    trace = ingest_from_otel_json(FIXT_CA)
    tool_spans = _tool_spans(trace)
    agent_spans = _agent_spans(trace)

    # tool.name wins over span_name (which has `.run` suffix)
    assert tool_spans
    assert all(s.agent_or_node_id == "search_web" for s in tool_spans), (
        f"tool.name not preferred; got ids: {[s.agent_or_node_id for s in tool_spans]}"
    )

    # graph.node.id wins over span_name (which has `._execute_core` suffix)
    # Note: preprocess.filter_router_spans removes agents without llm/tool descendants
    # (e.g. Fact Verifier), so only Web Researcher may survive here.
    assert agent_spans
    for s in agent_spans:
        assert s.agent_or_node_id in {"Web Researcher", "Fact Verifier"}, (
            f"graph.node.id not preferred; got id: {s.agent_or_node_id}"
        )


def test_ingest_openinference_crewai_fixture_tool_output_sha256_matches():
    """CrewAI has two identical tool call outputs (text/plain, no envelope) — sha256 identical raw."""
    trace = ingest_from_otel_json(FIXT_CA)
    tool_spans = _tool_spans(trace)
    hashes = {hashlib.sha256(s.output_text.encode()).hexdigest() for s in tool_spans}
    assert len(hashes) == 1, (
        f"expected identical raw outputs, got {len(hashes)} distinct hashes"
    )


def test_ingest_openinference_crewai_fixture_tool_output_starts_with_result():
    trace = ingest_from_otel_json(FIXT_CA)
    tool_spans = _tool_spans(trace)
    for s in tool_spans:
        assert s.output_text.startswith("Result 1:"), (
            f"crewai tool output should be raw text starting 'Result 1:', got: {s.output_text[:80]!r}"
        )


# ── shim symbol imports (guard against accidental deletion) ─────────────────

def test_agent_or_node_id_helper_symbol_exists():
    from clew.ingest.langgraph import _agent_or_node_id_of  # noqa: PLC0415, F401


def test_extract_tool_output_helper_symbol_exists():
    from clew.ingest.langgraph import _extract_tool_output  # noqa: PLC0415, F401
