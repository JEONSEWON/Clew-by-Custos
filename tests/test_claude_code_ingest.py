"""tests/test_claude_code_ingest.py — CC JSONL adapter verification.

- Do not commit transcripts (§22): fixtures are written as strings to tmp_path.
- Verification items: §22.3, §22.4 pre-registered contract.
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
    """§22.3: thinking / assistant text / user text do not create spans."""
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
    # 2 tool spans + 1 synthetic root = 3
    assert len(trace.spans) == 3
    tool_spans = [s for s in trace.spans if s.span_kind == "tool"]
    assert len(tool_spans) == 2
    names = {s.agent_or_node_id for s in tool_spans}
    assert names == {"Read", "Bash"}


def test_input_text_sort_keys_determinism(tmp_path: Path) -> None:
    """§22.2: identical inputs with different key order -> same input_text string."""
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
    """§22.1: end_time = timestamp of the tool_result line (not an approximation)."""
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


def test_absence_sentinel_flagged_on_tool_span(tmp_path: Path) -> None:
    """CASCADE_ABSENCE_SENTINEL_AMENDMENT_PREREG §4.3 S2: recognise this vendor's
    placeholders for absent output, and keep carrying the text.

    Claude Code writes these strings itself; grep the raw transcript, not our code.
    They are non-empty, so the Span tool-output invariant passes them through.
    """
    cases = [
        ("(Bash completed with no output)", True),
        ("  (Bash completed with no output)  ", True),   # stripped before matching
        ("No matches found\n\nFound 0 total occurrences across 0 files.", True),
        ("No matches found", True),                       # prefix rule
        ("(Bash completed with no output) plus more", False),  # exact rule, not prefix
        ("total 0\ndrwxr-xr-x", False),                   # real, if boring, output
    ]
    for i, (payload, expected) in enumerate(cases):
        entries = [
            _asst(f"a{i}", None, "2026-07-17T10:00:00Z", [
                {"type": "tool_use", "id": f"tu{i}", "name": "Bash",
                 "input": {"command": "true"}},
            ]),
            _user(f"u{i}", f"a{i}", "2026-07-17T10:00:01Z", [
                {"type": "tool_result", "tool_use_id": f"tu{i}", "content": payload},
            ]),
        ]
        trace = ingest_claude_code_jsonl(_write_jsonl(tmp_path, entries))
        span = next(s for s in trace.spans if s.span_kind == "tool")
        assert span.output_is_absent is expected, f"case {i}: {payload!r}"
        assert span.output_text == payload, "placeholder text must still be carried"


def test_orphan_tool_use_warns_and_skips(tmp_path: Path) -> None:
    """§29.1 recovery: orphan tool_use is skipped with warning (not raise).

    Two tool_uses; the second lacks a matching tool_result (session abort scenario).
    Adapter must warn once and produce a Trace containing only the paired one.
    """
    entries = [
        _asst("a1", None, "2026-07-17T10:00:00Z", [
            {"type": "tool_use", "id": "tu1", "name": "Read", "input": {"file_path": "/x"}},
        ]),
        _user("u1", "a1", "2026-07-17T10:00:05Z", [
            {"type": "tool_result", "tool_use_id": "tu1", "content": "ok"},
        ]),
        _asst("a2", "u1", "2026-07-17T10:00:10Z", [
            {"type": "tool_use", "id": "tu2", "name": "Bash", "input": {"cmd": "make"}},
        ]),
        # tu2 has no matching tool_result (session ended mid-call)
    ]
    p = _write_jsonl(tmp_path, entries)
    with pytest.warns(UserWarning, match="orphan tool_use 1건 skip"):
        trace = ingest_claude_code_jsonl(p)
    tool_ids = [s.span_id for s in trace.spans if s.span_kind == "tool"]
    assert tool_ids == ["tu1"], f"expected only tu1 span, got {tool_ids}"


def test_orphan_tool_result_raises(tmp_path: Path) -> None:
    """§22.4: orphan tool_result -> explicit error."""
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
    """§22.4 stop condition 1: empty output_text -> Pydantic validator raises (no placeholder allowed)."""
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
    """§22.5: when content is a list-of-blocks and all are text, join with '\\n'."""
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
    """§22.5: non-text blocks (e.g. tool_reference) are serialized via json.dumps + warn."""
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
    # determinism check: with sort_keys, tool_name comes before type
    assert span.output_text == (
        '{"tool_name": "TaskCreate", "type": "tool_reference"}\n'
        '{"tool_name": "TaskList", "type": "tool_reference"}'
    )
    # signal-preservation check: warning per block
    tref_warnings = [w for w in caught if "tool_reference" in str(w.message)]
    assert len(tref_warnings) == 2


def test_tool_result_mixed_text_and_nontext(tmp_path: Path) -> None:
    """§22.5: on mixed text + non-text, preserve order + join with '\\n'."""
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


def test_is_error_tool_result_is_gated(tmp_path: Path) -> None:
    """§29.2 tool-error gate: is_error=True tool_result spans are collected in metadata,
    and are excluded from waste details + amplification with explicit counts.

    Scenario: 3 tool spans.
      tu1, tu2: two identical error tool_results ("<tool_use_error>File not read")
                — would be sha256-identical → cascade flags tu2 as waste.
      tu3, tu4: two identical *normal* tool_results ("hello world")
                — sha256-identical → cascade flags tu4 as waste (kept).
    Expected: adapter puts tu1+tu2 in error_span_ids; enrich skips (tu1,tu2);
    amplification.n_skipped_error==1 (tu2 in cr.waste_span_ids gets excluded).
    """
    from clew.cost.amplification import estimate_amplification
    from clew.detect.cascade import CascadeResult
    from clew.report._enrich import enrich
    from clew.report._model import WasteDetail

    err_msg = "<tool_use_error>File has not been read yet</tool_use_error>"
    entries = [
        _asst("a1", None, "2026-07-17T10:00:00Z", [
            {"type": "tool_use", "id": "tu1", "name": "Read", "input": {"file_path": "/x"}},
        ]),
        _user("u1", "a1", "2026-07-17T10:00:05Z", [
            {"type": "tool_result", "tool_use_id": "tu1",
             "content": err_msg, "is_error": True},
        ]),
        _asst("a2", "u1", "2026-07-17T10:00:10Z", [
            {"type": "tool_use", "id": "tu2", "name": "Read", "input": {"file_path": "/y"}},
        ]),
        _user("u2", "a2", "2026-07-17T10:00:15Z", [
            {"type": "tool_result", "tool_use_id": "tu2",
             "content": err_msg, "is_error": True},
        ]),
        _asst("a3", "u2", "2026-07-17T10:00:20Z", [
            {"type": "tool_use", "id": "tu3", "name": "Bash", "input": {"cmd": "echo hi"}},
        ]),
        _user("u3", "a3", "2026-07-17T10:00:25Z", [
            {"type": "tool_result", "tool_use_id": "tu3", "content": "hello world"},
        ]),
        _asst("a4", "u3", "2026-07-17T10:00:30Z", [
            {"type": "tool_use", "id": "tu4", "name": "Bash", "input": {"cmd": "echo hi"}},
        ]),
        _user("u4", "a4", "2026-07-17T10:00:35Z", [
            {"type": "tool_result", "tool_use_id": "tu4", "content": "hello world"},
        ]),
    ]
    p = _write_jsonl(tmp_path, entries)
    trace = ingest_claude_code_jsonl(p)

    # 1) adapter collects both error tids
    assert trace.metadata["error_span_ids"] == ["tu1", "tu2"]

    # 2) enrich skips error pair, keeps normal repeat
    spans_by_id = {s.span_id: s for s in trace.spans}
    err_pair = WasteDetail(origin=spans_by_id["tu1"], candidate=spans_by_id["tu2"], cosine=1.0)
    ok_pair = WasteDetail(origin=spans_by_id["tu3"], candidate=spans_by_id["tu4"], cosine=1.0)
    result = enrich(trace, [err_pair, ok_pair])
    assert result.n_skipped_error == 1
    assert len(result.enriched) == 1
    assert result.enriched[0].detail.candidate.span_id == "tu4"

    # 3) amplification skips tu2 (in waste_span_ids ∩ error_span_ids) with explicit count
    cr = CascadeResult(
        trace_id=trace.trace_id,
        wasteful=True,
        waste_span_ids=["tu2", "tu4"],
    )
    est = estimate_amplification(cr, trace)
    assert est.n_skipped_error == 1
    assert all(ev.span_id != "tu2" for ev in est.events)


def test_duplicate_tool_use_id_raises(tmp_path: Path) -> None:
    """Reusing the same tool_use.id -> explicit error."""
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
