"""Tool mapping coverage banner + coverage_stats JSON field.

Follows docs/COVERAGE_TRANSPARENCY_PREREG.md §2.1.

Tests cover:
  - Line A always rendered (including waste-0, before early return)
  - Line B conditional on idempotent pair count > 0
  - Line ordering (A → B → Redundant-invocation candidates)
  - coverage_stats math (recognized / unique / affected pairs)
  - JSON `coverage_stats` field schema + backward compat
  - between_window_counts unchanged after coverage layer added
  - Banned-phrase guard on the new constants
  - README example carries the banner (standing rule from b23 §5)
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from clew.detect.cascade import CascadeResult
from clew.model import Span, Trace
from clew.report._enrich import coverage_stats, enrich
from clew.report._model import WasteDetail
from clew.report.json_report import render_json
from clew.report.markdown import render_markdown


def _ts(o: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=o)


def _tool_span(sid: str, tool: str, t: int, out: str = "x", tokens: int = 5) -> Span:
    return Span(
        trace_id="t", span_id=sid, parent_span_id="root",
        agent_or_node_id=tool, span_kind="tool",
        start_time=_ts(t), end_time=_ts(t),
        input_text="{}", output_text=out, token_count=tokens,
        model="fake", cost_rate=1e-6,
    )


def _root() -> Span:
    return Span(
        trace_id="t", span_id="root", parent_span_id=None,
        agent_or_node_id="run", span_kind="chain",
        start_time=_ts(0), end_time=_ts(9999),
        input_text="", output_text="root",
        token_count=0, model=None, cost_rate=None,
    )


def _trace(spans: list[Span]) -> Trace:
    return Trace(trace_id="t", spans=[_root(), *spans])


def _cascade_result(spans: list[Span], waste_ids: list[str]) -> CascadeResult:
    return CascadeResult(
        trace_id="t",
        wasteful=bool(waste_ids),
        waste_span_ids=waste_ids,
        waste_tokens=sum(s.token_count or 0 for s in spans if s.span_id in waste_ids),
        waste_cost=0.0,
    )


# ────────────────────────── Line A: always rendered ─────────────────────────

def test_coverage_line_a_present_in_waste_zero():
    """PREREG §1.1 Q2: line A must render before the waste-0 early return.
    A low-coverage user seeing 'no waste' alone would false-reassure themselves.
    """
    # No waste; just a couple of tool spans.
    s1 = _tool_span("s1", "filesystem-read_file", 1)
    s2 = _tool_span("s2", "some-unmapped-tool", 2)
    trace = _trace([s1, s2])
    cr = _cascade_result([s1, s2], [])
    md = render_markdown(trace, cr, [])
    assert "no waste detected" in md.lower()
    assert "Tool mapping coverage for this trace" in md, (
        "Line A must render even in waste-0 sessions "
        "(coverage banner comes before the early return)."
    )
    # Coverage number: 1 recognized (filesystem-read_file), 2 unique, 50%.
    assert "1 of 2 tools recognized" in md
    assert "50.0%" in md


def test_coverage_line_a_present_in_waste_detected():
    """Line A also renders in WASTE DETECTED, at category-breakdown → banner slot."""
    origin = _tool_span("o", "filesystem-read_file", 1)
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, cand])
    wd = WasteDetail(origin=origin, candidate=cand, cosine=1.0)
    cr = _cascade_result([origin, cand], ["c"])
    md = render_markdown(trace, cr, [wd])
    assert "Result: WASTE DETECTED" in md
    assert "Tool mapping coverage for this trace" in md


def test_coverage_line_a_math_all_recognized():
    """100% coverage renders as 100.0%."""
    origin = _tool_span("o", "filesystem-read_file", 1)
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, cand])
    wd = WasteDetail(origin=origin, candidate=cand, cosine=1.0)
    cr = _cascade_result([origin, cand], ["c"])
    md = render_markdown(trace, cr, [wd])
    assert "1 of 1 tools recognized" in md
    assert "100.0%" in md


# ────────────────────────── Line B: conditional ─────────────────────────────

def test_coverage_line_b_absent_when_no_idempotent():
    """PREREG §1.1 Q2: line B must NOT render when idempotent pair count == 0.
    Uses a side_effect pair (which does not create an idempotent count).
    """
    origin = _tool_span("o", "filesystem-write_file", 1)  # side_effect category
    cand = _tool_span("c", "filesystem-write_file", 100)
    trace = _trace([origin, cand])
    wd = WasteDetail(origin=origin, candidate=cand, cosine=1.0)
    cr = _cascade_result([origin, cand], ["c"])
    md = render_markdown(trace, cr, [wd])
    assert "Tool mapping coverage for this trace" in md  # line A yes
    assert "Idempotent pairs with unrecognized tool" not in md, (
        "Line B must not render when no idempotent pair exists."
    )


def test_coverage_line_b_present_when_idempotent_gt_zero():
    """Line B renders when at least one idempotent pair is present."""
    origin = _tool_span("o", "filesystem-read_file", 1)
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, cand])
    wd = WasteDetail(origin=origin, candidate=cand, cosine=1.0)
    cr = _cascade_result([origin, cand], ["c"])
    md = render_markdown(trace, cr, [wd])
    assert "Idempotent pairs with unrecognized tool in interval" in md
    assert "0 of 1" in md  # no unrecognized in between


def test_coverage_line_b_counts_pairs_with_unrecognized():
    """Line B increments when an unrecognized tool sits between origin and cand."""
    origin = _tool_span("o", "filesystem-read_file", 1)
    unmapped = _tool_span("um", "some-brand-new-tool", 10)
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, unmapped, cand])
    wd = WasteDetail(origin=origin, candidate=cand, cosine=1.0)
    cr = _cascade_result([origin, unmapped, cand], ["c"])
    md = render_markdown(trace, cr, [wd])
    assert "1 of 1" in md, (
        "1 idempotent pair, 1 with unrecognized tool in interval"
    )


# ────────────────────────── Line ordering ───────────────────────────────────

def test_coverage_lines_ab_before_redundant_invocation_candidates():
    """Order: category breakdown → line A → line B → Redundant-invocation candidates."""
    origin = _tool_span("o", "filesystem-read_file", 1)
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, cand])
    wd = WasteDetail(origin=origin, candidate=cand, cosine=1.0)
    cr = _cascade_result([origin, cand], ["c"])
    md = render_markdown(trace, cr, [wd])
    pos_cat = md.find("category breakdown")
    pos_a = md.find("Tool mapping coverage for this trace")
    pos_b = md.find("Idempotent pairs with unrecognized")
    pos_ric = md.find("Redundant-invocation candidates")
    assert 0 < pos_cat < pos_a < pos_b < pos_ric, (
        f"Order broken: cat={pos_cat}, a={pos_a}, b={pos_b}, ric={pos_ric}"
    )


# ────────────────────────── coverage_stats math ─────────────────────────────

def test_coverage_stats_zero_tools_trace():
    """Empty trace (no tool spans) → coverage_ratio defaults to 1.0."""
    trace = _trace([])
    cov = coverage_stats(trace, [])
    assert cov["unique_tools_in_trace"] == 0
    assert cov["recognized_tools"] == 0
    assert cov["coverage_ratio"] == 1.0
    assert cov["idempotent_pairs_total"] == 0
    assert cov["pairs_with_unrecognized_in_between"] == 0


def test_coverage_stats_mixed_bucket():
    """3 tools: 1 in _BW_SIDE_EFFECT_TOOLS, 1 in _IDEMPOTENT_TOOLS,
    1 unrecognized → recognized=2, unique=3, ratio=2/3.
    """
    s1 = _tool_span("s1", "filesystem-write_file", 1)   # bucket (1)
    s2 = _tool_span("s2", "filesystem-read_file", 2)    # bucket (2)
    s3 = _tool_span("s3", "some-unmapped-tool", 3)      # bucket (3)
    trace = _trace([s1, s2, s3])
    cov = coverage_stats(trace, [])
    assert cov["unique_tools_in_trace"] == 3
    assert cov["recognized_tools"] == 2
    assert abs(cov["coverage_ratio"] - 2 / 3) < 1e-9


# ────────────────────────── JSON schema ─────────────────────────────────────

def test_coverage_stats_json_schema():
    """JSON top-level `coverage_stats` field with 5 keys."""
    origin = _tool_span("o", "filesystem-read_file", 1)
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, cand])
    wd = WasteDetail(origin=origin, candidate=cand, cosine=1.0)
    cr = _cascade_result([origin, cand], ["c"])
    out = json.loads(render_json(trace, cr, [wd]))
    assert "coverage_stats" in out
    cov = out["coverage_stats"]
    assert set(cov.keys()) == {
        "unique_tools_in_trace",
        "recognized_tools",
        "coverage_ratio",
        "idempotent_pairs_total",
        "pairs_with_unrecognized_in_between",
    }
    assert cov["unique_tools_in_trace"] == 1
    assert cov["recognized_tools"] == 1
    assert cov["coverage_ratio"] == 1.0
    assert cov["idempotent_pairs_total"] == 1
    assert cov["pairs_with_unrecognized_in_between"] == 0


def test_coverage_stats_present_in_json_waste_zero():
    """coverage_stats field must be present even in waste-0 JSON."""
    s = _tool_span("s", "filesystem-read_file", 1)
    trace = _trace([s])
    cr = _cascade_result([s], [])
    out = json.loads(render_json(trace, cr, []))
    assert out["wasteful"] is False
    assert "coverage_stats" in out
    assert out["coverage_stats"]["unique_tools_in_trace"] == 1


def test_coverage_stats_stable():
    """Same input → same output (determinism)."""
    origin = _tool_span("o", "filesystem-read_file", 1)
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, cand])
    wd = WasteDetail(origin=origin, candidate=cand, cosine=1.0)
    cr = _cascade_result([origin, cand], ["c"])
    a = json.loads(render_json(trace, cr, [wd]))["coverage_stats"]
    b = json.loads(render_json(trace, cr, [wd]))["coverage_stats"]
    assert a == b


# ────────────────────────── Backward compat ─────────────────────────────────

def test_between_window_counts_stable_post_coverage():
    """coverage layer must not touch existing between_window_counts values."""
    origin = _tool_span("o", "filesystem-read_file", 1)
    unmapped = _tool_span("w", "some-unmapped-writer", 10)
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, unmapped, cand])
    wd = WasteDetail(origin=origin, candidate=cand, cosine=1.0)
    cr = _cascade_result([origin, unmapped, cand], ["c"])
    out = json.loads(render_json(trace, cr, [wd]))
    # unmapped tool → seen by Rule V2 step 2 as absent → no_side_effect
    assert out["between_window_counts"] == {
        "declarative": 0, "no_side_effect": 1, "payload_dependent": 0,
        "targeted_writes": 0, "high_volume": 0,
    }
    # But coverage_stats surfaces the mapping gap
    assert out["coverage_stats"]["pairs_with_unrecognized_in_between"] == 1


# ────────────────────────── §3.2 banned phrases ─────────────────────────────

_BANNED = [
    "confirmed waste", "verified waste", "proven waste",
    "waste confirmed", "waste verified",
    "guaranteed waste", "definite waste",
]


def test_no_over_claim_wording_in_banner_constants():
    """PREREG §3.2: banner constants must not carry banned phrases."""
    from clew.report.markdown import _COVERAGE_LINE_A, _COVERAGE_LINE_B
    for txt in (_COVERAGE_LINE_A, _COVERAGE_LINE_B):
        low = txt.lower()
        for phrase in _BANNED:
            assert phrase not in low, f"banned '{phrase}' in banner constant"


def test_no_over_claim_wording_in_rendered_output_with_banner():
    """Banned-phrase guard against actual rendered output (waste-0 and detected)."""
    # waste-0
    s = _tool_span("s", "filesystem-read_file", 1)
    trace = _trace([s])
    cr = _cascade_result([s], [])
    md_lower = render_markdown(trace, cr, []).lower()
    for phrase in _BANNED:
        assert phrase not in md_lower

    # waste-detected
    origin = _tool_span("o", "filesystem-read_file", 1)
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, cand])
    wd = WasteDetail(origin=origin, candidate=cand, cosine=1.0)
    cr = _cascade_result([origin, cand], ["c"])
    md_lower = render_markdown(trace, cr, [wd]).lower()
    for phrase in _BANNED:
        assert phrase not in md_lower


# ────────────────────────── README example lock (b23 §5) ────────────────────

def test_readme_example_has_coverage_banner():
    """b23 §5 standing rule (extended): README example must carry the current
    render structure — including the coverage banner introduced here."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    m = re.search(r"```\s*\n(Result: WASTE DETECTED.*?)```", readme, re.S)
    assert m, "README must contain a 'Result: WASTE DETECTED' fenced example"
    example = m.group(1)
    assert "Tool mapping coverage for this trace" in example, (
        "README example is missing the coverage banner. Regenerate it "
        "from a real render (per docs/COVERAGE_TRANSPARENCY_PREREG.md §5)."
    )
