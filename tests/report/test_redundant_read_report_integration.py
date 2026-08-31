"""tests/report/test_redundant_read_report_integration.py — prereg §7.2.

Locks the report integration contract for the Redundant Read Detector:
optional param, backward compat when None/empty, content when populated.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from clew.detect.cascade import CascadeResult
from clew.detect.redundant_read import (
    RedundantReadEvent,
    RedundantReadResult,
)
from clew.model import Span, Trace
from clew.report.json_report import render_json
from clew.report.markdown import render_markdown


def _root_trace() -> Trace:
    root = Span(
        trace_id="T", span_id="root", parent_span_id=None,
        agent_or_node_id="root", span_kind="chain",
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        input_text="", output_text="[root]",
    )
    return Trace(trace_id="T", spans=[root], metadata={})


def _empty_cascade() -> CascadeResult:
    return CascadeResult(trace_id="T", wasteful=False)


def _populated_result() -> RedundantReadResult:
    return RedundantReadResult(
        trace_id="T",
        events=[
            RedundantReadEvent(
                read_span_id="b",
                origin_read_span_id="a",
                tool_name="Read",
                target="/tmp/foo.py",
                waste_tokens=500,
                waste_cost=0.0015,
                confirmed=True,
            ),
            RedundantReadEvent(
                read_span_id="d",
                origin_read_span_id="c",
                tool_name="Grep",
                target="pattern-hash-abc",
                waste_tokens=200,
                waste_cost=0.0006,
                confirmed=False,
            ),
        ],
        total_waste_tokens=700,
        total_waste_cost=0.0021,
        cost_accuracy_flag="accurate",
    )


# ── backward compat gates ──────────────────────────────────────────────────

def test_markdown_backward_compat_when_redundant_read_omitted():
    """Omitting the new parameter must not add any Redundant reads content."""
    md = render_markdown(_root_trace(), _empty_cascade(), details=[])
    assert "Redundant reads" not in md
    assert "redundant_read" not in md.lower()


def test_json_backward_compat_when_redundant_read_omitted():
    """Omitting the new parameter must not add any redundant_read key."""
    js = json.loads(render_json(_root_trace(), _empty_cascade(), details=[]))
    assert js.get("redundant_read") is None


def test_markdown_backward_compat_with_empty_result():
    """Passing an empty RedundantReadResult also produces no section."""
    empty = RedundantReadResult(trace_id="T")
    md = render_markdown(
        _root_trace(), _empty_cascade(), details=[], redundant_read=empty,
    )
    assert "Redundant reads" not in md


def test_json_backward_compat_with_empty_result():
    """Empty result → key present but value is None."""
    empty = RedundantReadResult(trace_id="T")
    js = json.loads(render_json(
        _root_trace(), _empty_cascade(), details=[], redundant_read=empty,
    ))
    assert js.get("redundant_read") is None


# ── content rendering ──────────────────────────────────────────────────────

def test_render_markdown_includes_section_with_events():
    """Populated result → `## Redundant reads` section with top offenders."""
    md = render_markdown(
        _root_trace(), _empty_cascade(), details=[],
        redundant_read=_populated_result(),
    )
    assert "## Redundant reads" in md
    assert "Read" in md
    assert "/tmp/foo.py" in md


def test_render_json_includes_redundant_read_block():
    """Populated result → JSON has redundant_read block with shape."""
    js = json.loads(render_json(
        _root_trace(), _empty_cascade(), details=[],
        redundant_read=_populated_result(),
    ))
    block = js["redundant_read"]
    assert block is not None
    assert block["n_events"] == 2
    assert block["total_waste_tokens"] == 700
    assert block["cost_accuracy_flag"] == "accurate"
    assert len(block["events"]) == 2
    # Every event serialized with expected keys.
    for ev in block["events"]:
        assert set(ev.keys()) == {
            "read_span_id", "origin_read_span_id", "tool_name",
            "target", "waste_tokens", "waste_cost", "confirmed",
        }


def test_cost_summary_breakdown_includes_redundant_read():
    """Populated result → detector_breakdown['redundant_read'] in cost_summary."""
    js = json.loads(render_json(
        _root_trace(), _empty_cascade(), details=[],
        redundant_read=_populated_result(),
    ))
    breakdown = js["cost_summary"]["detector_breakdown"]
    assert "redundant_read" in breakdown
    assert breakdown["redundant_read"] == pytest.approx(0.0021)
