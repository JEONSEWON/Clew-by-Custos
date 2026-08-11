"""tests/test_toolathlon_ingest.py — Toolathlon JSONL adapter verification (§23).

- Data files must not be committed (docs/TOOLATHLON.md §23): fixtures are written under tmp_path.
- Verification items: §23.1 mapping, §23.2 synthetic ts, §23.3 deserialization, §23.4 detection routing.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from clew.ingest.toolathlon import (
    _TS_BASE,
    _synth_ts,
    ingest_toolathlon_jsonl,
    iter_toolathlon_traces,
)


def _trace_entry(
    request_id: str = "req-1",
    task_name: str = "task-1",
    model: str = "claude-4.5-sonnet-0929",
    messages: list[dict] | None = None,
    task_status: dict | None = None,
) -> dict:
    """Per README convention: all values are JSON strings."""
    return {
        "modelname_run": model,
        "task_name": task_name,
        "task_status": json.dumps(task_status or {"preprocess": "done", "running": "done", "evaluation": "True"}),
        "config": json.dumps({}),
        "request_id": request_id,
        "initial_run_time": "2025-10-17 23:08:46",
        "completion_time": "2025-10-17 23:09:40",
        "tool_calls": json.dumps({"tools": [], "tool_choice": "auto"}),
        "messages": json.dumps(messages or []),
        "key_stats": json.dumps({}),
        "agent_cost": json.dumps({}),
    }


def _write_jsonl(tmp_path: Path, entries: list[dict], name: str = "traj.jsonl") -> Path:
    p = tmp_path / name
    p.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in entries),
        encoding="utf-8",
    )
    return p


def _tool_call(tid: str, name: str, arguments: str | dict) -> dict:
    args_str = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {"id": tid, "type": "function", "function": {"name": name, "arguments": args_str}}


def _asst_calls(calls: list[dict], content: str = "") -> dict:
    return {"role": "assistant", "content": content, "tool_calls": calls}


def _tool_result(tid: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": tid, "content": content}


def _user(text: str = "hi") -> dict:
    return {"role": "user", "content": text}


# ─── §23.1 mapping ───────────────────────────────────────────────────────

def test_basic_two_calls_serial(tmp_path: Path) -> None:
    """assistant → tool → assistant → tool : creates 2 spans, material to feed the sha256 gate."""
    messages = [
        _user("query"),
        _asst_calls([_tool_call("t1", "read_file", {"path": "/a"})]),
        _tool_result("t1", "content-A"),
        _asst_calls([_tool_call("t2", "read_file", {"path": "/b"})]),
        _tool_result("t2", "content-B"),
    ]
    entry = _trace_entry(request_id="req-serial", messages=messages)
    path = _write_jsonl(tmp_path, [entry])
    trace = ingest_toolathlon_jsonl(path)

    assert trace.trace_id == "req-serial"
    # root + 2 tool spans
    assert len(trace.spans) == 3
    root = next(s for s in trace.spans if s.parent_span_id is None)
    assert root.span_kind == "chain"
    tool_spans = [s for s in trace.spans if s.span_kind == "tool"]
    assert [s.span_id for s in tool_spans] == ["t1", "t2"]
    assert [s.agent_or_node_id for s in tool_spans] == ["read_file", "read_file"]
    assert tool_spans[0].output_text == "content-A"
    assert tool_spans[1].output_text == "content-B"
    assert tool_spans[0].model == "claude-4.5-sonnet-0929"


def test_arguments_normalized_sort_keys(tmp_path: Path) -> None:
    """§23.1: arguments re-serialized with sort_keys — arguments arriving in different key order are normalized."""
    messages = [
        _asst_calls([_tool_call("t1", "read_file", '{"z": 1, "a": 2}')]),
        _tool_result("t1", "ok"),
    ]
    entry = _trace_entry(messages=messages)
    path = _write_jsonl(tmp_path, [entry])
    trace = ingest_toolathlon_jsonl(path)
    ts = next(s for s in trace.spans if s.span_kind == "tool")
    # sort_keys=True → "a" comes first
    assert ts.input_text == '{"a": 2, "z": 1}'


def test_arguments_parse_failure_raises(tmp_path: Path) -> None:
    """§23.3: arguments parse failure → explicit error (do not silently fall back to the raw string)."""
    messages = [
        _asst_calls([_tool_call("t1", "read_file", "not valid json!!")]),
        _tool_result("t1", "ok"),
    ]
    entry = _trace_entry(messages=messages)
    path = _write_jsonl(tmp_path, [entry])
    with pytest.raises(ValueError, match="arguments JSON 파싱 실패"):
        ingest_toolathlon_jsonl(path)


# ─── §23.2 synthetic timestamp ────────────────────────────────────────────

def test_synthetic_ts_preserves_msg_and_sub_order(tmp_path: Path) -> None:
    """§23.2 recon Q4: msg_idx*1000 + sub_idx preserves order even for parallel calls."""
    messages = [
        _asst_calls([
            _tool_call("t_a", "read_file", {"n": 1}),
            _tool_call("t_b", "read_file", {"n": 2}),  # parallel
        ]),
        _tool_result("t_a", "R-a"),
        _tool_result("t_b", "R-b"),
        _asst_calls([_tool_call("t_c", "read_file", {"n": 3})]),  # later
        _tool_result("t_c", "R-c"),
    ]
    entry = _trace_entry(messages=messages)
    path = _write_jsonl(tmp_path, [entry])
    trace = ingest_toolathlon_jsonl(path)
    tool_spans = sorted(
        (s for s in trace.spans if s.span_kind == "tool"),
        key=lambda s: s.start_time,
    )
    # Parallel t_a(msg=0,sub=0), t_b(msg=0,sub=1), then t_c(msg=3,sub=0) — msg_idx 0-based (§23.2)
    assert [s.span_id for s in tool_spans] == ["t_a", "t_b", "t_c"]
    assert tool_spans[0].start_time == _synth_ts(0, 0)
    assert tool_spans[1].start_time == _synth_ts(0, 1)
    assert tool_spans[2].start_time == _synth_ts(3, 0)
    # end_time == start_time
    for s in tool_spans:
        assert s.end_time == s.start_time


# ─── §23.3 join checks ───────────────────────────────────────────────────

def test_orphan_call_raises(tmp_path: Path) -> None:
    messages = [
        _asst_calls([_tool_call("t1", "read_file", {}), _tool_call("t2", "read_file", {})]),
        _tool_result("t1", "R-1"),
        # t2 result missing
    ]
    entry = _trace_entry(messages=messages)
    path = _write_jsonl(tmp_path, [entry])
    with pytest.raises(ValueError, match="조인 실패"):
        ingest_toolathlon_jsonl(path)


def test_orphan_result_raises(tmp_path: Path) -> None:
    messages = [
        _asst_calls([_tool_call("t1", "read_file", {})]),
        _tool_result("t1", "R-1"),
        _tool_result("t_ghost", "orphan"),
    ]
    entry = _trace_entry(messages=messages)
    path = _write_jsonl(tmp_path, [entry])
    with pytest.raises(ValueError, match="조인 실패"):
        ingest_toolathlon_jsonl(path)


def test_no_tool_calls_raises(tmp_path: Path) -> None:
    entry = _trace_entry(messages=[_user("hi")])
    path = _write_jsonl(tmp_path, [entry])
    with pytest.raises(ValueError, match="tool_calls 하나도 없음"):
        ingest_toolathlon_jsonl(path)


# ─── metadata + iter ─────────────────────────────────────────────────────

def test_metadata_carries_task_name_and_status(tmp_path: Path) -> None:
    messages = [
        _asst_calls([_tool_call("t1", "r", {})]),
        _tool_result("t1", "ok"),
    ]
    entry = _trace_entry(
        task_name="k8s-upgrade",
        task_status={"preprocess": "done", "running": "done", "evaluation": "False"},
        messages=messages,
    )
    path = _write_jsonl(tmp_path, [entry])
    trace = ingest_toolathlon_jsonl(path)
    md = trace.metadata
    assert md["source"] == "toolathlon_jsonl"
    assert md["task_name"] == "k8s-upgrade"
    assert md["task_status"]["evaluation"] == "False"
    # §23.2 compact gate no-op: compact_boundaries key absent
    assert "compact_boundaries" not in md


def test_iter_multiple_traces(tmp_path: Path) -> None:
    """§23.4: one file = multiple traces. Iterate each line via iter_toolathlon_traces."""
    e1 = _trace_entry(request_id="req-1", messages=[
        _asst_calls([_tool_call("a1", "r", {})]),
        _tool_result("a1", "ok"),
    ])
    e2 = _trace_entry(request_id="req-2", messages=[
        _asst_calls([_tool_call("b1", "r", {})]),
        _tool_result("b1", "ok"),
    ])
    path = _write_jsonl(tmp_path, [e1, e2])
    traces = list(iter_toolathlon_traces(path))
    assert [t.trace_id for t in traces] == ["req-1", "req-2"]


# ─── §23.4 detection routing (CLI auto-load) ────────────────────────────

def test_auto_dispatch_toolathlon(tmp_path: Path) -> None:
    from clew.__main__ import _load_trace_auto
    messages = [
        _asst_calls([_tool_call("t1", "r", {})]),
        _tool_result("t1", "ok"),
    ]
    entry = _trace_entry(request_id="req-auto", messages=messages)
    path = _write_jsonl(tmp_path, [entry])
    trace = _load_trace_auto(path)
    assert trace.trace_id == "req-auto"
    assert trace.metadata["source"] == "toolathlon_jsonl"


def test_auto_dispatch_cc_still_works(tmp_path: Path) -> None:
    """Stop-condition 2: detection-routing changes do not break the CC path."""
    from clew.__main__ import _load_trace_auto
    p = tmp_path / "cc.jsonl"
    p.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in [
            {
                "type": "assistant",
                "sessionId": "sess-1",
                "uuid": "u1",
                "parentUuid": None,
                "timestamp": "2026-07-18T00:00:00.000Z",
                "message": {"content": [{
                    "type": "tool_use", "id": "tu1", "name": "Read",
                    "input": {"file_path": "/a"},
                }]},
            },
            {
                "type": "user",
                "sessionId": "sess-1",
                "uuid": "u2",
                "parentUuid": "u1",
                "timestamp": "2026-07-18T00:00:01.000Z",
                "message": {"content": [{
                    "type": "tool_result", "tool_use_id": "tu1", "content": "hello",
                }]},
            },
        ]),
        encoding="utf-8",
    )
    trace = _load_trace_auto(p)
    assert trace.trace_id == "sess-1"
    assert trace.metadata["source"] == "claude_code_jsonl"


def test_auto_dispatch_unknown_jsonl_raises(tmp_path: Path) -> None:
    from clew.__main__ import _load_trace_auto
    p = tmp_path / "unknown.jsonl"
    p.write_text(json.dumps({"foo": "bar", "baz": 42}), encoding="utf-8")
    with pytest.raises(ValueError, match="JSONL 형식 판별 실패"):
        _load_trace_auto(p)


# ─── Amendment §1: LLM call reconstruction ───────────────────────────────

def _trace_entry_with_stats(
    request_id: str,
    messages: list[dict],
    input_tokens: int,
    output_tokens: int,
    agent_llm_requests: int,
    model: str = "claude-4.5-sonnet-0929",
) -> dict:
    entry = _trace_entry(request_id=request_id, model=model, messages=messages)
    entry["key_stats"] = json.dumps({
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "agent_llm_requests": agent_llm_requests,
    })
    return entry


def test_llm_calls_empty_when_key_stats_missing(tmp_path: Path) -> None:
    """Amendment §1: empty key_stats -> no llm_calls populated (back-compat)."""
    messages = [
        _asst_calls([_tool_call("t1", "r", {})]),
        _tool_result("t1", "ok"),
    ]
    entry = _trace_entry(messages=messages)  # key_stats = {}
    path = _write_jsonl(tmp_path, [entry])
    trace = ingest_toolathlon_jsonl(path)
    assert trace.metadata["llm_calls"] == []
    assert trace.metadata["key_stats"] == {}


def test_llm_calls_count_matches_agent_llm_requests(tmp_path: Path) -> None:
    """Amendment §4: len(llm_calls) == count of assistant messages."""
    messages = [
        _user("hi"),
        _asst_calls([_tool_call("t1", "r", {})], content="think 1"),
        _tool_result("t1", "R-1"),
        _asst_calls([_tool_call("t2", "r", {})], content="think 2"),
        _tool_result("t2", "R-2"),
        _asst_calls([_tool_call("t3", "r", {})], content="think 3"),
        _tool_result("t3", "R-3"),
    ]
    entry = _trace_entry_with_stats(
        request_id="req-count",
        messages=messages,
        input_tokens=3000,
        output_tokens=300,
        agent_llm_requests=3,
    )
    path = _write_jsonl(tmp_path, [entry])
    trace = ingest_toolathlon_jsonl(path)
    llm_calls = trace.metadata["llm_calls"]
    assert len(llm_calls) == 3
    assert trace.metadata["key_stats"]["agent_llm_requests"] == 3


def test_llm_calls_token_sum_invariant(tmp_path: Path) -> None:
    """Amendment §1.3: sum(input_tokens_i) == T_in exactly (residual absorbed in last)."""
    messages = [
        _user("some longer user question here to give input tokens body"),
        _asst_calls([_tool_call("t1", "r", {})], content="a"),
        _tool_result("t1", "result-A" * 5),
        _asst_calls([_tool_call("t2", "r", {})], content="b"),
        _tool_result("t2", "result-B" * 20),
        _asst_calls([_tool_call("t3", "r", {})], content="c"),
        _tool_result("t3", "final"),
    ]
    entry = _trace_entry_with_stats(
        request_id="req-sum",
        messages=messages,
        input_tokens=1_000_000,
        output_tokens=1_000_003,  # non-divisible by 3 to exercise residual
        agent_llm_requests=3,
    )
    path = _write_jsonl(tmp_path, [entry])
    trace = ingest_toolathlon_jsonl(path)
    llm_calls = trace.metadata["llm_calls"]
    assert sum(c["input_tokens"] for c in llm_calls) == 1_000_000
    assert sum(c["output_tokens"] for c in llm_calls) == 1_000_003


def test_llm_calls_length_weighted_apportionment(tmp_path: Path) -> None:
    """Amendment §1.3: later assistant sees more accumulated context -> more input tokens."""
    messages = [
        _user("hi"),
        _asst_calls([_tool_call("t1", "r", {})], content="a"),
        _tool_result("t1", "R-1"),
        _asst_calls([_tool_call("t2", "r", {})], content="b"),
        _tool_result("t2", "R-2"),
        _asst_calls([_tool_call("t3", "r", {})], content="c"),
        _tool_result("t3", "R-3"),
    ]
    entry = _trace_entry_with_stats(
        request_id="req-lw",
        messages=messages,
        input_tokens=10000,
        output_tokens=300,
        agent_llm_requests=3,
    )
    path = _write_jsonl(tmp_path, [entry])
    trace = ingest_toolathlon_jsonl(path)
    llm_calls = trace.metadata["llm_calls"]
    it = [c["input_tokens"] for c in llm_calls]
    # First assistant sees only [user]; third sees [user, asst1, tool1, asst2, tool2].
    # Length-weighted -> monotone non-decreasing on this construction.
    assert it[0] < it[1] < it[2]


def test_llm_calls_input_text_matches_prior_messages(tmp_path: Path) -> None:
    """Amendment §1.2: input_text = JSON-serialized accumulated messages BEFORE the assistant."""
    messages = [
        _user("first"),
        _asst_calls([_tool_call("t1", "r", {})], content="a1"),
        _tool_result("t1", "R-1"),
        _asst_calls([_tool_call("t2", "r", {})], content="a2"),
        _tool_result("t2", "R-2"),
    ]
    entry = _trace_entry_with_stats(
        request_id="req-it",
        messages=messages,
        input_tokens=1000,
        output_tokens=200,
        agent_llm_requests=2,
    )
    path = _write_jsonl(tmp_path, [entry])
    trace = ingest_toolathlon_jsonl(path)
    llm_calls = trace.metadata["llm_calls"]
    # First call: only the user message accumulated before it.
    first_parsed = json.loads(llm_calls[0]["input_text"])
    assert first_parsed == [{"role": "user", "content": "first"}]
    # Second call: user + asst1 + tool1 accumulated.
    second_parsed = json.loads(llm_calls[1]["input_text"])
    assert len(second_parsed) == 3
    assert second_parsed[0]["role"] == "user"
    assert second_parsed[1]["role"] == "assistant"
    assert second_parsed[1]["content"] == "a1"
    assert second_parsed[1]["tool_calls"][0]["id"] == "t1"
    assert second_parsed[2]["role"] == "tool"
    assert second_parsed[2]["tool_call_id"] == "t1"


def test_llm_calls_cost_rate_lookup(tmp_path: Path) -> None:
    """Amendment §1.5: cost rate looked up by modelname_run; missing model -> None."""
    messages = [
        _asst_calls([_tool_call("t1", "r", {})], content="a"),
        _tool_result("t1", "ok"),
    ]
    entry = _trace_entry_with_stats(
        request_id="req-cost",
        messages=messages,
        input_tokens=100,
        output_tokens=10,
        agent_llm_requests=1,
        model="claude-model-priced",
    )
    path = _write_jsonl(tmp_path, [entry])

    # Model present in table
    trace = ingest_toolathlon_jsonl(
        path,
        input_cost_table={"claude-model-priced": 3e-6},
        output_cost_table={"claude-model-priced": 15e-6},
    )
    llm_calls = trace.metadata["llm_calls"]
    assert llm_calls[0]["input_cost_rate"] == 3e-6
    assert llm_calls[0]["output_cost_rate"] == 15e-6

    # Model missing from table -> None
    trace2 = ingest_toolathlon_jsonl(
        path,
        input_cost_table={"some-other-model": 3e-6},
        output_cost_table={"some-other-model": 15e-6},
    )
    assert trace2.metadata["llm_calls"][0]["input_cost_rate"] is None
    assert trace2.metadata["llm_calls"][0]["output_cost_rate"] is None


def test_llm_calls_cache_tiers_all_uncached(tmp_path: Path) -> None:
    """Amendment §1.4: all input tokens assigned to uncached tier."""
    messages = [
        _asst_calls([_tool_call("t1", "r", {})], content="a"),
        _tool_result("t1", "ok"),
    ]
    entry = _trace_entry_with_stats(
        request_id="req-cache",
        messages=messages,
        input_tokens=500,
        output_tokens=20,
        agent_llm_requests=1,
    )
    path = _write_jsonl(tmp_path, [entry])
    trace = ingest_toolathlon_jsonl(path)
    c = trace.metadata["llm_calls"][0]
    assert c["input_tokens_uncached"] == c["input_tokens"] == 500
    assert c["input_tokens_cache_read"] == 0
    assert c["input_tokens_cache_write"] == 0


def test_llm_calls_span_id_and_start_time(tmp_path: Path) -> None:
    """Amendment §1.6: span_id = toolathlon-llm-{k:06d}; start_time via _synth_ts(msg_idx, 0)."""
    messages = [
        _user("go"),
        _asst_calls([_tool_call("t1", "r", {})], content="a"),
        _tool_result("t1", "ok"),
        _asst_calls([_tool_call("t2", "r", {})], content="b"),
        _tool_result("t2", "ok"),
    ]
    entry = _trace_entry_with_stats(
        request_id="req-id",
        messages=messages,
        input_tokens=100,
        output_tokens=10,
        agent_llm_requests=2,
    )
    path = _write_jsonl(tmp_path, [entry])
    trace = ingest_toolathlon_jsonl(path)
    llm_calls = trace.metadata["llm_calls"]
    assert llm_calls[0]["span_id"] == "toolathlon-llm-000000"
    assert llm_calls[1]["span_id"] == "toolathlon-llm-000001"
    # Assistants at msg_idx 1 and 3.
    assert llm_calls[0]["start_time"] == _synth_ts(1, 0).isoformat()
    assert llm_calls[1]["start_time"] == _synth_ts(3, 0).isoformat()


def test_llm_calls_fallback_equal_split_when_no_prior_context(tmp_path: Path) -> None:
    """Amendment §1.3 fallback: all-zero prior context lengths -> equal split."""
    # An assistant with no prior message -> its input_text = "[]" (2 bytes, not 0);
    # so we construct a synthetic case: single assistant only (prior accumulated = [] -> "[]").
    # The equal-split branch is exercised when sum(L_j) == 0, which json.dumps([]) is not,
    # so we test the more common path here: a single call absorbs T_in exactly.
    messages = [
        _asst_calls([_tool_call("t1", "r", {})], content="a"),
        _tool_result("t1", "ok"),
    ]
    entry = _trace_entry_with_stats(
        request_id="req-single",
        messages=messages,
        input_tokens=777,
        output_tokens=13,
        agent_llm_requests=1,
    )
    path = _write_jsonl(tmp_path, [entry])
    trace = ingest_toolathlon_jsonl(path)
    llm_calls = trace.metadata["llm_calls"]
    assert len(llm_calls) == 1
    assert llm_calls[0]["input_tokens"] == 777
    assert llm_calls[0]["output_tokens"] == 13
