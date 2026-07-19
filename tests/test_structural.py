"""tests/test_structural.py — Structural candidate detection unit tests.

(i) Repeated node N=2: same agent_or_node_id appears twice → 1 pair
(ii) Ping-pong:        A→B→A→B → 2 pairs
(iii) Clean trace: empty list
(iv) No label reference: 0 occurrences of the 'labels' string in the source
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from clew.detect.structural import (
    find_candidates,
    find_pingpong_candidates,
    find_repeat_candidates,
)
from clew.model import Span, Trace


def _ts(offset: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset)


def _span(trace_id: str, sid: str, parent: str | None, agent: str, t: int, out: str = "x") -> Span:
    return Span(
        trace_id=trace_id,
        span_id=sid,
        parent_span_id=parent,
        agent_or_node_id=agent,
        span_kind="llm" if parent else "chain",
        start_time=_ts(t),
        end_time=_ts(t + 1),
        input_text="",
        output_text=out,
        token_count=10,
        model="fake",
        cost_rate=1e-6,
    )


def _trace(spans: list[Span]) -> Trace:
    return Trace(trace_id=spans[0].trace_id, spans=spans)


def test_repeat_candidates_n2_finds_pair():
    spans = [
        _span("t", "s1", None, "run", 0),
        _span("t", "s2", "s1", "analyze", 1, "first"),
        _span("t", "s3", "s1", "analyze", 2, "second"),
    ]
    pairs = find_repeat_candidates(_trace(spans), n=2)
    assert len(pairs) == 1
    origin, cand = pairs[0]
    assert origin.span_id == "s2" and cand.span_id == "s3"


def test_repeat_candidates_threshold_blocks_single_occurrence():
    """A single occurrence is not a candidate under the N=2 threshold."""
    spans = [
        _span("t", "s1", None, "run", 0),
        _span("t", "s2", "s1", "analyze", 1),
    ]
    assert find_repeat_candidates(_trace(spans), n=2) == []


def test_repeat_candidates_three_occurrences_emit_two_pairs():
    spans = [
        _span("t", "s1", None, "run", 0),
        _span("t", "s2", "s1", "analyze", 1, "a"),
        _span("t", "s3", "s1", "analyze", 2, "b"),
        _span("t", "s4", "s1", "analyze", 3, "c"),
    ]
    pairs = find_repeat_candidates(_trace(spans), n=2)
    assert sorted((o.span_id, c.span_id) for o, c in pairs) == [("s2", "s3"), ("s2", "s4")]


def test_pingpong_emits_two_pairs():
    spans = [
        _span("t", "s1", None, "run", 0),
        _span("t", "s2", "s1", "A", 1),
        _span("t", "s3", "s1", "B", 2),
        _span("t", "s4", "s1", "A", 3),
        _span("t", "s5", "s1", "B", 4),
    ]
    pairs = find_pingpong_candidates(_trace(spans))
    keys = sorted((o.span_id, c.span_id) for o, c in pairs)
    assert keys == [("s2", "s4"), ("s3", "s5")]


def test_pingpong_requires_alternation():
    """A→A→A is not ping-pong (caught only as repeated node)."""
    spans = [
        _span("t", "s1", None, "run", 0),
        _span("t", "s2", "s1", "A", 1),
        _span("t", "s3", "s1", "A", 2),
        _span("t", "s4", "s1", "A", 3),
        _span("t", "s5", "s1", "A", 4),
    ]
    assert find_pingpong_candidates(_trace(spans)) == []


def test_clean_trace_no_candidates():
    spans = [
        _span("t", "s1", None, "run", 0),
        _span("t", "s2", "s1", "start", 1),
        _span("t", "s3", "s1", "analyze", 2),
        _span("t", "s4", "s1", "report", 3),
    ]
    assert find_candidates(_trace(spans), n=2) == []


def test_find_candidates_dedupes_repeat_and_pingpong_overlap():
    """When repeat and ping-pong candidates produce the same pair, return it only once."""
    spans = [
        _span("t", "s1", None, "run", 0),
        _span("t", "s2", "s1", "A", 1),
        _span("t", "s3", "s1", "B", 2),
        _span("t", "s4", "s1", "A", 3),
        _span("t", "s5", "s1", "B", 4),
    ]
    pairs = find_candidates(_trace(spans), n=2)
    keys = sorted((o.span_id, c.span_id) for o, c in pairs)
    assert keys == [("s2", "s4"), ("s3", "s5")]


def test_invalid_n_raises():
    spans = [
        _span("t", "s1", None, "run", 0),
        _span("t", "s2", "s1", "analyze", 1),
    ]
    with pytest.raises(ValueError):
        find_repeat_candidates(_trace(spans), n=1)


def test_structural_source_does_not_reference_labels():
    """0 occurrences of the 'labels' string in structural.py source (leakage guard auxiliary)."""
    src = Path(__file__).parent.parent / "src" / "clew" / "detect" / "structural.py"
    text = src.read_text(encoding="utf-8")
    assert "labels" not in text
    assert "eval/" not in text


# ─── SPEC §8 2.1: span_kind-aware input gate (applies to tool kind only) ────────


def _tool_span(sid: str, parent: str, agent: str, t: int, input_text: str, out: str = "x") -> Span:
    return Span(
        trace_id="t",
        span_id=sid,
        parent_span_id=parent,
        agent_or_node_id=agent,
        span_kind="tool",
        start_time=_ts(t),
        end_time=_ts(t + 1),
        input_text=input_text,
        output_text=out,
        token_count=10,
        model="fake",
        cost_rate=1e-6,
    )


def _llm_span(sid: str, parent: str, agent: str, t: int, input_text: str, out: str) -> Span:
    return Span(
        trace_id="t",
        span_id=sid,
        parent_span_id=parent,
        agent_or_node_id=agent,
        span_kind="llm",
        start_time=_ts(t),
        end_time=_ts(t + 1),
        input_text=input_text,
        output_text=out,
        token_count=10,
        model="fake",
        cost_rate=1e-6,
    )


def test_tool_input_gate_blocks_different_inputs():
    """tool kind repeat + different input → not a candidate (legitimate unrelated lookup)."""
    spans = [
        _span("t", "s1", None, "run", 0),
        _tool_span("s2", "s1", "lookup", 1, input_text="customer_id=12345"),
        _tool_span("s3", "s1", "lookup", 2, input_text="customer_id=67890"),
    ]
    assert find_repeat_candidates(_trace(spans), n=2) == []


def test_tool_input_gate_passes_identical_inputs():
    """tool kind repeat + identical input → candidate emitted (re-lookup waste candidate)."""
    spans = [
        _span("t", "s1", None, "run", 0),
        _tool_span("s2", "s1", "lookup", 1, input_text="customer_id=12345"),
        _tool_span("s3", "s1", "lookup", 2, input_text="customer_id=12345"),
    ]
    pairs = find_repeat_candidates(_trace(spans), n=2)
    assert [(o.span_id, c.span_id) for o, c in pairs] == [("s2", "s3")]


def test_tool_input_gate_normalizes_whitespace_and_case():
    """SPEC §8 2.1 normalized-equal = strip()+casefold(). Equivalent under whitespace/case."""
    spans = [
        _span("t", "s1", None, "run", 0),
        _tool_span("s2", "s1", "lookup", 1, input_text="customer_id=12345"),
        _tool_span("s3", "s1", "lookup", 2, input_text="  Customer_ID=12345  "),
    ]
    pairs = find_repeat_candidates(_trace(spans), n=2)
    assert [(o.span_id, c.span_id) for o, c in pairs] == [("s2", "s3")]


def test_llm_kind_repeat_ignores_input_gate():
    """span_kind=='llm' repeat is input-difference-agnostic — candidate emitted (regression guard: other 3 patterns)."""
    spans = [
        _span("t", "s1", None, "run", 0),
        _llm_span("s2", "s1", "analyze", 1, input_text="prompt_v1", out="r1"),
        _llm_span("s3", "s1", "analyze", 2, input_text="prompt_v2_DIFFERENT", out="r2"),
    ]
    pairs = find_repeat_candidates(_trace(spans), n=2)
    assert [(o.span_id, c.span_id) for o, c in pairs] == [("s2", "s3")]


def test_tool_gate_origin_basis_recovers_aba_repeat():
    """[A(k), B(k'), A(k)] tool sequence: skip if the middle cand has input different from origin,
    a later re-occurrence with the same input is a candidate again — origin-based gate consistency."""
    spans = [
        _span("t", "s1", None, "run", 0),
        _tool_span("s2", "s1", "lookup", 1, input_text="key=A"),
        _tool_span("s3", "s1", "lookup", 2, input_text="key=B"),
        _tool_span("s4", "s1", "lookup", 3, input_text="key=A"),
    ]
    pairs = find_repeat_candidates(_trace(spans), n=2)
    assert [(o.span_id, c.span_id) for o, c in pairs] == [("s2", "s4")]


def test_repeat_same_agent_parent_fires():
    """I3: two CHAIN spans under the same parent AGENT — pass the gate, genuine repeat candidate."""
    agent = Span(
        trace_id="t", span_id="agent1", parent_span_id=None,
        agent_or_node_id="MyAgent", span_kind="agent",
        start_time=_ts(0), end_time=_ts(1),
        input_text="", output_text="agent out", token_count=10, model="fake", cost_rate=1e-6,
    )
    s1 = Span(
        trace_id="t", span_id="s1", parent_span_id="agent1",
        agent_or_node_id="Step 1", span_kind="chain",
        start_time=_ts(1), end_time=_ts(2),
        input_text="", output_text="result A", token_count=10, model="fake", cost_rate=1e-6,
    )
    s2 = Span(
        trace_id="t", span_id="s2", parent_span_id="agent1",
        agent_or_node_id="Step 1", span_kind="chain",
        start_time=_ts(2), end_time=_ts(3),
        input_text="", output_text="result B", token_count=10, model="fake", cost_rate=1e-6,
    )
    pairs = find_repeat_candidates(Trace(trace_id="t", spans=[agent, s1, s2]), n=2)
    assert [(o.span_id, c.span_id) for o, c in pairs] == [("s1", "s2")]


def test_repeat_different_agent_parent_blocked():
    """E3 regression prevention: same-named CHAIN spans under different parent AGENTs → filtered by the gate.

    E3 real-trace case: CodeAgent.run/Step 1 vs ToolCallingAgent.run/Step 1.
    Same topical vocabulary → cosine > φ, but different roles are legitimate steps → not a candidate.
    Structure: root(CHAIN) → agent1(AGENT) → s1(CHAIN, "Step 1")
                           → agent2(AGENT) → s2(CHAIN, "Step 1")
    """
    root = Span(
        trace_id="t", span_id="root", parent_span_id=None,
        agent_or_node_id="main", span_kind="chain",
        start_time=_ts(0), end_time=_ts(5),
        input_text="", output_text="root out", token_count=10, model="fake", cost_rate=1e-6,
    )
    agent1 = Span(
        trace_id="t", span_id="agent1", parent_span_id="root",
        agent_or_node_id="CodeAgent", span_kind="agent",
        start_time=_ts(1), end_time=_ts(3),
        input_text="", output_text="agent1 out", token_count=10, model="fake", cost_rate=1e-6,
    )
    agent2 = Span(
        trace_id="t", span_id="agent2", parent_span_id="root",
        agent_or_node_id="ToolCallingAgent", span_kind="agent",
        start_time=_ts(3), end_time=_ts(5),
        input_text="", output_text="agent2 out", token_count=10, model="fake", cost_rate=1e-6,
    )
    s1 = Span(
        trace_id="t", span_id="s1", parent_span_id="agent1",
        agent_or_node_id="Step 1", span_kind="chain",
        start_time=_ts(2), end_time=_ts(3),
        input_text="", output_text="Execution logs: final answer", token_count=10, model="fake", cost_rate=1e-6,
    )
    s2 = Span(
        trace_id="t", span_id="s2", parent_span_id="agent2",
        agent_or_node_id="Step 1", span_kind="chain",
        start_time=_ts(4), end_time=_ts(5),
        input_text="", output_text="Address: google: same topic search", token_count=10, model="fake", cost_rate=1e-6,
    )
    pairs = find_repeat_candidates(
        Trace(trace_id="t", spans=[root, agent1, agent2, s1, s2]), n=2
    )
    assert pairs == []


def test_repeat_mixed_depth_blocked():
    """None/ID_X: top-level span (AGENT ancestor=None) vs sub-agent child (AGENT ancestor=agent1) → FILTER.

    In a mixed trace, spans at different structural layers are not repeat candidates.
    The alternative (None → PASS) is rejected because top-level ↔ sub-agent matching can produce new false positives.
    """
    root = Span(
        trace_id="t", span_id="root", parent_span_id=None,
        agent_or_node_id="root", span_kind="chain",
        start_time=_ts(0), end_time=_ts(1),
        input_text="", output_text="root out", token_count=10, model="fake", cost_rate=1e-6,
    )
    agent1 = Span(
        trace_id="t", span_id="agent1", parent_span_id="root",
        agent_or_node_id="SubAgent", span_kind="agent",
        start_time=_ts(1), end_time=_ts(2),
        input_text="", output_text="agent out", token_count=10, model="fake", cost_rate=1e-6,
    )
    s_toplevel = Span(
        trace_id="t", span_id="s1", parent_span_id="root",
        agent_or_node_id="Step 1", span_kind="chain",
        start_time=_ts(2), end_time=_ts(3),
        input_text="", output_text="top level step", token_count=10, model="fake", cost_rate=1e-6,
    )
    s_subagent = Span(
        trace_id="t", span_id="s2", parent_span_id="agent1",
        agent_or_node_id="Step 1", span_kind="chain",
        start_time=_ts(3), end_time=_ts(4),
        input_text="", output_text="sub agent step", token_count=10, model="fake", cost_rate=1e-6,
    )
    pairs = find_repeat_candidates(
        Trace(trace_id="t", spans=[root, agent1, s_toplevel, s_subagent]), n=2
    )
    assert pairs == []


def test_c1_requery_known_hard_clean_yields_no_candidates():
    """CRITERIA C1: hard-branch instances of requery_known clean → 0 structural candidates.

    Hard-branch identification: both lookup inputs start with 'customer_id=' + have different values.
    Expect roughly ~25 out of 50 to fall into the hard branch.
    """
    from eval.generators.patterns.requery_known import make_clean

    hard_count = 0
    for seed in range(50):
        gen = make_clean(trace_id=f"t-c1-{seed}", seed=seed)
        lookups = sorted(
            (s for s in gen.trace.spans if s.agent_or_node_id == "lookup"),
            key=lambda s: s.start_time,
        )
        assert len(lookups) == 2
        is_hard = (
            lookups[0].input_text.startswith("customer_id=")
            and lookups[1].input_text.startswith("customer_id=")
            and lookups[0].input_text != lookups[1].input_text
        )
        if is_hard:
            hard_count += 1
            assert find_candidates(gen.trace, n=2) == [], (
                f"seed={seed}: candidate emitted on hard instance — input gate failed"
            )
    assert hard_count >= 10, f"too few instances fell into hard branch: {hard_count}/50"
