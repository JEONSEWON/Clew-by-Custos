"""tests/report/test_llm_judge_report_integration.py — prereg §11.3.

Locks report integration: backward compat + section presence + JSON
schema + cost_summary accuracy downgrade.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

from clew.detect.cascade import CascadeResult
from clew.detect.llm_judge.semantic_duplicate import (
    LLMJudgeMatch,
    LLMJudgeResult,
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


def _populated_result() -> LLMJudgeResult:
    return LLMJudgeResult(
        trace_id="T",
        enabled=True,
        total_judge_calls=3,
        total_judge_cost=0.0003,
        total_semantic_resent_tokens=500,
        total_semantic_resent_cost=0.0015,
        matches=[
            LLMJudgeMatch(
                kind="semantic_duplicate",
                chunk_a_hash="a" * 64,
                chunk_b_hash="b" * 64,
                origin_llm_span_id="llm-a",
                candidate_llm_span_id="llm-b",
                equivalent=True,
                confidence=0.92,
                reasoning="paraphrase of same request",
                judge_model="claude-haiku-4-5",
                judge_cost=0.0001,
            ),
        ],
    )


# ── backward compat gates ──────────────────────────────────────────────────

def test_markdown_backward_compat_when_llm_judge_omitted():
    """Omitting the new parameter must not add any LLM judge content."""
    md = render_markdown(_root_trace(), _empty_cascade(), details=[])
    assert "Semantic duplicates" not in md
    assert "LLM judge" not in md


def test_json_backward_compat_when_llm_judge_omitted():
    """Omitting the new parameter → no llm_judge key or None."""
    js = json.loads(render_json(_root_trace(), _empty_cascade(), details=[]))
    assert js.get("llm_judge") is None


def test_markdown_backward_compat_with_empty_result():
    """Passing an empty (unopened) LLMJudgeResult → no section rendered."""
    empty = LLMJudgeResult(trace_id="T", enabled=False)
    md = render_markdown(
        _root_trace(), _empty_cascade(), details=[], llm_judge=empty,
    )
    assert "Semantic duplicates" not in md


def test_json_disabled_returns_none():
    """Disabled + no matches → llm_judge JSON key is None."""
    empty = LLMJudgeResult(trace_id="T", enabled=False)
    js = json.loads(render_json(
        _root_trace(), _empty_cascade(), details=[], llm_judge=empty,
    ))
    assert js.get("llm_judge") is None


# ── content rendering ──────────────────────────────────────────────────────

def test_render_markdown_with_matches():
    """Populated result → section present with top offenders."""
    md = render_markdown(
        _root_trace(), _empty_cascade(), details=[],
        llm_judge=_populated_result(),
    )
    assert "## Semantic duplicates (LLM judge)" in md
    assert "paraphrase of same request" in md
    assert "claude-haiku-4-5" in md
    assert "non-reproducible" in md


def test_render_json_with_matches():
    """Populated result → llm_judge block with expected shape."""
    js = json.loads(render_json(
        _root_trace(), _empty_cascade(), details=[],
        llm_judge=_populated_result(),
    ))
    block = js["llm_judge"]
    assert block is not None
    assert block["enabled"] is True
    assert block["n_matches"] == 1
    assert block["total_judge_calls"] == 3
    assert len(block["matches"]) == 1
    match = block["matches"][0]
    assert set(match.keys()) == {
        "kind", "chunk_a_hash", "chunk_b_hash",
        "origin_llm_span_id", "candidate_llm_span_id",
        "equivalent", "confidence", "reasoning",
        "judge_model", "judge_cost",
    }


def test_cost_summary_accuracy_downgrades():
    """Populated matches → cost_summary accuracy_flag == 'estimated'."""
    js = json.loads(render_json(
        _root_trace(), _empty_cascade(), details=[],
        llm_judge=_populated_result(),
    ))
    assert js["cost_summary"]["accuracy_flag"] == "estimated"


def test_cost_summary_breakdown_includes_semantic_duplicate():
    """Populated matches → detector_breakdown['semantic_duplicate']."""
    js = json.loads(render_json(
        _root_trace(), _empty_cascade(), details=[],
        llm_judge=_populated_result(),
    ))
    breakdown = js["cost_summary"]["detector_breakdown"]
    assert "semantic_duplicate" in breakdown
    assert breakdown["semantic_duplicate"] == pytest.approx(0.0015)


def test_enabled_but_zero_matches_emits_block():
    """Enabled=True but no matches → block IS emitted with n_matches=0.

    Machine consumers need this to distinguish "not run" from "ran, empty".
    """
    result = LLMJudgeResult(
        trace_id="T",
        enabled=True,
        total_judge_calls=5,
        total_judge_cost=0.0005,
        total_semantic_resent_tokens=0,
        total_semantic_resent_cost=0.0,
    )
    js = json.loads(render_json(
        _root_trace(), _empty_cascade(), details=[], llm_judge=result,
    ))
    assert js["llm_judge"] is not None
    assert js["llm_judge"]["enabled"] is True
    assert js["llm_judge"]["n_matches"] == 0
