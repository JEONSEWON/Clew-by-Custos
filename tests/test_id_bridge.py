"""ID-bridge / duplicate-creation-check tests.

Follows docs/ID_BRIDGE_PRODUCTION_PREREG.md §2.1.

Tests cover:
  - extract_entity_id per mapping kind (path / array_path / regex_url) and
    the three None branches (tool not in mapping, JSON parse error, path miss)
  - scan_id_bridge_candidates pool = side_effect only, sha256-independent
  - 3-way verdict (differ / same / no_id)
  - Toolathlon 66-file reproduction of frozen 3,432 / 159 / 76 / 3,197
  - waste_span_ids / between_window_counts / coverage_stats stability
  - JSON id_bridge_candidates field + backward compat
  - Markdown section: header, intro, "0 candidates" line, waste-0 render,
    position (Wasted Span Details -> Duplicate creation check -> Possible causes),
    IDs verbatim (no truncation)
  - Banned phrases + "provable" absence
  - README subsection lock (b23 §5 standing rule extension)
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from clew.detect.cascade import CascadeResult
from clew.model import Span, Trace
from clew.report._enrich import (
    _ID_BRIDGE_MAPPING,
    _SIDE_EFFECT_TOOLS,
    IdBridgeCandidate,
    extract_entity_id,
    scan_id_bridge_candidates,
)
from clew.report._model import WasteDetail
from clew.report.json_report import render_json
from clew.report.markdown import render_markdown


# ────────────────────────── helpers ─────────────────────────────────────────

def _ts(o: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=o)


def _tool_span(sid: str, tool: str, t: int, out: str = "x", inp: str = "{}",
               tokens: int = 5) -> Span:
    return Span(
        trace_id="t", span_id=sid, parent_span_id="root",
        agent_or_node_id=tool, span_kind="tool",
        start_time=_ts(t), end_time=_ts(t),
        input_text=inp, output_text=out, token_count=tokens,
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


# ────────────────────────── extract_entity_id ───────────────────────────────

def test_extract_entity_id_notion_page_path():
    """path kind on notion-API-post-page → top-level `id` field."""
    body = json.dumps({"id": "290d1b2a-abcd-4000-8000-000000000001", "other": 1})
    got = extract_entity_id("notion-API-post-page", body)
    assert got == "290d1b2a-abcd-4000-8000-000000000001"


def test_extract_entity_id_github_url_regex():
    """regex_url kind on github-create_pull_request → tail /pull/N."""
    body = json.dumps({"url": "https://api.github.com/repos/x/y/pull/42"})
    got = extract_entity_id("github-create_pull_request", body)
    assert got == "42"


def test_extract_entity_id_array_path():
    """array_path kind on notion-API-patch-block-children → results.0.id."""
    body = json.dumps({"results": [{"id": "block-1"}, {"id": "block-2"}]})
    got = extract_entity_id("notion-API-patch-block-children", body)
    assert got == "block-1"


def test_extract_entity_id_toolathlon_envelope_unwrap():
    """Toolathlon envelope {"type":"text","text":"<body>"} is unwrapped once."""
    inner = json.dumps({"id": "wrapped-1"})
    outer = json.dumps({"type": "text", "text": inner, "annotations": None})
    got = extract_entity_id("notion-API-post-page", outer)
    assert got == "wrapped-1"


def test_extract_entity_id_none_when_tool_not_in_mapping():
    """Tool outside the 26-tool mapping → None."""
    got = extract_entity_id("some-brand-new-tool", json.dumps({"id": "x"}))
    assert got is None


def test_extract_entity_id_none_when_path_missing():
    """Mapped tool, but the specific key is absent → None."""
    got = extract_entity_id("notion-API-post-page", json.dumps({"other_field": "y"}))
    assert got is None


def test_extract_entity_id_none_on_json_parse_error():
    """Path kind but body is not JSON → None (no raise)."""
    got = extract_entity_id("notion-API-post-page", "<html>error</html>")
    assert got is None


def test_extract_entity_id_none_on_empty_output():
    got = extract_entity_id("notion-API-post-page", "")
    assert got is None


def test_extract_entity_id_string_id_with_numeric_value():
    """Numeric IDs (canvas etc.) are stringified."""
    body = json.dumps({"id": 12345})
    got = extract_entity_id("canvas-canvas_create_course", body)
    assert got == "12345"


def test_id_bridge_mapping_size_frozen_26():
    """Mapping frozen at 26 tools (§1.1 · §0.2). Any change requires new prereg."""
    assert len(_ID_BRIDGE_MAPPING) == 26


# ────────────────────────── scan_id_bridge_candidates ───────────────────────

def _notion_out(entity_id: str) -> str:
    return json.dumps({"id": entity_id, "other": "x"})


def test_scan_id_bridge_pool_side_effect_only():
    """Pool includes side_effect tools only; read tools are ignored."""
    # side_effect: notion-API-post-page (mapped, in _SIDE_EFFECT_TOOLS)
    se_o = _tool_span("se_o", "notion-API-post-page", 1, _notion_out("A"))
    se_c = _tool_span("se_c", "notion-API-post-page", 100, _notion_out("B"))
    # read: filesystem-read_file (not in _SIDE_EFFECT_TOOLS)
    r_o = _tool_span("r_o", "filesystem-read_file", 10, "same-content")
    r_c = _tool_span("r_c", "filesystem-read_file", 110, "same-content")
    trace = _trace([se_o, se_c, r_o, r_c])
    cands = scan_id_bridge_candidates(trace)
    tools = {c.tool for c in cands}
    assert tools == {"notion-API-post-page"}


def test_scan_id_bridge_ignores_sha256_gate():
    """Different responses (would fail cascade sha256 gate) still enter the pool."""
    o = _tool_span("o", "notion-API-post-page", 1, _notion_out("A"))
    c = _tool_span("c", "notion-API-post-page", 100, _notion_out("B"))  # differ
    trace = _trace([o, c])
    cands = scan_id_bridge_candidates(trace)
    assert len(cands) == 1
    assert cands[0].verdict == "differ"


def test_id_bridge_verdict_differ():
    o = _tool_span("o", "notion-API-post-page", 1, _notion_out("A"))
    c = _tool_span("c", "notion-API-post-page", 100, _notion_out("B"))
    trace = _trace([o, c])
    (cand,) = scan_id_bridge_candidates(trace)
    assert cand.verdict == "differ"
    assert cand.origin_id == "A"
    assert cand.candidate_id == "B"


def test_id_bridge_verdict_same():
    body = _notion_out("SAME")
    o = _tool_span("o", "notion-API-post-page", 1, body)
    c = _tool_span("c", "notion-API-post-page", 100, body)
    trace = _trace([o, c])
    (cand,) = scan_id_bridge_candidates(trace)
    assert cand.verdict == "same"
    assert cand.origin_id == "SAME"
    assert cand.candidate_id == "SAME"


def test_id_bridge_verdict_no_id():
    """No extractable id on the candidate side → no_id."""
    o = _tool_span("o", "notion-API-post-page", 1, _notion_out("A"))
    c = _tool_span("c", "notion-API-post-page", 100, json.dumps({"no_field": "x"}))
    trace = _trace([o, c])
    (cand,) = scan_id_bridge_candidates(trace)
    assert cand.verdict == "no_id"


def test_id_bridge_verdict_no_id_on_error_response():
    o = _tool_span("o", "notion-API-post-page", 1, _notion_out("A"))
    c = _tool_span("c", "notion-API-post-page", 100, "internal server error, retry")
    trace = _trace([o, c])
    (cand,) = scan_id_bridge_candidates(trace)
    assert cand.verdict == "no_id"


def test_scan_id_bridge_pool_membership_is_side_effect_set():
    """Every candidate tool must be a member of _SIDE_EFFECT_TOOLS."""
    o = _tool_span("o", "notion-API-post-page", 1, _notion_out("A"))
    c = _tool_span("c", "notion-API-post-page", 100, _notion_out("B"))
    trace = _trace([o, c])
    for cand in scan_id_bridge_candidates(trace):
        assert cand.tool in _SIDE_EFFECT_TOOLS


# ────────────────────────── Toolathlon reproduction ─────────────────────────

def test_id_bridge_toolathlon_distribution_reproduces_pool_a():
    """PREREG §1.5 KILL gate: Toolathlon 66-file scan must reproduce
    frozen 3,432 / 159 / 76 / 3,197 distribution.
    """
    from collections import Counter
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    if not (root / "data" / "toolathlon" / "hf").is_dir():
        import pytest
        pytest.skip("Toolathlon dataset not available in this environment")

    from clew.ingest.toolathlon import _build_trace_from_entry, _iter_raw_lines

    cnt: Counter[str] = Counter()
    total = 0
    for path in sorted((root / "data" / "toolathlon" / "hf").glob("*.jsonl")):
        for lineno, entry in _iter_raw_lines(path):
            try:
                trace = _build_trace_from_entry(entry, lineno)
            except Exception:
                continue
            for cand in scan_id_bridge_candidates(trace):
                total += 1
                cnt[cand.verdict] += 1

    assert total == 3432, f"total pool != 3432 (got {total})"
    assert cnt["differ"] == 159, f"differ != 159 (got {cnt['differ']})"
    assert cnt["same"] == 76, f"same != 76 (got {cnt['same']})"
    assert cnt["no_id"] == 3197, f"no_id != 3197 (got {cnt['no_id']})"


def test_waste_span_ids_bit_identical_post_id_bridge():
    """PREREG §2.1 #1: cascade waste_span_ids unchanged. Frozen sha256s from
    docs/COVERAGE_TRANSPARENCY_PREREG.md §2 (b21/b23 baseline).
    """
    import hashlib
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    if not (root / "data" / "toolathlon" / "hf").is_dir():
        import pytest
        pytest.skip("Toolathlon dataset not available in this environment")

    diag = root / "field_test" / "diagnostics"
    sys.path.insert(0, str(diag))
    from greyzone_judge_feasibility import (  # noqa: E402
        TOOLATHLON_DIR,
        collect_waste_pairs,
    )
    from clew.ingest.toolathlon import _build_trace_from_entry, _iter_raw_lines

    cand_lines: list[str] = []
    pair_lines: list[str] = []
    for path in sorted(TOOLATHLON_DIR.glob("*.jsonl")):
        for lineno, entry in _iter_raw_lines(path):
            try:
                trace = _build_trace_from_entry(entry, lineno)
            except Exception:
                continue
            for origin, cand in collect_waste_pairs(trace):
                cand_lines.append(f"{trace.trace_id}\t{cand.span_id}")
                pair_lines.append(f"{trace.trace_id}\t{origin.span_id}\t{cand.span_id}")

    cand_lines.sort()
    pair_lines.sort()
    cand_sha = hashlib.sha256("\n".join(cand_lines).encode()).hexdigest()
    pair_sha = hashlib.sha256("\n".join(pair_lines).encode()).hexdigest()
    assert cand_sha == "5c0c94d680fe4741dd5df6d3cc928a0bba59af6c595e7037df088926b04d47d4"
    assert pair_sha == "742b51a75b67648cedf14d37cf9ea9d4dbc5d9237fe5ee798eeb2c1455fd45a0"


def test_between_window_counts_stable_post_id_bridge():
    """PREREG §2.1 #2: 5-enum counts unchanged after id-bridge layer added.
    Uses a small local trace (reuses the fast in-memory gate)."""
    origin = _tool_span("o", "filesystem-read_file", 1)
    unmapped = _tool_span("w", "some-unmapped-writer", 10)
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, unmapped, cand])
    wd = WasteDetail(origin=origin, candidate=cand, cosine=1.0)
    cr = _cascade_result([origin, unmapped, cand], ["c"])
    out = json.loads(render_json(trace, cr, [wd]))
    assert out["between_window_counts"] == {
        "declarative": 0, "no_side_effect": 1, "payload_dependent": 0,
        "targeted_writes": 0, "high_volume": 0,
    }


# ────────────────────────── JSON schema ─────────────────────────────────────

def test_json_id_bridge_candidates_field_present():
    o = _tool_span("o", "notion-API-post-page", 1, _notion_out("A"))
    c = _tool_span("c", "notion-API-post-page", 100, _notion_out("B"))
    trace = _trace([o, c])
    wd = WasteDetail(origin=o, candidate=c, cosine=1.0)
    cr = _cascade_result([o, c], [])
    out = json.loads(render_json(trace, cr, [wd]))
    assert "id_bridge_candidates" in out
    assert isinstance(out["id_bridge_candidates"], list)
    assert len(out["id_bridge_candidates"]) == 1
    entry = out["id_bridge_candidates"][0]
    assert entry["tool"] == "notion-API-post-page"
    assert entry["verdict"] == "differ"
    assert entry["origin_id"] == "A"
    assert entry["candidate_id"] == "B"


def test_json_id_bridge_empty_when_no_side_effect_pairs():
    """When no side_effect same-input pair exists, the array is empty (not omitted)."""
    o = _tool_span("o", "filesystem-read_file", 1, "same")
    c = _tool_span("c", "filesystem-read_file", 100, "same")
    trace = _trace([o, c])
    wd = WasteDetail(origin=o, candidate=c, cosine=1.0)
    cr = _cascade_result([o, c], ["c"])
    out = json.loads(render_json(trace, cr, [wd]))
    assert out["id_bridge_candidates"] == []


def test_json_id_bridge_backward_compat_no_side_effect_waste_zero():
    """Waste-0, no side-effect pair → empty array present; old fields intact."""
    s = _tool_span("s", "filesystem-read_file", 1)
    trace = _trace([s])
    cr = _cascade_result([s], [])
    out = json.loads(render_json(trace, cr, []))
    assert out["wasteful"] is False
    assert out["id_bridge_candidates"] == []
    # old fields still there
    assert "coverage_stats" in out
    assert "between_window_counts" in out


# ────────────────────────── Markdown rendering ──────────────────────────────

def test_markdown_duplicate_creation_section_present():
    """Section header + intro line render on any trace with side_effect pair."""
    o = _tool_span("o", "notion-API-post-page", 1, _notion_out("A"))
    c = _tool_span("c", "notion-API-post-page", 100, _notion_out("B"))
    trace = _trace([o, c])
    wd = WasteDetail(origin=o, candidate=c, cosine=1.0)
    cr = _cascade_result([o, c], [])
    md = render_markdown(trace, cr, [wd])
    assert "## Duplicate creation check" in md
    assert "waste detector above requires both responses to be byte-identical" in md


def test_markdown_section_shows_zero_when_pool_empty_but_rendered():
    """PREREG §1.6 decision 3: `0 candidates` line rendered explicitly.

    A waste-detected trace with side_effect Writes (which are candidates in
    principle) but with sha256-differing outputs still enters the pool. To
    hit the empty branch reliably we craft a trace whose only side_effect
    tool is not called twice — no pair, no candidates. The section must
    still render on waste-detected traces? PREREG says the empty branch is
    for `Pool = 0`. Waste-detected case renders section regardless.
    """
    # waste_detected but pool = 0: cascade waste on read tool; no side_effect
    # tool called twice.
    origin = _tool_span("o", "filesystem-read_file", 1)
    cand = _tool_span("c", "filesystem-read_file", 100)
    trace = _trace([origin, cand])
    wd = WasteDetail(origin=origin, candidate=cand, cosine=1.0)
    cr = _cascade_result([origin, cand], ["c"])
    md = render_markdown(trace, cr, [wd])
    assert "## Duplicate creation check" in md
    assert "0 candidates found in this trace." in md


def test_markdown_section_renders_in_waste_zero_with_pool():
    """PREREG §1.6 decision 4: section renders even when cr.wasteful is False,
    provided the id-bridge pool is nonempty. Prevents hidden findings."""
    # No cascade waste (differing sha256 → not flagged), but id-bridge pool has 1 pair.
    o = _tool_span("o", "notion-API-post-page", 1, _notion_out("A"))
    c = _tool_span("c", "notion-API-post-page", 100, _notion_out("B"))
    trace = _trace([o, c])
    cr = _cascade_result([o, c], [])  # wasteful=False
    md = render_markdown(trace, cr, [])
    assert "no waste detected" in md.lower()
    assert "## Duplicate creation check" in md
    # differ per-candidate wording is present
    assert "and they differ" in md


def test_markdown_section_absent_in_waste_zero_when_pool_empty():
    """PREREG §1.6 decision 3 (converse): when waste-0 and pool = 0, do not
    render the section. The section is meaningful only when checked."""
    s = _tool_span("s", "filesystem-read_file", 1)
    trace = _trace([s])
    cr = _cascade_result([s], [])
    md = render_markdown(trace, cr, [])
    assert "no waste detected" in md.lower()
    assert "## Duplicate creation check" not in md


def test_markdown_position_between_waste_details_and_possible_causes():
    """PREREG §1.6 decision 2: section sits between the "Wasted Span Details"
    block and "Possible causes"."""
    # waste-detected + side_effect pair present
    o = _tool_span("o", "notion-API-post-page", 1, _notion_out("A"))
    c = _tool_span("c", "notion-API-post-page", 100, _notion_out("B"))
    trace = _trace([o, c])
    wd = WasteDetail(origin=o, candidate=c, cosine=1.0)
    cr = _cascade_result([o, c], ["c"])
    md = render_markdown(trace, cr, [wd])
    pos_details = md.find("## Wasted Span Details")
    pos_dup = md.find("## Duplicate creation check")
    pos_causes = md.find("## Possible causes")
    assert 0 < pos_details < pos_dup < pos_causes, (
        f"Order broken: details={pos_details}, dup={pos_dup}, causes={pos_causes}"
    )


def test_markdown_full_id_not_truncated():
    """PREREG §1.6 decision 5: entity IDs verbatim, no `…` truncation."""
    long_id_a = "290d1b2a-abcdefab-cdef-0123456789abcdef" + "x" * 50
    long_id_b = "290d1b2a-abcdefab-cdef-0123456789abcdef" + "y" * 50
    o = _tool_span("o", "notion-API-post-page", 1, _notion_out(long_id_a))
    c = _tool_span("c", "notion-API-post-page", 100, _notion_out(long_id_b))
    trace = _trace([o, c])
    cr = _cascade_result([o, c], [])
    md = render_markdown(trace, cr, [])
    assert long_id_a in md
    assert long_id_b in md
    # Between the "and they differ:" wording and the newline, no ellipsis.
    line = next(l for l in md.splitlines() if "and they differ" in l)
    assert "…" not in line and "..." not in line


# ────────────────────────── wording guards ──────────────────────────────────

_BANNED = [
    "confirmed waste", "verified waste", "proven waste",
    "waste confirmed", "waste verified",
    "guaranteed waste", "definite waste",
]


def test_no_over_claim_wording_in_id_bridge_constants():
    from clew.report.markdown import (
        _DUPLICATE_CREATION_INTRO,
        _ID_BRIDGE_VERDICT_DIFFER,
        _ID_BRIDGE_VERDICT_NO_ID,
        _ID_BRIDGE_VERDICT_SAME,
    )
    for txt in (
        _DUPLICATE_CREATION_INTRO,
        _ID_BRIDGE_VERDICT_DIFFER,
        _ID_BRIDGE_VERDICT_SAME,
        _ID_BRIDGE_VERDICT_NO_ID,
    ):
        low = txt.lower()
        for phrase in _BANNED:
            assert phrase not in low, f"banned '{phrase}' in id-bridge constant"
        assert "provable" not in low, "renderer wording must not use 'provable'"


def test_no_over_claim_wording_in_rendered_output_with_id_bridge():
    """Guard on actual rendered output for every verdict path."""
    # differ
    o = _tool_span("o", "notion-API-post-page", 1, _notion_out("A"))
    c = _tool_span("c", "notion-API-post-page", 100, _notion_out("B"))
    trace = _trace([o, c])
    cr = _cascade_result([o, c], [])
    md = render_markdown(trace, cr, [])
    low = md.lower()
    for phrase in _BANNED:
        assert phrase not in low
    assert "provable" not in low

    # same
    body = _notion_out("SAME")
    o = _tool_span("o", "notion-API-post-page", 1, body)
    c = _tool_span("c", "notion-API-post-page", 100, body)
    trace = _trace([o, c])
    cr = _cascade_result([o, c], [])
    md = render_markdown(trace, cr, [])
    low = md.lower()
    for phrase in _BANNED:
        assert phrase not in low
    assert "provable" not in low

    # no_id
    o = _tool_span("o", "notion-API-post-page", 1, _notion_out("A"))
    c = _tool_span("c", "notion-API-post-page", 100, "err")
    trace = _trace([o, c])
    cr = _cascade_result([o, c], [])
    md = render_markdown(trace, cr, [])
    low = md.lower()
    for phrase in _BANNED:
        assert phrase not in low
    assert "provable" not in low


# ─────────────── raw_output_text fallback (openinference §5.4) ─────────────

def test_id_bridge_fallback_reads_raw_output_text_on_langgraph_path():
    """T-3: on the langgraph/openinference path, preprocess rewrites tool
    span output_text to the processed leaf ("Login broken"), but raw_output_text
    keeps the original dict. extract_entity_id via scan_id_bridge_candidates
    reads `raw_output_text or output_text`, so a user-registered
    `entity_id: ticket.id` recovers T-1041 / T-1042 → verdict "differ"."""
    from pathlib import Path
    from clew.config.user_tools import resolve_user_tools
    from clew.ingest.otel_json import ingest_from_otel_json

    fixture = Path(__file__).parent / "fixtures" / "openinference_dict_tool_raw.json"
    trace = ingest_from_otel_json(fixture)
    tools = resolve_user_tools(
        {"create_ticket": "side_effect"},
        {"create_ticket": "ticket.id"},
    )

    candidates = scan_id_bridge_candidates(trace, tools)
    ticket_cands = [c for c in candidates if c.tool == "create_ticket"]
    assert len(ticket_cands) == 1, (
        f"expected exactly one create_ticket pair, got {len(ticket_cands)}: {ticket_cands}"
    )
    c = ticket_cands[0]
    assert c.verdict == "differ", (
        f"expected differ verdict from raw_output_text ID extraction, got {c.verdict}"
    )
    assert {c.origin_id, c.candidate_id} == {"T-1041", "T-1042"}, (
        f"expected ID pair T-1041 / T-1042, got origin={c.origin_id} cand={c.candidate_id}"
    )


def test_id_bridge_fallback_uses_output_text_when_raw_is_none():
    """T-4: on paths where preprocess did not run (CC / Toolathlon / RB),
    raw_output_text stays None and the fallback `raw or output_text` reads
    the untouched output_text. Verifies extract_entity_id still works."""
    body_a = json.dumps({"id": "N-1"})
    body_b = json.dumps({"id": "N-2"})
    o = Span(
        trace_id="t", span_id="o", parent_span_id="root",
        agent_or_node_id="notion-API-post-page", span_kind="tool",
        start_time=_ts(1), end_time=_ts(1),
        input_text="{}", output_text=body_a, token_count=5,
        model="fake", cost_rate=1e-6,
        raw_output_text=None,
    )
    c = Span(
        trace_id="t", span_id="c", parent_span_id="root",
        agent_or_node_id="notion-API-post-page", span_kind="tool",
        start_time=_ts(2), end_time=_ts(2),
        input_text="{}", output_text=body_b, token_count=5,
        model="fake", cost_rate=1e-6,
        raw_output_text=None,
    )
    trace = _trace([o, c])
    candidates = scan_id_bridge_candidates(trace, tools=None)
    assert len(candidates) == 1
    got = candidates[0]
    assert got.verdict == "differ"
    assert {got.origin_id, got.candidate_id} == {"N-1", "N-2"}


# ────────────────────────── README subsection lock ──────────────────────────

def test_readme_has_duplicate_creation_check_subsection():
    """b23 §5 standing rule (extended): README documents the new detector."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "Duplicate creation check" in readme, (
        "README must document the duplicate creation check detector "
        "(per docs/ID_BRIDGE_PRODUCTION_PREREG.md §1.8)."
    )
    # sanity: no 'provable' in the README section
    assert "provable" not in readme.lower()


def test_readme_has_entity_id_path_per_framework_table():
    """Tier 1 Results §5.2 → README: users need to know entity_id path
    depends on the OpenInference instrumentor. Only measured framework
    paths are locked here; unmeasured frameworks must not be added
    without a probe."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    # Section header presence
    assert "Path depends on the OpenInference instrumentor you use" in readme, (
        "README must document that entity_id path varies by instrumentor "
        "(per docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md §5.2)."
    )
    # Measured instrumentors — must be listed
    for name in (
        "openinference-instrumentation-langchain",
        "openinference-instrumentation-crewai",
        "openinference-instrumentation-openai-agents",
        "openinference-instrumentation-llama-index",
    ):
        assert name in readme, f"README missing measured instrumentor {name!r}"
    # LlamaIndex envelope prefix must be shown explicitly
    assert "raw_output.ticket.id" in readme, (
        "README must show LlamaIndex envelope prefix explicitly."
    )
    # Guardrail: unmeasured framework paths must not be advertised.
    assert "Anthropic" not in readme.split("Path depends on the OpenInference")[1].split("Runtime signals")[0], (
        "README table must not list Anthropic (FAIL — no tool span emitted)."
    )
    assert "AutoGen" not in readme.split("Path depends on the OpenInference")[1].split("Runtime signals")[0], (
        "README table must not list AutoGen (FAIL — Python str(dict) is invalid JSON)."
    )
    # Fallback guidance must point users at the trace JSON when their
    # instrumentor isn't in the table.
    assert "output.value" in readme.split("Path depends on the OpenInference")[1].split("Runtime signals")[0]
