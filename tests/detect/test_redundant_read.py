"""tests/detect/test_redundant_read.py — Redundant Read Detector prereg §7.1.

Locks the detection contract for redundant reads: same read tool + same
target + no intervening write + shell-conservative gate + SPEC §16
parent-AGENT gate. Cost via tier-aware pricing from the next LLM call.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


from clew.detect.redundant_read import find_redundant_reads
from clew.model import Span, Trace


def _t(offset_sec: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset_sec)


def _mk_span(
    span_id: str, parent: str | None, kind: str, tool: str,
    input_text: str, output_text: str,
    start_sec: int, dur_sec: int = 1,
) -> Span:
    return Span(
        trace_id="T",
        span_id=span_id,
        parent_span_id=parent,
        agent_or_node_id=tool,
        span_kind=kind,
        start_time=_t(start_sec),
        end_time=_t(start_sec + dur_sec),
        input_text=input_text,
        output_text=output_text,
    )


def _mk_llm_call(
    span_id: str, start_sec: int,
    input_tokens: int = 100, model: str = "claude-sonnet-4-5",
) -> dict[str, Any]:
    return {
        "span_id": span_id,
        "input_text": "[]",
        "input_tokens": input_tokens,
        "output_tokens": 20,
        "input_tokens_uncached": input_tokens,
        "input_tokens_cache_read": 0,
        "input_tokens_cache_write": 0,
        "input_cost_rate": None,
        "output_cost_rate": None,
        "cost_rate_legacy": None,
        "model": model,
        "start_time": _t(start_sec).isoformat(),
    }


def _trace(spans: list[Span], llm_calls: list[dict[str, Any]] | None = None) -> Trace:
    root = Span(
        trace_id="T", span_id="root", parent_span_id=None,
        agent_or_node_id="root", span_kind="chain",
        start_time=_t(0), end_time=_t(1000),
        input_text="", output_text="[root]",
    )
    md: dict[str, Any] = {}
    if llm_calls is not None:
        md["llm_calls"] = llm_calls
    all_spans = [root] + spans
    return Trace(trace_id="T", spans=all_spans, metadata=md)


# ── unit tests ──────────────────────────────────────────────────────────────

def test_two_reads_same_file_no_writes_flagged():
    """Two Read calls on same path, no intervening write → one event, confirmed=True."""
    a = _mk_span("a", "root", "tool", "Read",
                 '{"file_path": "/tmp/x.py"}', "print('hi')", 10)
    b = _mk_span("b", "root", "tool", "Read",
                 '{"file_path": "/tmp/x.py"}', "print('hi')", 20)
    trace = _trace([a, b], [_mk_llm_call("llm-1", 30)])

    r = find_redundant_reads(trace)
    assert len(r.events) == 1
    assert r.events[0].confirmed is True
    assert r.events[0].tool_name == "Read"


def test_intervening_write_same_path_skips():
    """Read → Write(same path) → Read → zero events."""
    a = _mk_span("a", "root", "tool", "Read",
                 '{"file_path": "/tmp/x.py"}', "v1", 10)
    w = _mk_span("w", "root", "tool", "Write",
                 '{"file_path": "/tmp/x.py"}', "written", 15)
    b = _mk_span("b", "root", "tool", "Read",
                 '{"file_path": "/tmp/x.py"}', "v2", 20)
    trace = _trace([a, w, b])
    r = find_redundant_reads(trace)
    assert r.events == []


def test_intervening_write_different_path_no_skip():
    """Read(A) → Write(B) → Read(A) → one event (write was different path)."""
    a = _mk_span("a", "root", "tool", "Read",
                 '{"file_path": "/tmp/a.py"}', "v", 10)
    w = _mk_span("w", "root", "tool", "Write",
                 '{"file_path": "/tmp/b.py"}', "written", 15)
    b = _mk_span("b", "root", "tool", "Read",
                 '{"file_path": "/tmp/a.py"}', "v", 20)
    trace = _trace([a, w, b])
    r = find_redundant_reads(trace)
    assert len(r.events) == 1


def test_bash_between_conservative_skip():
    """Read → Bash → Read → zero (payload-opaque, conservative)."""
    a = _mk_span("a", "root", "tool", "Read",
                 '{"file_path": "/tmp/x.py"}', "v", 10)
    sh = _mk_span("sh", "root", "tool", "Bash",
                  '{"command": "echo hi"}', "hi", 15)
    b = _mk_span("b", "root", "tool", "Read",
                 '{"file_path": "/tmp/x.py"}', "v", 20)
    trace = _trace([a, sh, b])
    r = find_redundant_reads(trace)
    assert r.events == []


def test_read_via_fetch_url_normalization():
    """fetch calls with same URL modulo trailing slash → one event."""
    a = _mk_span("a", "root", "tool", "fetch-fetch_json",
                 '{"url": "https://api.example.com/data/"}', "{}", 10)
    b = _mk_span("b", "root", "tool", "fetch-fetch_json",
                 '{"url": "https://api.example.com/data"}', "{}", 20)
    trace = _trace([a, b])
    r = find_redundant_reads(trace)
    assert len(r.events) == 1


def test_search_tool_target_via_query_hash():
    """Two Grep calls with identical query args → one event via query-hash."""
    a = _mk_span("a", "root", "tool", "Grep",
                 '{"pattern": "TODO", "path": "src"}', "match1", 10)
    b = _mk_span("b", "root", "tool", "Grep",
                 '{"pattern": "TODO", "path": "src"}', "match1", 20)
    trace = _trace([a, b])
    r = find_redundant_reads(trace)
    # Grep gets a valid path in _file_path_of via "path" key.
    # If _file_path_of returns "src", the target is normalized path.
    # Either way, one event.
    assert len(r.events) == 1


def test_different_agent_parents_excluded():
    """SPEC §16 gate: reads under different AGENT ancestors excluded."""
    agent_a = _mk_span("agent_a", "root", "agent", "agent_a", "", "", 5, dur_sec=30)
    agent_b = _mk_span("agent_b", "root", "agent", "agent_b", "", "", 5, dur_sec=30)
    a = _mk_span("a", "agent_a", "tool", "Read",
                 '{"file_path": "/tmp/x.py"}', "v", 10)
    b = _mk_span("b", "agent_b", "tool", "Read",
                 '{"file_path": "/tmp/x.py"}', "v", 20)
    trace = _trace([agent_a, agent_b, a, b])
    r = find_redundant_reads(trace)
    assert r.events == []


def test_confirmed_flag_when_outputs_differ():
    """Same input, different output → event emitted, confirmed=False."""
    a = _mk_span("a", "root", "tool", "Read",
                 '{"file_path": "/tmp/x.py"}', "v1", 10)
    b = _mk_span("b", "root", "tool", "Read",
                 '{"file_path": "/tmp/x.py"}', "v2", 20)
    trace = _trace([a, b])
    r = find_redundant_reads(trace)
    assert len(r.events) == 1
    assert r.events[0].confirmed is False


def test_cost_uses_next_llm_call_rate():
    """Redundant read followed by LLM call → waste_cost uses that call's rate."""
    a = _mk_span("a", "root", "tool", "Read",
                 '{"file_path": "/tmp/x.py"}', "hello world " * 100, 10)
    b = _mk_span("b", "root", "tool", "Read",
                 '{"file_path": "/tmp/x.py"}', "hello world " * 100, 20)
    trace = _trace([a, b], [_mk_llm_call("llm-1", 25, input_tokens=1000)])

    r = find_redundant_reads(trace)
    assert len(r.events) == 1
    ev = r.events[0]
    assert ev.waste_tokens > 0
    assert ev.waste_cost > 0
    assert r.cost_accuracy_flag == "accurate"


def test_deterministic_repeat_run():
    """Prereg §5 determinism: same trace → identical result."""
    a = _mk_span("a", "root", "tool", "Read",
                 '{"file_path": "/tmp/x.py"}', "hi", 10)
    b = _mk_span("b", "root", "tool", "Read",
                 '{"file_path": "/tmp/x.py"}', "hi", 20)
    trace = _trace([a, b], [_mk_llm_call("llm-1", 25)])

    r1 = find_redundant_reads(trace)
    r2 = find_redundant_reads(trace)
    assert repr(r1) == repr(r2)
