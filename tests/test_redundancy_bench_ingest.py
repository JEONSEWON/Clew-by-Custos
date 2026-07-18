"""tests/test_redundancy_bench_ingest.py — RB JSON 어댑터 검증 (§24).

- 데이터 파일 커밋 금지 (docs/REDUNDANCY_BENCH.md §24.6): fixture 는 tmp_path 에 작성.
- 검증 항목: §24.2 매핑 + requestor 필터, turn_pair metadata, 조인, 감지 분기.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from clew.ingest.redundancy_bench import (
    _TS_BASE,
    _synth_ts,
    ingest_redundancy_bench_json,
    iter_redundancy_bench_traces,
)


def _asst_msg(tool_calls: list[dict] | None = None, content: str = "", timestamp: str | None = None) -> dict:
    m: dict = {"role": "assistant", "content": content}
    if tool_calls is not None:
        m["tool_calls"] = tool_calls
    if timestamp is not None:
        m["timestamp"] = timestamp
    return m


def _user_msg(content: str = "", tool_calls: list[dict] | None = None) -> dict:
    m: dict = {"role": "user", "content": content}
    if tool_calls is not None:
        m["tool_calls"] = tool_calls
    return m


def _tool_msg(tid: str, content: str, requestor: str = "assistant") -> dict:
    return {"role": "tool", "id": tid, "content": content, "requestor": requestor}


def _tool_call(tid: str, name: str, arguments: dict | str) -> dict:
    return {"id": tid, "name": name, "arguments": arguments, "requestor": "assistant"}


def _sim(sim_id: str = "sim-1", task_id: str = "1", messages: list[dict] | None = None) -> dict:
    # turn_idx 필드 자동 부여 (recon Q3: 리스트 인덱스와 동일)
    msgs = messages or []
    for i, m in enumerate(msgs):
        m.setdefault("turn_idx", i)
    return {
        "id": sim_id,
        "task_id": task_id,
        "timestamp": "2026-01-01T00:00:00Z",
        "messages": msgs,
        "reward_info": {"reward": 1.0},
    }


def _write_rb(tmp_path: Path, sims: list[dict], name: str = "final_traces.json") -> Path:
    p = tmp_path / name
    p.write_text(
        json.dumps({"tasks": [], "simulations": sims}, ensure_ascii=False),
        encoding="utf-8",
    )
    return p


# ─── §24.2 매핑 ───────────────────────────────────────────────────────────

def test_basic_serial_pair(tmp_path: Path) -> None:
    """assistant → tool : span 1개, turn_pair 보존. span_id = tid#call_idx."""
    sim = _sim("s1", "t1", messages=[
        _user_msg("hi"),
        _asst_msg([_tool_call("c1", "get_user", {"id": 100})]),
        _tool_msg("c1", '{"name": "John"}'),
    ])
    path = _write_rb(tmp_path, [sim])
    trace = ingest_redundancy_bench_json(path)

    assert trace.trace_id == "s1"
    assert len(trace.spans) == 2  # root + 1 tool
    tool = next(s for s in trace.spans if s.span_kind == "tool")
    # RB 는 tid 재사용 → span_id = f"{tid}#{call_idx}"
    assert tool.span_id == "c1#1"
    assert tool.agent_or_node_id == "get_user"
    assert tool.output_text == '{"name": "John"}'
    # turn_pair: assistant at idx=1, tool at idx=2
    assert trace.metadata["rb_span_to_turn_pair"] == {"c1#1": [1, 2]}
    assert trace.metadata["source"] == "redundancy_bench_json"
    assert trace.metadata["rb_user_tool_idx"] == []


def test_duplicate_tool_call_id_split_by_occurrence(tmp_path: Path) -> None:
    """§24.2: RB 는 같은 sim 안에서 tool_call.id 재사용. FIFO 로 짝지어 span 분리."""
    sim = _sim("s-dup", messages=[
        _asst_msg([_tool_call("call_x", "get_res", {"id": "A"})]),  # turn 0
        _tool_msg("call_x", "result-1"),                              # turn 1
        _asst_msg([_tool_call("call_x", "get_res", {"id": "A"})]),  # turn 2 (같은 tid 재사용)
        _tool_msg("call_x", "result-2"),                              # turn 3
    ])
    path = _write_rb(tmp_path, [sim])
    trace = ingest_redundancy_bench_json(path)

    tool_spans = sorted(
        (s for s in trace.spans if s.span_kind == "tool"), key=lambda s: s.start_time
    )
    assert [s.span_id for s in tool_spans] == ["call_x#0", "call_x#2"]
    assert [s.output_text for s in tool_spans] == ["result-1", "result-2"]
    assert trace.metadata["rb_span_to_turn_pair"] == {
        "call_x#0": [0, 1],
        "call_x#2": [2, 3],
    }


def test_arguments_normalized_sort_keys(tmp_path: Path) -> None:
    """§24.2: arguments dict → sort_keys 재직렬화."""
    sim = _sim(messages=[
        _asst_msg([_tool_call("c1", "read_file", {"z": 1, "a": 2})]),
        _tool_msg("c1", "content"),
    ])
    path = _write_rb(tmp_path, [sim])
    trace = ingest_redundancy_bench_json(path)
    tool = next(s for s in trace.spans if s.span_kind == "tool")
    assert tool.input_text == '{"a": 2, "z": 1}'


def test_arguments_str_form_parsed(tmp_path: Path) -> None:
    """안전장치: arguments 가 str 로 오는 경우도 처리."""
    sim = _sim(messages=[
        _asst_msg([_tool_call("c1", "read_file", '{"a": 1}')]),
        _tool_msg("c1", "content"),
    ])
    path = _write_rb(tmp_path, [sim])
    trace = ingest_redundancy_bench_json(path)
    tool = next(s for s in trace.spans if s.span_kind == "tool")
    assert tool.input_text == '{"a": 1}'


def test_arguments_invalid_raises(tmp_path: Path) -> None:
    sim = _sim(messages=[
        _asst_msg([_tool_call("c1", "r", "not-json!!")]),
        _tool_msg("c1", "x"),
    ])
    path = _write_rb(tmp_path, [sim])
    with pytest.raises(ValueError, match="arguments JSON 파싱 실패"):
        ingest_redundancy_bench_json(path)


# ─── §24.2 requestor 필터 (telecom 사용자 시뮬) ─────────────────────────

def test_user_requestor_tool_excluded(tmp_path: Path) -> None:
    """role=user + tool_calls (telecom) 는 span 화 안 됨. tool msg (requestor='user') 도 span 아님."""
    sim = _sim(messages=[
        _user_msg("hello"),
        _asst_msg([_tool_call("c_asst", "get_x", {})]),
        _tool_msg("c_asst", "asst-result", requestor="assistant"),
        # 사용자 시뮬 툴콜 (telecom 패턴)
        {"role": "user", "content": "", "tool_calls": [{"id": "c_user", "name": "device_check", "arguments": {}, "requestor": "user"}]},
        _tool_msg("c_user", "device-result", requestor="user"),
    ])
    path = _write_rb(tmp_path, [sim])
    trace = ingest_redundancy_bench_json(path)

    tool_spans = [s for s in trace.spans if s.span_kind == "tool"]
    assert [s.span_id for s in tool_spans] == ["c_asst#1"]  # c_user 제외, tid#call_idx
    # rb_user_tool_idx: turn_idx 4 (tool msg with requestor='user')
    assert trace.metadata["rb_user_tool_idx"] == [4]
    # turn_pair 는 c_asst 만
    assert trace.metadata["rb_span_to_turn_pair"] == {"c_asst#1": [1, 2]}


# ─── §24.2 timestamp ─────────────────────────────────────────────────────

def test_timestamp_uses_original_when_present(tmp_path: Path) -> None:
    sim = _sim(messages=[
        _asst_msg([_tool_call("c1", "r", {})], timestamp="2026-05-15T12:34:56Z"),
        _tool_msg("c1", "ok"),
    ])
    path = _write_rb(tmp_path, [sim])
    trace = ingest_redundancy_bench_json(path)
    tool = next(s for s in trace.spans if s.span_kind == "tool")
    # 2026-05-15T12:34:56+00:00
    assert tool.start_time.year == 2026
    assert tool.start_time.month == 5
    assert tool.start_time.hour == 12


def test_timestamp_fallback_synthetic(tmp_path: Path) -> None:
    sim = _sim(messages=[
        _asst_msg([_tool_call("c1", "r", {})]),  # no timestamp
        _tool_msg("c1", "ok"),
    ])
    path = _write_rb(tmp_path, [sim])
    trace = ingest_redundancy_bench_json(path)
    tool = next(s for s in trace.spans if s.span_kind == "tool")
    # call_turn_idx = 0 → synthetic base + 0s
    assert tool.start_time == _synth_ts(0)


# ─── §24.2 조인 ─────────────────────────────────────────────────────────

def test_orphan_call_raises(tmp_path: Path) -> None:
    sim = _sim(messages=[
        _asst_msg([_tool_call("c1", "r", {}), _tool_call("c2", "r", {})]),
        _tool_msg("c1", "ok"),
        # c2 결과 누락
    ])
    path = _write_rb(tmp_path, [sim])
    with pytest.raises(ValueError, match="조인 실패"):
        ingest_redundancy_bench_json(path)


def test_orphan_result_raises(tmp_path: Path) -> None:
    sim = _sim(messages=[
        _asst_msg([_tool_call("c1", "r", {})]),
        _tool_msg("c1", "ok"),
        _tool_msg("ghost", "orphan"),
    ])
    path = _write_rb(tmp_path, [sim])
    with pytest.raises(ValueError, match="조인 실패"):
        ingest_redundancy_bench_json(path)


def test_no_assistant_tool_calls_raises(tmp_path: Path) -> None:
    sim = _sim(messages=[
        _user_msg("hi"),
        _asst_msg([], content="just chat"),
    ])
    path = _write_rb(tmp_path, [sim])
    with pytest.raises(ValueError, match="assistant 발행 tool_calls 하나도 없음"):
        ingest_redundancy_bench_json(path)


# ─── metadata + iter ─────────────────────────────────────────────────────

def test_metadata_carries_domain_task_id(tmp_path: Path) -> None:
    sim = _sim("s7", "task_xyz", messages=[
        _asst_msg([_tool_call("c1", "r", {})]),
        _tool_msg("c1", "ok"),
    ])
    # domain 은 경로 관례로 추정
    dom_dir = tmp_path / "airline"
    dom_dir.mkdir()
    p = dom_dir / "final_traces.json"
    p.write_text(json.dumps({"tasks": [], "simulations": [sim]}), encoding="utf-8")
    trace = ingest_redundancy_bench_json(p)
    assert trace.metadata["domain"] == "airline"
    assert trace.metadata["task_id"] == "task_xyz"
    assert trace.metadata["sim_id"] == "s7"
    # compact_boundaries 키 없음 (compact 게이트 no-op)
    assert "compact_boundaries" not in trace.metadata


def test_iter_multiple_sims(tmp_path: Path) -> None:
    sim1 = _sim("s1", messages=[
        _asst_msg([_tool_call("c1", "r", {})]),
        _tool_msg("c1", "ok"),
    ])
    sim2 = _sim("s2", messages=[
        _asst_msg([_tool_call("c2", "r", {})]),
        _tool_msg("c2", "ok"),
    ])
    path = _write_rb(tmp_path, [sim1, sim2])
    traces = list(iter_redundancy_bench_traces(path))
    assert [t.trace_id for t in traces] == ["s1", "s2"]


# ─── §24.4 감지 분기 (CLI auto-load) ─────────────────────────────────────

def test_auto_dispatch_redundancy_bench(tmp_path: Path) -> None:
    from clew.__main__ import _load_trace_auto
    sim = _sim("s-auto", messages=[
        _asst_msg([_tool_call("c1", "r", {})]),
        _tool_msg("c1", "ok"),
    ])
    path = _write_rb(tmp_path, [sim])
    trace = _load_trace_auto(path)
    assert trace.trace_id == "s-auto"
    assert trace.metadata["source"] == "redundancy_bench_json"


def test_auto_dispatch_clew_trace_json_still_works(tmp_path: Path) -> None:
    """중단조건 2: RB 분기 추가가 Clew Trace JSON 경로를 안 깬다."""
    from clew.__main__ import _load_trace_auto
    p = tmp_path / "trace.json"
    p.write_text(json.dumps({
        "trace_id": "t1",
        "spans": [{
            "trace_id": "t1", "span_id": "r", "parent_span_id": None,
            "agent_or_node_id": "root", "span_kind": "chain",
            "start_time": "2026-01-01T00:00:00+00:00",
            "end_time": "2026-01-01T00:00:01+00:00",
            "input_text": "", "output_text": "root", "token_count": None,
        }],
    }), encoding="utf-8")
    trace = _load_trace_auto(p)
    assert trace.trace_id == "t1"
