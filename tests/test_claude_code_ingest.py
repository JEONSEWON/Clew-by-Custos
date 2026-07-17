"""tests/test_claude_code_ingest.py — CC JSONL 어댑터 검증.

- transcript 커밋 금지 (§22): fixture 는 tmp_path 에 문자열로 작성.
- 검증 항목: §22.3, §22.4 사전등록 규약.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from clew.ingest.claude_code import ingest_claude_code_jsonl


def _line(**kw) -> str:
    return json.dumps(kw, ensure_ascii=False)


def _write_jsonl(tmp_path: Path, entries: list[dict]) -> Path:
    p = tmp_path / "session.jsonl"
    p.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries), encoding="utf-8")
    return p


def _asst(uuid: str, parent: str | None, ts: str, blocks: list[dict], sid: str = "s1") -> dict:
    return {
        "type": "assistant",
        "sessionId": sid,
        "uuid": uuid,
        "parentUuid": parent,
        "timestamp": ts,
        "message": {"content": blocks},
    }


def _user(uuid: str, parent: str | None, ts: str, blocks: list[dict], sid: str = "s1") -> dict:
    return {
        "type": "user",
        "sessionId": sid,
        "uuid": uuid,
        "parentUuid": parent,
        "timestamp": ts,
        "message": {"content": blocks},
    }


def test_thinking_and_text_do_not_create_spans(tmp_path: Path) -> None:
    """§22.3: thinking / assistant text / user text 는 스팬 만들지 않는다."""
    entries = [
        _asst("a1", None, "2026-07-17T10:00:00Z", [
            {"type": "thinking", "thinking": "", "signature": "sig1"},
            {"type": "text", "text": "let me read file"},
            {"type": "tool_use", "id": "tu1", "name": "Read", "input": {"file_path": "/x"}},
        ]),
        _user("u1", "a1", "2026-07-17T10:00:05Z", [
            {"type": "tool_result", "tool_use_id": "tu1", "content": "file contents"},
        ]),
        _asst("a2", "u1", "2026-07-17T10:00:10Z", [
            {"type": "thinking", "thinking": "", "signature": "sig2"},
            {"type": "tool_use", "id": "tu2", "name": "Bash", "input": {"cmd": "ls"}},
        ]),
        _user("u2", "a2", "2026-07-17T10:00:15Z", [
            {"type": "tool_result", "tool_use_id": "tu2", "content": "a b c"},
        ]),
    ]
    p = _write_jsonl(tmp_path, entries)
    trace = ingest_claude_code_jsonl(p)
    # 2 tool 스팬 + 1 synthetic root = 3
    assert len(trace.spans) == 3
    tool_spans = [s for s in trace.spans if s.span_kind == "tool"]
    assert len(tool_spans) == 2
    names = {s.agent_or_node_id for s in tool_spans}
    assert names == {"Read", "Bash"}


def test_input_text_sort_keys_determinism(tmp_path: Path) -> None:
    """§22.2: 키 순서 다른 동일 입력 → 같은 input_text 문자열."""
    entries = [
        _asst("a1", None, "2026-07-17T10:00:00Z", [
            {"type": "tool_use", "id": "tu1", "name": "Read",
             "input": {"limit": 10, "file_path": "/x", "offset": 0}},
        ]),
        _user("u1", "a1", "2026-07-17T10:00:05Z", [
            {"type": "tool_result", "tool_use_id": "tu1", "content": "same content"},
        ]),
        _asst("a2", "u1", "2026-07-17T10:00:10Z", [
            {"type": "tool_use", "id": "tu2", "name": "Read",
             "input": {"file_path": "/x", "offset": 0, "limit": 10}},
        ]),
        _user("u2", "a2", "2026-07-17T10:00:15Z", [
            {"type": "tool_result", "tool_use_id": "tu2", "content": "same content"},
        ]),
    ]
    p = _write_jsonl(tmp_path, entries)
    trace = ingest_claude_code_jsonl(p)
    tool_spans = sorted(
        (s for s in trace.spans if s.span_kind == "tool"),
        key=lambda s: s.start_time,
    )
    assert tool_spans[0].input_text == tool_spans[1].input_text


def test_end_time_is_tool_result_timestamp(tmp_path: Path) -> None:
    """§22.1: end_time = tool_result 라인의 timestamp (근사 아님)."""
    entries = [
        _asst("a1", None, "2026-07-17T10:00:00Z", [
            {"type": "tool_use", "id": "tu1", "name": "Read", "input": {"file_path": "/x"}},
        ]),
        _user("u1", "a1", "2026-07-17T10:00:07Z", [
            {"type": "tool_result", "tool_use_id": "tu1", "content": "text"},
        ]),
    ]
    p = _write_jsonl(tmp_path, entries)
    trace = ingest_claude_code_jsonl(p)
    span = next(s for s in trace.spans if s.span_kind == "tool")
    assert span.start_time.isoformat().startswith("2026-07-17T10:00:00")
    assert span.end_time.isoformat().startswith("2026-07-17T10:00:07")


def test_orphan_tool_use_raises(tmp_path: Path) -> None:
    """§22.4 중단 조건 2: 고아 tool_use → 명시적 에러."""
    entries = [
        _asst("a1", None, "2026-07-17T10:00:00Z", [
            {"type": "tool_use", "id": "tu1", "name": "Read", "input": {"file_path": "/x"}},
        ]),
        # tool_result 없음
    ]
    p = _write_jsonl(tmp_path, entries)
    with pytest.raises(ValueError, match="조인 실패"):
        ingest_claude_code_jsonl(p)


def test_orphan_tool_result_raises(tmp_path: Path) -> None:
    """§22.4: 고아 tool_result → 명시적 에러."""
    entries = [
        _user("u1", None, "2026-07-17T10:00:05Z", [
            {"type": "tool_result", "tool_use_id": "tu-missing", "content": "orphan"},
        ]),
        _asst("a1", "u1", "2026-07-17T10:00:10Z", [
            {"type": "tool_use", "id": "tu1", "name": "Read", "input": {"file_path": "/x"}},
        ]),
        _user("u2", "a1", "2026-07-17T10:00:15Z", [
            {"type": "tool_result", "tool_use_id": "tu1", "content": "ok"},
        ]),
    ]
    p = _write_jsonl(tmp_path, entries)
    with pytest.raises(ValueError, match="조인 실패"):
        ingest_claude_code_jsonl(p)


def test_empty_tool_result_content_raises(tmp_path: Path) -> None:
    """§22.4 중단 조건 1: 빈 output_text → Pydantic validator 가 raise (placeholder 금지)."""
    entries = [
        _asst("a1", None, "2026-07-17T10:00:00Z", [
            {"type": "tool_use", "id": "tu1", "name": "Bash", "input": {"cmd": "true"}},
        ]),
        _user("u1", "a1", "2026-07-17T10:00:05Z", [
            {"type": "tool_result", "tool_use_id": "tu1", "content": ""},
        ]),
    ]
    p = _write_jsonl(tmp_path, entries)
    with pytest.raises(ValidationError, match="output_text must be non-empty"):
        ingest_claude_code_jsonl(p)


def test_tool_result_list_content(tmp_path: Path) -> None:
    """§22.5: content 가 list-of-blocks 이고 모두 text 일 때 '\\n' 결합."""
    entries = [
        _asst("a1", None, "2026-07-17T10:00:00Z", [
            {"type": "tool_use", "id": "tu1", "name": "Read", "input": {"file_path": "/x"}},
        ]),
        _user("u1", "a1", "2026-07-17T10:00:05Z", [
            {"type": "tool_result", "tool_use_id": "tu1",
             "content": [
                 {"type": "text", "text": "part1"},
                 {"type": "text", "text": "part2"},
             ]},
        ]),
    ]
    p = _write_jsonl(tmp_path, entries)
    trace = ingest_claude_code_jsonl(p)
    span = next(s for s in trace.spans if s.span_kind == "tool")
    assert span.output_text == "part1\npart2"


def test_tool_result_non_text_block_serialized(tmp_path: Path) -> None:
    """§22.5: 비-text 블록 (tool_reference 등) 은 json.dumps 로 직렬화 + warn."""
    import warnings as _w
    entries = [
        _asst("a1", None, "2026-07-17T10:00:00Z", [
            {"type": "tool_use", "id": "tu1", "name": "ToolSearch",
             "input": {"query": "x"}},
        ]),
        _user("u1", "a1", "2026-07-17T10:00:05Z", [
            {"type": "tool_result", "tool_use_id": "tu1",
             "content": [
                 {"type": "tool_reference", "tool_name": "TaskCreate"},
                 {"type": "tool_reference", "tool_name": "TaskList"},
             ]},
        ]),
    ]
    p = _write_jsonl(tmp_path, entries)
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        trace = ingest_claude_code_jsonl(p)
    span = next(s for s in trace.spans if s.span_kind == "tool")
    # 결정론 확인: sort_keys 로 tool_name 이 type 앞에 옴
    assert span.output_text == (
        '{"tool_name": "TaskCreate", "type": "tool_reference"}\n'
        '{"tool_name": "TaskList", "type": "tool_reference"}'
    )
    # 신호 유지 확인: 각 블록마다 경고
    tref_warnings = [w for w in caught if "tool_reference" in str(w.message)]
    assert len(tref_warnings) == 2


def test_tool_result_mixed_text_and_nontext(tmp_path: Path) -> None:
    """§22.5: text + 비-text 혼합 시 순서 유지 + '\\n' 결합."""
    entries = [
        _asst("a1", None, "2026-07-17T10:00:00Z", [
            {"type": "tool_use", "id": "tu1", "name": "X", "input": {}},
        ]),
        _user("u1", "a1", "2026-07-17T10:00:05Z", [
            {"type": "tool_result", "tool_use_id": "tu1",
             "content": [
                 {"type": "text", "text": "hello"},
                 {"type": "image", "source": {"data": "base64..."}},
             ]},
        ]),
    ]
    p = _write_jsonl(tmp_path, entries)
    trace = ingest_claude_code_jsonl(p)
    span = next(s for s in trace.spans if s.span_kind == "tool")
    assert span.output_text.startswith("hello\n{")
    assert '"type": "image"' in span.output_text


def test_duplicate_tool_use_id_raises(tmp_path: Path) -> None:
    """동일 tool_use.id 재사용 → 명시적 에러."""
    entries = [
        _asst("a1", None, "2026-07-17T10:00:00Z", [
            {"type": "tool_use", "id": "tu1", "name": "Read", "input": {"file_path": "/x"}},
        ]),
        _user("u1", "a1", "2026-07-17T10:00:05Z", [
            {"type": "tool_result", "tool_use_id": "tu1", "content": "ok"},
        ]),
        _asst("a2", "u1", "2026-07-17T10:00:10Z", [
            {"type": "tool_use", "id": "tu1", "name": "Read", "input": {"file_path": "/y"}},
        ]),
    ]
    p = _write_jsonl(tmp_path, entries)
    with pytest.raises(ValueError, match="중복 tool_use.id"):
        ingest_claude_code_jsonl(p)
