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
from clew.report._enrich import coverage_stats
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
    """Line A also renders when waste is detected, at category-breakdown → banner slot."""
    origin = _tool_span("o", "filesystem-read_file", 1)
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, cand])
    wd = WasteDetail(origin=origin, candidate=cand, cosine=1.0)
    cr = _cascade_result([origin, cand], ["c"])
    md = render_markdown(trace, cr, [wd])
    assert "## Result" in md
    assert "wasteful span" in md
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
    """JSON top-level `coverage_stats` field.

    Schema is the 5 keys from COVERAGE_TRANSPARENCY_PREREG plus
    unrecognized_tool_names (COVERAGE_BANNER_AMEND_PREREG §4 option B).
    """
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
        "unrecognized_tool_names",
    }
    assert cov["unique_tools_in_trace"] == 1
    assert cov["recognized_tools"] == 1
    assert cov["coverage_ratio"] == 1.0
    assert cov["idempotent_pairs_total"] == 1
    assert cov["pairs_with_unrecognized_in_between"] == 0
    assert cov["unrecognized_tool_names"] == []


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
    # v0.4.1: fenced example uses the actual renderer output — includes
    # `## Result` heading and `**Waste detection**:` bold markers.
    m = re.search(
        r"```\s*\n((?:##\s+)?Result\s*\n.*?\*{0,2}Waste detection\*{0,2}:.*?)```",
        readme,
        re.S,
    )
    assert m, (
        "README must contain a fenced 'Result / Waste detection:' example. "
        "See docs/COVERAGE_TRANSPARENCY_PREREG.md §5 (regenerate from a "
        "real render if the banner changes)."
    )
    example = m.group(1)
    assert "Tool mapping coverage for this trace" in example, (
        "README example is missing the coverage banner. Regenerate it "
        "from a real render (per docs/COVERAGE_TRANSPARENCY_PREREG.md §5)."
    )


# ────────────── Line C: top-N unrecognized names (banner amend) ─────────────


def test_coverage_line_c_absent_when_zero_unrecognized():
    """PREREG (banner amend) §3.2: Line C must NOT render when all tools recognized."""
    s = _tool_span("s", "filesystem-read_file", 1)
    trace = _trace([s])
    cr = _cascade_result([s], [])
    md = render_markdown(trace, cr, [])
    assert "Unrecognized tools in this trace" not in md


def test_coverage_line_c_present_when_unrecognized_gt_zero():
    """§3.1: Line C renders when at least one unrecognized tool exists."""
    s1 = _tool_span("s1", "filesystem-read_file", 1)
    s2 = _tool_span("s2", "some-brand-new-tool", 2)
    trace = _trace([s1, s2])
    cr = _cascade_result([s1, s2], [])
    md = render_markdown(trace, cr, [])
    assert "Unrecognized tools in this trace" in md
    assert "some-brand-new-tool" in md


def test_coverage_line_c_names_sorted_by_occurrence_desc():
    """§3.1: sort key is occurrence-desc, alphabetic tie-break."""
    # bravo appears 3× (spans t=1,2,3), alpha 2×, zulu 1×.
    spans = [
        _tool_span("b1", "bravo-tool", 1),
        _tool_span("b2", "bravo-tool", 2),
        _tool_span("b3", "bravo-tool", 3),
        _tool_span("a1", "alpha-tool", 4),
        _tool_span("a2", "alpha-tool", 5),
        _tool_span("z1", "zulu-tool", 6),
    ]
    trace = _trace(spans)
    cov = coverage_stats(trace, [])
    assert cov["unrecognized_tool_names"] == ["bravo-tool", "alpha-tool", "zulu-tool"]


def test_coverage_line_c_alpha_tie_break():
    """§3.1: tie-break on occurrence count is alphabetic."""
    spans = [
        _tool_span("g1", "gamma-tool", 1),
        _tool_span("g2", "gamma-tool", 2),
        _tool_span("d1", "delta-tool", 3),
        _tool_span("d2", "delta-tool", 4),
    ]
    trace = _trace(spans)
    cov = coverage_stats(trace, [])
    assert cov["unrecognized_tool_names"] == ["delta-tool", "gamma-tool"]


def test_coverage_line_c_ellipsis_when_more_than_5():
    """§3.1: >5 unrecognized → top-5 shown, '… (+K more)' suffix."""
    spans = []
    # Seven distinct unrecognized names, each seen once. Alphabetic order applies
    # because all have count=1.
    for i, name in enumerate(["a-tool", "b-tool", "c-tool", "d-tool",
                              "e-tool", "f-tool", "g-tool"]):
        spans.append(_tool_span(f"s{i}", name, i + 1))
    trace = _trace(spans)
    cr = _cascade_result(spans, [])
    md = render_markdown(trace, cr, [])
    assert "Unrecognized tools in this trace (top 5)" in md
    assert "a-tool, b-tool, c-tool, d-tool, e-tool" in md
    assert "… (+2 more)" in md
    # f-tool and g-tool should NOT appear in the top-5 comma list.
    banner_line = next(
        line for line in md.splitlines() if "Unrecognized tools in this trace" in line
    )
    assert "f-tool" not in banner_line
    assert "g-tool" not in banner_line


def test_coverage_line_c_no_ellipsis_when_le_5():
    """§3.1: ≤5 unrecognized → n_shown = actual, no '(+K more)'."""
    spans = [
        _tool_span("s1", "x-tool", 1),
        _tool_span("s2", "y-tool", 2),
    ]
    trace = _trace(spans)
    cr = _cascade_result(spans, [])
    md = render_markdown(trace, cr, [])
    assert "Unrecognized tools in this trace (top 2)" in md
    assert "more)" not in md


def test_coverage_line_c_renders_in_waste_zero():
    """§3.5: waste-0 branch renders Line C too (parallels Line A)."""
    s = _tool_span("s", "some-unmapped-tool", 1)
    trace = _trace([s])
    cr = _cascade_result([s], [])
    md = render_markdown(trace, cr, [])
    assert "no waste detected" in md.lower()
    assert "Unrecognized tools in this trace" in md
    assert "some-unmapped-tool" in md


def test_coverage_line_c_renders_in_waste_detected():
    """§3.4 / §3.5 also applies inside the waste-detected branch."""
    origin = _tool_span("o", "filesystem-read_file", 1)
    unmapped = _tool_span("u", "some-brand-new-tool", 10)
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, unmapped, cand])
    wd = WasteDetail(origin=origin, candidate=cand, cosine=1.0)
    cr = _cascade_result([origin, unmapped, cand], ["c"])
    md = render_markdown(trace, cr, [wd])
    assert "## Result" in md
    assert "wasteful span" in md
    assert "Unrecognized tools in this trace" in md
    assert "some-brand-new-tool" in md


def test_json_unrecognized_tool_names_full_not_truncated():
    """§4 option B: JSON list is the FULL list, no top-5 cap."""
    # 7 unrecognized names, occurrence 1 each — Line C truncates to 5, JSON has all 7.
    spans = []
    for i, name in enumerate(["a", "b", "c", "d", "e", "f", "g"]):
        spans.append(_tool_span(f"s{i}", f"{name}-tool", i + 1))
    trace = _trace(spans)
    cr = _cascade_result(spans, [])
    out = json.loads(render_json(trace, cr, []))
    assert out["coverage_stats"]["unrecognized_tool_names"] == [
        "a-tool", "b-tool", "c-tool", "d-tool", "e-tool", "f-tool", "g-tool",
    ]


def test_coverage_line_c_no_over_claim_wording():
    """§3.3: Line C constant carries no banned phrase and no 'provable'."""
    from clew.report.markdown import _COVERAGE_LINE_C
    low = _COVERAGE_LINE_C.lower()
    for phrase in _BANNED:
        assert phrase not in low
    assert "provable" not in low


def test_coverage_line_c_determinism():
    """§3.1: same input → same sorted names."""
    spans = [
        _tool_span("s1", "b-tool", 1),
        _tool_span("s2", "a-tool", 2),
        _tool_span("s3", "a-tool", 3),
    ]
    trace = _trace(spans)
    a = coverage_stats(trace, [])["unrecognized_tool_names"]
    b = coverage_stats(trace, [])["unrecognized_tool_names"]
    assert a == b == ["a-tool", "b-tool"]


# ───────────── zero tool spans: COVERAGE_ZERO_TOOL_AMENDMENT_PREREG ─────────
#
# Before this, a trace whose tool detectors had nothing to run on said only
# "no waste detected" -- the banner was skipped rather than adapted, so "we
# could not look" and "you are clean" were the same report. Three measured
# frameworks live in that state (Haystack, Google GenAI, the Anthropic direct
# SDK), because their instrumentors emit no tool span.

def _llm_span(sid: str, t: int, out: str = "answer", tokens: int = 10) -> Span:
    return Span(
        trace_id="t", span_id=sid, parent_span_id="root",
        agent_or_node_id="model", span_kind="llm",
        start_time=_ts(t), end_time=_ts(t + 1),
        input_text="ask", output_text=out, token_count=tokens,
        model="fake", cost_rate=1e-6,
    )


def test_a_trace_with_no_tool_spans_says_so(  # P1
):
    """P1. The sentence the amendment exists for, and neither of the two
    strings that would mean the old shape leaked through."""
    trace = _trace([_llm_span("l1", 1)])
    cr = _cascade_result([], [])
    md = render_markdown(trace, cr, [])

    assert "no tool calls were recorded" in md
    assert "this is not a finding of zero waste" in md
    assert "100.0%" not in md, "the vacuous ratio reached the page"
    assert "0 of 0" not in md, "the counts shape rendered on an empty trace"


def test_the_no_tool_line_renders_in_the_waste_detected_branch_too():  # P6
    """P6. Two render sites, and the amendment's first draft saw one.

    A trace can carry waste and no tool spans at once -- llm-side waste with an
    uninstrumented tool layer -- and that report goes down the other branch.
    """
    a = _llm_span("l1", 1, out="same answer")
    b = _llm_span("l2", 100, out="same answer")
    trace = _trace([a, b])
    wd = WasteDetail(origin=a, candidate=b, cosine=1.0)
    cr = _cascade_result([a, b], ["l2"])
    md = render_markdown(trace, cr, [wd])

    assert "wasteful span" in md, "this test needs the waste-detected branch"
    assert "no tool calls were recorded" in md
    assert "100.0%" not in md


def test_the_with_tools_shape_is_untouched():  # P2
    """P2. A wording fix that moves a report with tools in it is not a wording
    fix. The counts form has to come out exactly as before."""
    s1 = _tool_span("s1", "filesystem-read_file", 1)
    s2 = _tool_span("s2", "some-unmapped-tool", 2)
    trace = _trace([s1, s2])
    md = render_markdown(trace, _cascade_result([s1, s2], []), [])

    assert ("**Tool mapping coverage for this trace**: 1 of 2 tools "
            "recognized (50.0%).") in md
    assert "no tool calls were recorded" not in md


def test_coverage_stats_json_is_unchanged_by_this(  # P3
):
    """P3. `coverage_ratio` stays 1.0 on the empty case, deliberately.

    It is stored, pre-registered, and read by the aggregate. The defect was in
    the prose, so the fix is in the prose -- and `unique_tools_in_trace == 0`
    already disambiguates for any machine that looks.
    """
    trace = _trace([_llm_span("l1", 1)])
    cov = json.loads(render_json(trace, _cascade_result([], []), []))[
        "coverage_stats"]

    assert cov["unique_tools_in_trace"] == 0
    assert cov["recognized_tools"] == 0
    assert cov["coverage_ratio"] == 1.0, (
        "changing this to fix a sentence would move a measurement; the "
        "amendment §3 says it stays"
    )
    assert cov["unrecognized_tool_names"] == []


def test_a_json_consumer_can_tell_the_empty_case_apart():  # P3 corollary
    """The hazard the amendment names rather than fixes: `coverage_ratio` alone
    reads as 100%. What makes it safe is that the companion count is in the
    same object, so a renderer has something to guard on."""
    empty = json.loads(render_json(_trace([_llm_span("l1", 1)]),
                                   _cascade_result([], []), []))["coverage_stats"]
    s1 = _tool_span("s1", "filesystem-read_file", 1)
    full = json.loads(render_json(_trace([s1]), _cascade_result([s1], []),
                                  []))["coverage_stats"]

    assert empty["coverage_ratio"] == full["coverage_ratio"] == 1.0
    assert empty["unique_tools_in_trace"] == 0
    assert full["unique_tools_in_trace"] == 1


def test_the_empty_trace_is_not_excluded_from_the_aggregate():  # P4
    """P4. `excluded_reason` decides which traces leave the published
    denominators. A trace with llm calls and no tool spans was included before
    and stays included -- otherwise a wording change would silently move every
    corpus figure."""
    from clew.metrics.waste_rate import compute_waste_rate

    class _FixedEmbedder:
        def embed(self, text: str) -> list[float]:
            return [1.0, 0.0]

    # `excluded_reason` reads `metadata["llm_calls"]`, not llm spans. That
    # distinction matters here: a trace with neither is excluded as
    # `no_llm_calls` and always was, while the frameworks this amendment is
    # about *do* produce llm_calls -- their instrumentors emit the LLM span and
    # skip only the tool span. So the case under test is llm_calls present,
    # tool spans absent.
    trace = _trace([_llm_span("l1", 1)])
    trace.metadata["llm_calls"] = [{
        "input_text": "ask", "input_tokens": 10, "output_tokens": 4,
        "input_cost_rate": 1e-6, "model": "fake", "span_id": "l1",
    }]
    wr = compute_waste_rate(trace, embedder=_FixedEmbedder(), n=2, phi=0.5)

    assert wr.excluded_reason is None, (
        f"a no-tool trace became excluded: {wr.excluded_reason}"
    )
    assert wr.total_input_bytes > 0


def test_both_shapes_come_from_one_function():
    """The two render sites must not be able to disagree. If a third site is
    added, it gets both shapes by calling this."""
    from clew.report.markdown import _coverage_line_a

    empty = _coverage_line_a({"unique_tools_in_trace": 0, "recognized_tools": 0,
                              "coverage_ratio": 1.0})
    full = _coverage_line_a({"unique_tools_in_trace": 2, "recognized_tools": 1,
                             "coverage_ratio": 0.5})

    assert "no tool calls were recorded" in empty
    assert "1 of 2 tools recognized (50.0%)" in full


def test_the_stale_comment_is_gone():
    """The comment above Line A said it was "ALWAYS rendered" while a guard
    below it skipped the empty case. That mismatch is what made the first draft
    of the amendment assert a sentence we never shipped -- read twice, run
    zero times. It must not be left describing the new code either."""
    import inspect

    import clew.report.markdown as md_mod

    source = inspect.getsource(md_mod)
    assert "ALWAYS rendered" not in source, (
        "the comment that misled a reader once is still there"
    )
