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
    enrich,
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
    assert "by tool identity: declarative 1" in md


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
