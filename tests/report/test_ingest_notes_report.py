"""tests/report/test_ingest_notes_report.py — the report says what it was
computed on.

The adapter has always warned when it dropped a tool call or rewrote a
non-text result, but the warning went to stderr, which a hosted analysis run
has no reader for. These lock the notes into both renderers, and lock the
silence when there is nothing to say.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from clew.detect.cascade import CascadeResult
from clew.model import Span, Trace
from clew.report.json_report import render_json
from clew.report.markdown import render_markdown

_T0 = datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc)


def _trace(metadata: dict | None = None, output_text: str = "[x]") -> Trace:
    spans = [
        Span(
            trace_id="t1", span_id="root", parent_span_id=None,
            agent_or_node_id="root", span_kind="chain",
            start_time=_T0, end_time=_T0, input_text="", output_text="[root]",
        ),
        Span(
            trace_id="t1", span_id="s1", parent_span_id="root",
            agent_or_node_id="Read", span_kind="tool",
            start_time=_T0, end_time=_T0, input_text="{}", output_text=output_text,
        ),
    ]
    return Trace(trace_id="t1", spans=spans, metadata=metadata or {})


def _both(trace: Trace) -> tuple[dict, str]:
    cr = CascadeResult(trace_id="t1", wasteful=False)
    return json.loads(render_json(trace, cr, details=[])), render_markdown(trace, cr, details=[])


def test_clean_trace_says_nothing() -> None:
    """Silence is the ordinary case; a section on every report gets skipped."""
    js, md = _both(_trace())
    assert js["ingest_notes"] == {}
    assert "What the numbers were computed on" not in md


def test_dropped_tool_call_is_stated_in_both_renderers() -> None:
    js, md = _both(_trace({"ingest_notes": {"orphan_tool_use_skipped": 2}}))
    assert js["ingest_notes"]["orphan_tool_use_skipped"] == 2
    assert "2 tool calls dropped" in md


def test_single_dropped_call_reads_as_singular() -> None:
    _, md = _both(_trace({"ingest_notes": {"orphan_tool_use_skipped": 1}}))
    assert "1 tool call dropped" in md
    assert "1 tool calls" not in md


def test_no_tool_use_recovery_warns_against_reading_zero_as_clean() -> None:
    _, md = _both(_trace({"ingest_notes": {"no_tool_use_recovery": True}}))
    assert "nothing to measure" in md


def test_unknown_block_types_are_named() -> None:
    _, md = _both(_trace({"ingest_notes": {"unknown_block_types": {"document": 3}}}))
    assert "`document` ×3" in md


def test_nontext_share_is_computed_against_measured_text() -> None:
    """The share must move with the trace, not be echoed from the adapter.

    Distinguishes: 20 of 40 measured characters is 50%, and a renderer that
    printed the raw character count alone would pass no matter the trace.
    """
    trace = _trace(
        {"ingest_notes": {
            "nontext_result_blocks": {"image": 1},
            "nontext_result_chars": 20,
        }},
        output_text="y" * 34,  # + "[root]" = 40 measured characters
    )
    _, md = _both(trace)
    assert "20 characters" in md
    assert "(50.0% of it)" in md


def test_negligible_nontext_share_stays_out_of_the_markdown() -> None:
    """A `tool_reference` block is ~52 characters and shows up in most
    sessions; printing that on every report is how the section gets ignored.

    Distinguishes: an ungated renderer emits the section here, on a trace
    whose non-text share is 0.5%.
    """
    trace = _trace(
        {"ingest_notes": {
            "nontext_result_blocks": {"tool_reference": 1},
            "nontext_result_chars": 1,
        }},
        output_text="y" * 194,  # + "[root]" = 200 measured characters -> 0.5%
    )
    js, md = _both(trace)
    assert "What the numbers were computed on" not in md
    # the machine-readable report still carries it - the gate is a display rule
    assert js["ingest_notes"]["nontext_result_chars"] == 1


def test_a_dropped_call_is_never_gated_away() -> None:
    """The share gate applies to the non-text line only. Something dropped is
    always worth a line, however small the trace."""
    trace = _trace(
        {"ingest_notes": {
            "orphan_tool_use_skipped": 1,
            "nontext_result_blocks": {"tool_reference": 1},
            "nontext_result_chars": 1,
        }},
        output_text="y" * 194,
    )
    _, md = _both(trace)
    assert "1 tool call dropped" in md
    assert "non-text tool results" not in md
