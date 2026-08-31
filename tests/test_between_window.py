"""between_window (PREREG §1.3 Rule V2) — report-only enum.

Tests cover:
  1. §1.3 priority order — declarative > no_side_effect > high_volume >
     payload_dependent > targeted_writes
  2. between_window only attached to `idempotent`; absent (not null) in JSON
     for other categories (§0.4 backward compat)
  3. Frozen wording — §3.2 banned phrases must not appear in rendered
     markdown or JSON output
  4. Waste-0 case renders without crash
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from clew.detect.cascade import CascadeResult
from clew.model import Span, Trace
from clew.report._enrich import (
    _BW_BLACKBOX_TOOLS,
    _BW_CONTEXT_LIMIT,
    _BW_DECLARATIVE_TOOLS,
    _BW_SIDE_EFFECT_TOOLS,
    _classify_between_window,
)
from clew.report._model import WasteDetail
from clew.report.json_report import render_json
from clew.report.markdown import render_markdown


def _ts(o: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=o)


def _tool_span(sid: str, tool: str, t: int, out: str = "x", tokens: int = 5) -> Span:
    return Span(
        trace_id="t",
        span_id=sid,
        parent_span_id="root",
        agent_or_node_id=tool,
        span_kind="tool",
        start_time=_ts(t),
        end_time=_ts(t),  # end == start; between-check uses < strict
        input_text="{}",
        output_text=out,
        token_count=tokens,
        model="fake",
        cost_rate=1e-6,
    )


def _root() -> Span:
    return Span(
        trace_id="t",
        span_id="root",
        parent_span_id=None,
        agent_or_node_id="run",
        span_kind="chain",
        start_time=_ts(0),
        end_time=_ts(9999),
        input_text="",
        output_text="root",
        token_count=0,
        model=None,
        cost_rate=None,
    )


def _trace(spans: list[Span]) -> Trace:
    return Trace(trace_id="t", spans=[_root(), *spans])


# ─────────────────────────────── priority order ─────────────────────────────

def test_priority_declarative_beats_all():
    """declarative wins even when between has side-effect + ≥20 tools + blackbox."""
    origin = _tool_span("o", "local-claim_done", 1)
    between = [
        _tool_span(f"b{i}", "terminal-run_command", 10 + i)
        for i in range(25)  # ≥20, blackbox, side-effect
    ]
    cand = _tool_span("c", "local-claim_done", 100)
    trace = _trace([origin, *between, cand])
    assert _classify_between_window(trace, origin, cand) == "declarative"


def test_priority_no_side_effect_beats_high_volume():
    """no_side_effect: side-effect 0, total tools ≥20 → still no_side_effect."""
    origin = _tool_span("o", "filesystem-read_file", 1)
    # 25 reads (idempotent, non-side-effect)
    between = [
        _tool_span(f"b{i}", "filesystem-read_file", 10 + i)
        for i in range(25)
    ]
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, *between, cand])
    assert _classify_between_window(trace, origin, cand) == "no_side_effect"


def test_priority_high_volume_beats_payload_dependent():
    """high_volume: side-effect ≥1 (blackbox), total ≥20 → high_volume."""
    origin = _tool_span("o", "filesystem-read_file", 1)
    between = [
        _tool_span(f"b{i}", "filesystem-read_file", 10 + i) for i in range(19)
    ] + [_tool_span("bb", "terminal-run_command", 30)]  # total = 20 → high_volume
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, *between, cand])
    assert len(between) == _BW_CONTEXT_LIMIT
    assert _classify_between_window(trace, origin, cand) == "high_volume"


def test_priority_payload_dependent_beats_targeted():
    """side-effect ≥1, total <20, blackbox present → payload_dependent."""
    origin = _tool_span("o", "filesystem-read_file", 1)
    between = [
        _tool_span("w1", "filesystem-write_file", 10),  # targeted write
        _tool_span("bb", "terminal-run_command", 11),   # blackbox
    ]
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, *between, cand])
    assert _classify_between_window(trace, origin, cand) == "payload_dependent"


def test_targeted_writes():
    """side-effect ≥1, total <20, no blackbox → targeted_writes."""
    origin = _tool_span("o", "filesystem-read_file", 1)
    between = [
        _tool_span("w1", "filesystem-write_file", 10),
        _tool_span("w2", "github-create_issue", 11),
    ]
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, *between, cand])
    assert _classify_between_window(trace, origin, cand) == "targeted_writes"


def test_cc_bash_between_treated_as_payload_dependent():
    """CC adapter: Bash in between makes idempotent Read pair payload_dependent."""
    origin = _tool_span("o", "Read", 1)
    between = [_tool_span("b", "Bash", 10)]  # Bash: side-effect + blackbox
    cand = _tool_span("c", "Read", 100)
    trace = _trace([origin, *between, cand])
    assert _classify_between_window(trace, origin, cand) == "payload_dependent"


def test_set_invariants():
    """§1.6 invariant: _BW_BLACKBOX_TOOLS ⊂ _BW_SIDE_EFFECT_TOOLS."""
    assert _BW_BLACKBOX_TOOLS.issubset(_BW_SIDE_EFFECT_TOOLS)
    assert _BW_DECLARATIVE_TOOLS == frozenset(
        {"local-claim_done", "filesystem-create_directory"}
    )
    # CC declarative is empty; total declarative = 2 Toolathlon items.
    assert len(_BW_DECLARATIVE_TOOLS) == 2


# ─────────────────────────── field presence / absence ───────────────────────

def _cascade_result(spans: list[Span], waste_ids: list[str]) -> CascadeResult:
    return CascadeResult(
        trace_id="t",
        wasteful=bool(waste_ids),
        waste_span_ids=waste_ids,
        waste_tokens=sum(s.token_count or 0 for s in spans if s.span_id in waste_ids),
        waste_cost=0.0,
    )


def test_between_window_absent_in_json_when_not_idempotent():
    """PREREG §0.4: between_window key MUST be absent (not null) for non-idempotent."""
    origin = _tool_span("o", "filesystem-write_file", 1)  # side_effect category
    cand = _tool_span("c", "filesystem-write_file", 100)
    trace = _trace([origin, cand])
    wd = WasteDetail(origin=origin, candidate=cand, cosine=1.0)
    cr = _cascade_result([origin, cand], ["c"])
    out = json.loads(render_json(trace, cr, [wd]))
    assert out["waste_details"][0]["category"] == "side_effect"
    assert "between_window" not in out["waste_details"][0], (
        "between_window MUST be absent (not null) when category != 'idempotent' "
        "(PREREG §0.4 backward compat)"
    )


def test_between_window_present_in_json_when_idempotent():
    origin = _tool_span("o", "filesystem-read_file", 1)
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, cand])
    wd = WasteDetail(origin=origin, candidate=cand, cosine=1.0)
    cr = _cascade_result([origin, cand], ["c"])
    out = json.loads(render_json(trace, cr, [wd]))
    assert out["waste_details"][0]["category"] == "idempotent"
    assert out["waste_details"][0]["between_window"] == "no_side_effect"
    # top-level counts include all 5 enum keys
    assert set(out["between_window_counts"].keys()) == {
        "declarative", "no_side_effect", "payload_dependent",
        "targeted_writes", "high_volume",
    }
    assert out["between_window_counts"]["no_side_effect"] == 1


def test_declarative_gets_its_own_wording_in_markdown():
    """PREREG §9: declarative uses 'interval ... was not examined' wording."""
    origin = _tool_span("o", "local-claim_done", 1)
    cand = _tool_span("c", "local-claim_done", 100)
    trace = _trace([origin, cand])
    wd = WasteDetail(origin=origin, candidate=cand, cosine=1.0)
    cr = _cascade_result([origin, cand], ["c"])
    md = render_markdown(trace, cr, [wd])
    assert "declarative or idempotent by name" in md
    assert "the interval between calls was not examined" in md
    # And its aggregate line
    assert "indicated, by tool identity: declarative 1" in md


def test_no_waste_case_renders_without_crash():
    """PREREG §5.1 #4: idempotent count = 0 → no idempotent block, no crash."""
    dummy = _tool_span("s1", "run", 1)
    trace = Trace(trace_id="t", spans=[_root(), dummy])
    cr = _cascade_result([dummy], [])
    md = render_markdown(trace, cr, [])
    js = json.loads(render_json(trace, cr, []))
    assert "no waste detected" in md.lower()
    assert js["wasteful"] is False
    # between_window_counts key still present in JSON, all zeros
    assert js.get("between_window_counts", {}) == {
        "declarative": 0, "no_side_effect": 0, "payload_dependent": 0,
        "targeted_writes": 0, "high_volume": 0,
    }


# ─────────────────────────────── §3.2 wording guard ─────────────────────────

_BANNED_PHRASES = [
    "confirmed waste", "verified waste", "proven waste",
    "waste confirmed", "waste verified",
    "guaranteed waste", "definite waste",
]


def test_no_over_claim_wording_in_report_sources():
    """PREREG §3.2: banned phrases must not appear in report source files."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    report_dir = root / "src" / "clew" / "report"
    checked = 0
    for path in sorted(report_dir.glob("*.py")):
        checked += 1
        text = path.read_text(encoding="utf-8").lower()
        for phrase in _BANNED_PHRASES:
            assert phrase not in text, (
                f"PREREG §3.2 banned phrase '{phrase}' in {path.name}"
            )
    assert checked >= 4  # __init__.py, _enrich.py, _model.py, json_report.py, markdown.py


def test_no_over_claim_wording_in_rendered_output():
    """Same guard against actual RENDERED output (all 5 between_window buckets)."""
    origins_cands = [
        ("local-claim_done", "local-claim_done", []),                       # declarative
        ("filesystem-read_file", "filesystem-read_file", []),               # no_side_effect
        ("filesystem-read_file", "filesystem-read_file",
         [("w", "filesystem-write_file"), ("b", "terminal-run_command")]),  # payload_dependent
        ("filesystem-read_file", "filesystem-read_file",
         [("w", "filesystem-write_file")]),                                 # targeted_writes
        ("filesystem-read_file", "filesystem-read_file",
         [(f"b{i}", "filesystem-read_file") for i in range(19)]
         + [("bb", "filesystem-write_file")]),                              # high_volume
    ]
    for origin_tool, cand_tool, between in origins_cands:
        o = _tool_span("o", origin_tool, 1)
        b = [_tool_span(sid, tool, 10 + i) for i, (sid, tool) in enumerate(between)]
        c = _tool_span("c", cand_tool, 100)
        trace = _trace([o, *b, c])
        wd = WasteDetail(origin=o, candidate=c, cosine=1.0)
        cr = _cascade_result([o, *b, c], ["c"])
        md_lower = render_markdown(trace, cr, [wd]).lower()
        js_lower = render_json(trace, cr, [wd]).lower()
        for phrase in _BANNED_PHRASES:
            assert phrase not in md_lower, f"banned '{phrase}' in markdown for {cand_tool}"
            assert phrase not in js_lower, f"banned '{phrase}' in JSON for {cand_tool}"


# ─────────────────────────── §4.1 exact reproduction ─────────────────────────

def test_between_window_toolathlon_counts_reproduce_pre_reg_4_1():
    """PREREG §4.1: Toolathlon 66-file scan reproduces frozen 5-enum counts.

    This is the KILL gate. If any single count diverges, the rule was
    misimplemented — do not adjust the rule to fit; investigate.
    """
    import sys
    from collections import Counter
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    diag = root / "field_test" / "diagnostics"
    if not (root / "data" / "toolathlon" / "hf").is_dir():
        import pytest
        pytest.skip("Toolathlon dataset not available in this environment")
    sys.path.insert(0, str(diag))
    try:
        from greyzone_judge_feasibility import (  # noqa: E402
            _is_empty_input, _is_error, _is_nooutput,
            collect_waste_pairs, is_A, TOOLATHLON_DIR,
        )
        from clew.ingest.toolathlon import (  # noqa: E402
            _build_trace_from_entry, _iter_raw_lines,
        )
    finally:
        pass

    cnt: Counter[str] = Counter()
    for path in sorted(TOOLATHLON_DIR.glob("*.jsonl")):
        for lineno, entry in _iter_raw_lines(path):
            try:
                trace = _build_trace_from_entry(entry, lineno)
            except Exception:
                continue
            for origin, cand in collect_waste_pairs(trace):
                if _is_error(cand.output_text):
                    continue
                if _is_empty_input(cand.input_text) and _is_nooutput(cand.output_text):
                    continue
                if not is_A(cand.agent_or_node_id):
                    continue
                cnt[_classify_between_window(trace, origin, cand)] += 1

    expected = {
        "declarative": 1226,
        "no_side_effect": 888,
        "payload_dependent": 405,
        "targeted_writes": 248,
        "high_volume": 1024,
    }
    for k, v in expected.items():
        assert cnt.get(k, 0) == v, (
            f"PREREG §4.1 KILL: {k} = {cnt.get(k, 0)} != expected {v}. "
            f"Full counts: {dict(cnt)}"
        )
    assert sum(cnt.values()) == 3791


# ─── extensions (b21 + b23) ─────────────────────────────────────────────────

def test_targeted_writes_own_wording():
    """b21 §1.2 + b23 §1.2: targeted_writes uses its own _BW_OBS_TARGETED_WRITES,
    distinct from all other tiers including the new _BW_OBS_HIGH_VOLUME."""
    from clew.report.markdown import (
        _BW_OBS_DECLARATIVE,
        _BW_OBS_NO_CHANGE,
        _BW_OBS_HIGH_VOLUME,
        _BW_OBS_TARGETED_WRITES,
    )
    assert _BW_OBS_TARGETED_WRITES != _BW_OBS_DECLARATIVE
    assert _BW_OBS_TARGETED_WRITES != _BW_OBS_NO_CHANGE
    assert _BW_OBS_TARGETED_WRITES != _BW_OBS_HIGH_VOLUME

    origin = _tool_span("o", "filesystem-read_file", 1)
    between = [_tool_span("w", "filesystem-write_file", 10)]
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, *between, cand])
    wd = WasteDetail(origin=origin, candidate=cand, cosine=1.0)
    cr = _cascade_result([origin, *between, cand], ["c"])
    md = render_markdown(trace, cr, [wd])
    assert _BW_OBS_TARGETED_WRITES in md
    assert _BW_OBS_HIGH_VOLUME not in md, (
        "targeted_writes must not fall through to HIGH_VOLUME wording"
    )


def test_high_volume_own_wording():
    """b23 §1.2: high_volume uses its own _BW_OBS_HIGH_VOLUME, distinct from
    all four other wording constants."""
    from clew.report.markdown import (
        _BW_OBS_DECLARATIVE,
        _BW_OBS_NO_CHANGE,
        _BW_OBS_HIGH_VOLUME,
        _BW_OBS_TARGETED_WRITES,
    )
    assert _BW_OBS_HIGH_VOLUME != _BW_OBS_DECLARATIVE
    assert _BW_OBS_HIGH_VOLUME != _BW_OBS_NO_CHANGE
    assert _BW_OBS_HIGH_VOLUME != _BW_OBS_TARGETED_WRITES

    origin = _tool_span("o", "filesystem-read_file", 1)
    # ≥ 20 between-tools, includes a side-effect → high_volume
    between = [
        _tool_span(f"b{i}", "filesystem-read_file", 10 + i) for i in range(19)
    ] + [_tool_span("bb", "filesystem-write_file", 30)]
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, *between, cand])
    wd = WasteDetail(origin=origin, candidate=cand, cosine=1.0)
    cr = _cascade_result([origin, *between, cand], ["c"])
    md = render_markdown(trace, cr, [wd])
    assert _BW_OBS_HIGH_VOLUME in md, "high_volume must receive its own wording"
    assert _BW_OBS_TARGETED_WRITES not in md, (
        "high_volume must not fall through to TARGETED_WRITES wording"
    )


def test_not_established_constant_removed():
    """b23 §1.2: _BW_OBS_NOT_ESTABLISHED must not exist in markdown module.
    The 'not established' group is empty after b23; the constant is dead code."""
    import clew.report.markdown as md_mod
    assert not hasattr(md_mod, "_BW_OBS_NOT_ESTABLISHED"), (
        "b23 §1.2: _BW_OBS_NOT_ESTABLISHED must be removed"
    )
    # Also verify no textual leak in the rendered output.
    origin = _tool_span("o", "filesystem-read_file", 1)
    between = [
        _tool_span(f"b{i}", "filesystem-read_file", 10 + i) for i in range(19)
    ] + [_tool_span("bb", "filesystem-write_file", 30)]
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, *between, cand])
    wd = WasteDetail(origin=origin, candidate=cand, cosine=1.0)
    cr = _cascade_result([origin, *between, cand], ["c"])
    md = render_markdown(trace, cr, [wd])
    assert "not established" not in md, (
        "b23: 'not established' group must not appear in rendered markdown"
    )


def test_between_window_counts_stable_post_b23():
    """b21 §0.2 / b23 §0.2: display-layer restructure must not change
    JSON between_window_counts field values across BOTH extensions."""
    origin = _tool_span("o", "filesystem-read_file", 1)
    between = [_tool_span("w", "filesystem-write_file", 10)]
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, *between, cand])
    wd = WasteDetail(origin=origin, candidate=cand, cosine=1.0)
    cr = _cascade_result([origin, *between, cand], ["c"])
    out = json.loads(render_json(trace, cr, [wd]))
    assert out["between_window_counts"] == {
        "declarative": 0, "no_side_effect": 0, "payload_dependent": 0,
        "targeted_writes": 1, "high_volume": 0,
    }
    assert out["waste_details"][0]["between_window"] == "targeted_writes"

    # And for a high_volume pair the enum still lands correctly (not lost by
    # the display-layer changes).
    origin2 = _tool_span("o2", "filesystem-read_file", 1000)
    between2 = [
        _tool_span(f"hb{i}", "filesystem-read_file", 1010 + i) for i in range(19)
    ] + [_tool_span("hbb", "filesystem-write_file", 1030)]
    cand2 = _tool_span("c2", "filesystem-read_file", 1100)
    trace2 = _trace([origin2, *between2, cand2])
    wd2 = WasteDetail(origin=origin2, candidate=cand2, cosine=1.0)
    cr2 = _cascade_result([origin2, *between2, cand2], ["c2"])
    out2 = json.loads(render_json(trace2, cr2, [wd2]))
    assert out2["waste_details"][0]["between_window"] == "high_volume"
    assert out2["between_window_counts"]["high_volume"] == 1


def test_markdown_tier_order_evidence_strength():
    """b23 §1.3: aggregate lines render in evidence-strength order:
      (1) indicated, by tool identity
      (2) indicated, by interval scan
      (3) high_volume         (own tier, 82.78% lower — above targeted_writes)
      (4) writes to other targets: targeted_writes  (77.93% lower)
    Top-level tiers = 3 (indicated / high_volume / writes to other targets).
    """
    origin = _tool_span("o", "filesystem-read_file", 1)
    # Craft: one targeted_writes pair + one high_volume pair to exercise both tiers.
    tw_between = [_tool_span("w", "filesystem-write_file", 10)]
    hv_between = [
        _tool_span(f"hb{i}", "filesystem-read_file", 200 + i) for i in range(19)
    ] + [_tool_span("hbb", "filesystem-write_file", 230)]
    cand_tw = _tool_span("c_tw", "filesystem-read_file", 100)
    origin_hv = _tool_span("o_hv", "filesystem-read_file", 190)
    cand_hv = _tool_span("c_hv", "filesystem-read_file", 300)
    trace = _trace([origin, *tw_between, cand_tw, origin_hv, *hv_between, cand_hv])
    wd_tw = WasteDetail(origin=origin, candidate=cand_tw, cosine=1.0)
    wd_hv = WasteDetail(origin=origin_hv, candidate=cand_hv, cosine=1.0)
    cr = _cascade_result(list(trace.spans), ["c_tw", "c_hv"])
    md = render_markdown(trace, cr, [wd_tw, wd_hv])

    # Summary line: evidence-strength order + parallel "with X" phrasing.
    assert re.search(
        r"idempotent 2:\s*0 with no state change indicated,\s*"
        r"1 with high tool volume,\s*"
        r"1 with writes to other targets",
        md,
    ), f"Aggregate summary order or wording changed. Got:\n{md}"

    # 4 aggregate lines in order.
    pos_ident = md.find("indicated, by tool identity")
    pos_scan = md.find("indicated, by interval scan")
    pos_hv = md.find("- high_volume: 1")
    pos_tw = md.find("writes to other targets: targeted_writes 1")
    assert 0 <= pos_ident < pos_scan < pos_hv < pos_tw, (
        f"Aggregate line order broken. positions: "
        f"ident={pos_ident}, scan={pos_scan}, hv={pos_hv}, tw={pos_tw}"
    )

    # Both stat lines present.
    assert "Validated on Toolathlon: 29/30 hand-labeled TRUE" in md
    assert re.search(r"Clopper-Pearson lower [≈~] 82\.78", md)
    assert "Validated on Toolathlon: 28/30 hand-labeled TRUE" in md
    assert re.search(r"Clopper-Pearson lower [≈~] 77\.93", md)

    # "not established" group must be gone.
    assert "not established" not in md


def test_markdown_high_volume_tier_absent_when_zero():
    """b23 §1.3: high_volume line + stat are conditional on high_volume > 0.
    Summary line still shows '0 with high tool volume' (all counts always
    printed for arithmetic transparency)."""
    origin = _tool_span("o", "filesystem-read_file", 1)
    between = [_tool_span("w", "filesystem-write_file", 10)]  # targeted_writes only
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, *between, cand])
    wd = WasteDetail(origin=origin, candidate=cand, cosine=1.0)
    cr = _cascade_result([origin, *between, cand], ["c"])
    md = render_markdown(trace, cr, [wd])
    # Summary still shows the count (0), but no dedicated high_volume line/stat.
    assert "0 with high tool volume" in md
    assert re.search(r"^\s+- high_volume:", md, re.M) is None, (
        "high_volume line must be absent when count == 0"
    )
    assert "82.78" not in md


def test_markdown_writes_tier_absent_when_zero():
    """b21 §1.3 (unchanged by b23): writes-to-other-targets line + stat are
    conditional on targeted_writes > 0. Summary line still shows the count."""
    origin = _tool_span("o", "filesystem-read_file", 1)
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, cand])
    wd = WasteDetail(origin=origin, candidate=cand, cosine=1.0)
    cr = _cascade_result([origin, cand], ["c"])
    md = render_markdown(trace, cr, [wd])
    assert "0 with writes to other targets" in md
    assert "writes to other targets: targeted_writes" not in md
    assert "77.93" not in md


# ─── standing rule (docs/GREYZONE_B23_EXTENSION_PREREG.md §5) ──────────────

def test_readme_example_matches_current_render_structure():
    """b23 §5 standing rule: README output example must reflect the current
    render structure. When render wording/lines change, regenerate the example
    in the same PR.

    This is a *structural* check (not char-for-char): it verifies the example
    block uses the current tier-header phrasing, not obsolete ones. Two prior
    slips (0.3.2 between_window intro; b21 targeted_writes 3-tier) prompted
    promoting this to a standing rule.
    """
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")

    # Extract the first fenced code block that starts with the "Result" banner
    # and includes the "Waste detection: N wasteful span(s)." line.
    # v0.4.1: fenced example now pastes the actual renderer output verbatim,
    # so it may include `## ` heading prefix and `**bold**` markers.
    m = re.search(
        r"```\s*\n((?:##\s+)?Result\s*\n.*?\*{0,2}Waste detection\*{0,2}:.*?)```",
        readme,
        re.S,
    )
    assert m, (
        "README must contain a fenced 'Result / Waste detection:' example."
    )
    example = m.group(1)

    # v0.4.2+: hero fenced block can be either an idempotent-pair example
    # (with the b23 tier-header phrasing) or a duplicate-creation example
    # (Waste detection = no waste detected, but Duplicate creation check
    # surfaces candidate pairs). Both are current render shapes.
    is_idempotent_hero = "with no state change indicated" in example
    is_duplicate_creation_hero = (
        "Duplicate creation check" in example
        and "candidate pair" in example
    )
    assert is_idempotent_hero or is_duplicate_creation_hero, (
        "README hero fenced block must be either an idempotent-pair "
        "example (with 'with no state change indicated' tier phrasing) or "
        "a duplicate-creation example (with 'Duplicate creation check' and "
        "'candidate pair(s)')."
    )

    if is_idempotent_hero:
        # Current (b23) tier phrasing must be present.
        assert "indicated, by tool identity" in example
        assert "indicated, by interval scan" in example

        # Obsolete phrasings from earlier iterations must be gone.
        # Pre-b21: "by tool identity" (without "indicated, ").
        assert re.search(r"^\s+- by tool identity", example, re.M) is None, (
            "README example uses pre-b21 aggregate wording; regenerate."
        )
        # Pre-b21: "by interval scan" (without "indicated, ").
        assert re.search(r"^\s+- by interval scan", example, re.M) is None, (
            "README example uses pre-b21 aggregate wording; regenerate."
        )
        # Pre-b23: "not established:" line.
        assert "not established: targeted_writes" not in example, (
            "README example uses pre-b23 'not established' grouping; regenerate."
        )
        assert "not established: high_volume" not in example, (
            "README example uses pre-b23 'not established' grouping; regenerate."
        )

        # Current per-pair wording variants must appear if the example flags any
        # idempotent pair. (Loose check: at least one of the current 4 wordings.)
        from clew.report.markdown import (
            _BW_OBS_DECLARATIVE, _BW_OBS_NO_CHANGE,
            _BW_OBS_TARGETED_WRITES, _BW_OBS_HIGH_VOLUME,
        )
        per_pair_line = re.search(r"between_window: `[^`]+`:\s*(.+)", example)
        if per_pair_line:
            wording = per_pair_line.group(1).strip().rstrip(".")
            current = {
                _BW_OBS_DECLARATIVE.rstrip("."),
                _BW_OBS_NO_CHANGE.rstrip("."),
                _BW_OBS_TARGETED_WRITES.rstrip("."),
                _BW_OBS_HIGH_VOLUME.rstrip("."),
            }
            assert any(wording.startswith(c) for c in current), (
                f"README example's per-pair wording is not among current 4:\n"
                f"  got: {wording!r}\n"
                f"  expected one of (prefix match): {sorted(current)}"
            )
