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


# ── §5.4 raw_output_text regression: dict-return TOOL fixture (ux_agent.py실측) ────

FIXT_DICT_RAW = Path(__file__).parent / "fixtures" / "openinference_dict_tool_raw.json"


def _create_ticket_spans(trace):
    return [s for s in trace.spans if s.span_kind == "tool" and s.agent_or_node_id == "create_ticket"]


def test_dict_tool_raw_fixture_ingests():
    """Fixture parses cleanly and contains the expected create_ticket pair."""
    trace = ingest_from_otel_json(FIXT_DICT_RAW)
    tickets = _create_ticket_spans(trace)
    assert len(tickets) == 2, f"expected 2 create_ticket spans, got {len(tickets)}"


def test_dict_tool_raw_preserves_original_payload_in_raw_output_text():
    """T-1: preprocess extracts 'Login broken' into output_text but keeps the
    original dict-return JSON in raw_output_text. AGENT/CHAIN spans stay None
    on raw_output_text because the tool-branch is what populates it."""
    trace = ingest_from_otel_json(FIXT_DICT_RAW)
    tickets = _create_ticket_spans(trace)

    for span in tickets:
        assert span.output_text == "Login broken", (
            f"processed leaf should be the title, got {span.output_text!r}"
        )
        assert span.raw_output_text is not None, (
            f"raw_output_text should preserve original JSON for tool spans, got None"
        )
        assert '"ticket"' in span.raw_output_text and '"id"' in span.raw_output_text
    ids = sorted(json.loads(s.raw_output_text)["ticket"]["id"] for s in tickets)
    assert ids == ["T-1041", "T-1042"], ids

    # Non-tool spans (chain) do not populate raw_output_text.
    non_tool = [s for s in trace.spans if s.span_kind != "tool"]
    assert non_tool, "fixture should include chain spans"
    for s in non_tool:
        assert s.raw_output_text is None, (
            f"non-tool span {s.agent_or_node_id!r} unexpectedly has raw_output_text set"
        )


def test_dict_tool_raw_cascade_sha256_still_matches_across_pair():
    """T-2: cascade continues to hash the processed output_text — both
    create_ticket spans hash to the same value ("Login broken"), so the
    waste flag stays. raw_output_text is not on cascade's read path."""
    trace = ingest_from_otel_json(FIXT_DICT_RAW)
    tickets = _create_ticket_spans(trace)
    hashes = {hashlib.sha256(s.output_text.encode("utf-8")).hexdigest() for s in tickets}
    assert len(hashes) == 1, (
        f"cascade sha256 (on output_text, processed) should collapse the pair, "
        f"got {len(hashes)} distinct hashes"
    )


# ── shim symbol imports (guard against accidental deletion) ─────────────────

def test_agent_or_node_id_helper_symbol_exists():
    from clew.ingest.langgraph import _agent_or_node_id_of  # noqa: PLC0415, F401


def test_extract_tool_output_helper_symbol_exists():
    from clew.ingest.langgraph import _extract_tool_output  # noqa: PLC0415, F401
