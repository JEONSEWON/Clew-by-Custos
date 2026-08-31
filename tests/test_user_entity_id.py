"""tests/test_user_entity_id.py — clew.yaml Phase 2 entity_id.

Design doc: field_test/diagnostics/clew_yaml_phase2_entity_id_PREREG.md.

Covers:
  §2.1 CREATE-only enforcement (entity_id on non-side_effect → error).
  §2.2 dot-path grammar (arrays / brackets / wildcards / empty segments).
  §2.3 extraction ratio computation.
  §2.4 built-in / user banner split + precision footnote.
  §2.5 suspicious tail warns (message_id / event_id excluded per Q3).
  §3.1 id_bridge parity (built-in overlap rejected; user-only pool intact).
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from clew.config import (
    UserToolConfigError,
    emit_load_warnings,
    load_user_config,
    resolve_user_tools,
)
from clew.detect.cascade import CascadeResult
from clew.model import Span, Trace
from clew.report._enrich import (
    IdBridgeCandidate,
    compute_user_extraction_ratios,
    extract_entity_id,
    format_extraction_ratios,
    scan_id_bridge_candidates,
)
from clew.report.markdown import render_markdown
from clew.report.json_report import render_json


T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _pair_trace(tool: str, out_a: str, out_b: str, span_input: str = "q") -> Trace:
    """Trace with two identical-input tool spans (waste candidate for id_bridge)."""
    root = Span(
        trace_id="t", span_id="root", parent_span_id=None,
        agent_or_node_id="root", span_kind="chain",
        start_time=T0, end_time=T0 + timedelta(seconds=10),
        input_text="x", output_text="root",
    )
    a = Span(
        trace_id="t", span_id="s1", parent_span_id="root",
        agent_or_node_id=tool, span_kind="tool",
        start_time=T0 + timedelta(seconds=1), end_time=T0 + timedelta(seconds=2),
        input_text=span_input, output_text=out_a,
    )
    b = Span(
        trace_id="t", span_id="s2", parent_span_id="root",
        agent_or_node_id=tool, span_kind="tool",
        start_time=T0 + timedelta(seconds=3), end_time=T0 + timedelta(seconds=4),
        input_text=span_input, output_text=out_b,
    )
    return Trace(trace_id="t", spans=[root, a, b])


def _make_cr() -> CascadeResult:
    return CascadeResult(trace_id="t", wasteful=False, waste_span_ids=[])


# ── §2.1 CREATE-only enforcement (entity_id only on side_effect) ────────────


def test_entity_id_on_read_only_raises(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text(
        "version: 1\ntools:\n  my_get:\n    category: read_only\n    entity_id: id\n",
        encoding="utf-8",
    )
    with pytest.raises(UserToolConfigError, match="category='read_only'"):
        load_user_config(p)


def test_entity_id_on_payload_dependent_raises(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text(
        "version: 1\ntools:\n  my_sh:\n    category: payload_dependent\n    entity_id: id\n",
        encoding="utf-8",
    )
    with pytest.raises(UserToolConfigError, match="category='payload_dependent'"):
        load_user_config(p)


def test_entity_id_on_declarative_raises(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text(
        "version: 1\ntools:\n  finish:\n    category: declarative\n    entity_id: id\n",
        encoding="utf-8",
    )
    with pytest.raises(UserToolConfigError, match="category='declarative'"):
        load_user_config(p)


def test_error_message_contains_newly_created_wording(tmp_path: Path):
    """Q1 confirmed wording — the error must state the create-vs-query distinction."""
    p = tmp_path / "clew.yaml"
    p.write_text(
        "version: 1\ntools:\n  my_get:\n    category: read_only\n    entity_id: id\n",
        encoding="utf-8",
    )
    with pytest.raises(UserToolConfigError) as exc_info:
        load_user_config(p)
    msg = str(exc_info.value)
    assert "NEWLY CREATES" in msg
    assert "queried, opened, or listed" in msg


# ── §2.2 grammar (arrays / brackets / wildcards / empty segments) ───────────


def test_bracket_notation_rejected(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text(
        "version: 1\ntools:\n  create_x:\n    category: side_effect\n    entity_id: 'response[0].id'\n",
        encoding="utf-8",
    )
    with pytest.raises(UserToolConfigError, match="may not contain"):
        load_user_config(p)


def test_wildcard_rejected(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text(
        "version: 1\ntools:\n  create_x:\n    category: side_effect\n    entity_id: 'response.*.id'\n",
        encoding="utf-8",
    )
    with pytest.raises(UserToolConfigError, match="may not contain"):
        load_user_config(p)


def test_jsonpath_dollar_rejected(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text(
        "version: 1\ntools:\n  create_x:\n    category: side_effect\n    entity_id: '$.response.id'\n",
        encoding="utf-8",
    )
    with pytest.raises(UserToolConfigError, match="may not contain"):
        load_user_config(p)


def test_numeric_segment_rejected(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text(
        "version: 1\ntools:\n  create_x:\n    category: side_effect\n    entity_id: 'response.0.id'\n",
        encoding="utf-8",
    )
    with pytest.raises(UserToolConfigError, match="numeric"):
        load_user_config(p)


def test_empty_segment_rejected(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text(
        "version: 1\ntools:\n  create_x:\n    category: side_effect\n    entity_id: 'response..id'\n",
        encoding="utf-8",
    )
    with pytest.raises(UserToolConfigError, match="empty segment"):
        load_user_config(p)


def test_empty_string_rejected(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text(
        "version: 1\ntools:\n  create_x:\n    category: side_effect\n    entity_id: ''\n",
        encoding="utf-8",
    )
    with pytest.raises(UserToolConfigError, match="non-empty"):
        load_user_config(p)


def test_non_string_type_rejected(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text(
        "version: 1\ntools:\n  create_x:\n    category: side_effect\n    entity_id: [id]\n",
        encoding="utf-8",
    )
    with pytest.raises(UserToolConfigError, match="must be a string"):
        load_user_config(p)


def test_valid_dot_path_accepted(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text(
        "version: 1\ntools:\n  create_x:\n    category: side_effect\n    entity_id: response.ticket.id\n",
        encoding="utf-8",
    )
    r = load_user_config(p)
    assert r.user_entity_id_map == {"create_x": "response.ticket.id"}


def test_top_level_id_path_accepted(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text(
        "version: 1\ntools:\n  create_x:\n    category: side_effect\n    entity_id: id\n",
        encoding="utf-8",
    )
    r = load_user_config(p)
    assert r.user_entity_id_map == {"create_x": "id"}


# ── §2.3 extraction: user_entity_id_map path fallback ───────────────────────


def test_extract_entity_id_user_map_hit():
    r = resolve_user_tools(
        {"create_x": "side_effect"},
        {"create_x": "response.id"},
    )
    body = json.dumps({"response": {"id": "T-42"}})
    assert extract_entity_id("create_x", body, r.user_entity_id_map) == "T-42"


def test_extract_entity_id_user_map_miss_returns_none():
    r = resolve_user_tools(
        {"create_x": "side_effect"},
        {"create_x": "response.id"},
    )
    body = json.dumps({"different": "shape"})
    assert extract_entity_id("create_x", body, r.user_entity_id_map) is None


def test_extract_entity_id_none_when_no_maps():
    assert extract_entity_id("unknown_tool", '{"id":"1"}', None) is None


# ── source field + banner split ─────────────────────────────────────────────


def test_scan_id_bridge_marks_user_source():
    r = resolve_user_tools(
        {"create_x": "side_effect"},
        {"create_x": "id"},
    )
    trace = _pair_trace(
        "create_x",
        out_a=json.dumps({"id": "e-1"}),
        out_b=json.dumps({"id": "e-2"}),
    )
    cands = scan_id_bridge_candidates(trace, r)
    assert len(cands) == 1
    assert cands[0].source == "user"
    assert cands[0].verdict == "differ"


def test_scan_id_bridge_marks_builtin_source_when_no_user_config():
    # github-create_pull_request is a built-in side_effect + built-in ID mapping
    trace = _pair_trace(
        "github-create_pull_request",
        out_a='{"html_url": "https://github.com/x/y/pull/1"}',
        out_b='{"html_url": "https://github.com/x/y/pull/2"}',
    )
    cands = scan_id_bridge_candidates(trace)
    assert cands[0].source == "built-in"


def test_render_markdown_banner_split_present_with_user():
    r = resolve_user_tools(
        {"create_x": "side_effect"},
        {"create_x": "id"},
    )
    trace = _pair_trace(
        "create_x",
        out_a=json.dumps({"id": "e-1"}),
        out_b=json.dumps({"id": "e-2"}),
    )
    md = render_markdown(trace, _make_cr(), [], user_tools=r)
    assert "built-in:" in md
    assert "user-registered:" in md
    assert "Precision bounds on the built-in mappings" in md
    assert "user-registered mappings are unverified" in md.lower() or (
        "User-registered mappings are unverified" in md
    )


def test_render_markdown_no_split_without_user():
    """§3 parity: without user config, no built-in/user split lines, no footnote."""
    trace = _pair_trace(
        "github-create_pull_request",
        out_a='{"html_url": "https://github.com/x/y/pull/1"}',
        out_b='{"html_url": "https://github.com/x/y/pull/2"}',
    )
    md = render_markdown(trace, _make_cr(), [])
    assert "built-in:" not in md
    assert "user-registered:" not in md
    assert "Precision bounds on the built-in mappings" not in md


def test_json_source_field_present_for_user_candidate():
    r = resolve_user_tools(
        {"create_x": "side_effect"},
        {"create_x": "id"},
    )
    trace = _pair_trace(
        "create_x",
        out_a=json.dumps({"id": "e-1"}),
        out_b=json.dumps({"id": "e-2"}),
    )
    j = json.loads(render_json(trace, _make_cr(), [], user_tools=r))
    assert j["id_bridge_candidates"][0]["source"] == "user"


def test_json_source_field_builtin_for_built_in_mapping():
    trace = _pair_trace(
        "github-create_pull_request",
        out_a='{"html_url": "https://github.com/x/y/pull/1"}',
        out_b='{"html_url": "https://github.com/x/y/pull/2"}',
    )
    j = json.loads(render_json(trace, _make_cr(), []))
    assert j["id_bridge_candidates"][0]["source"] == "built-in"


# ── §3.1 gate: built-in overlap rejected at load time ──────────────────────


def test_user_entity_id_on_built_in_tool_raises(tmp_path: Path):
    # notion-API-post-page is in _ID_BRIDGE_MAPPING already.
    p = tmp_path / "clew.yaml"
    p.write_text(
        "version: 1\ntools:\n  'notion-API-post-page':\n"
        "    category: side_effect\n    entity_id: response.override.id\n",
        encoding="utf-8",
    )
    with pytest.raises(UserToolConfigError, match="conflicts with built-in"):
        load_user_config(p)


# ── §2.5 suspicious tail warns (Q3 confirmed frozen list) ──────────────────


@pytest.mark.parametrize("tail", [
    "request_id", "req_id", "correlation_id", "corr_id",
    "trace_id", "span_id", "session_id",
    "call_id", "run_id",
])
def test_suspicious_tails_produce_warn(tail: str):
    r = resolve_user_tools(
        {"log_x": "side_effect"},
        {"log_x": f"response.{tail}"},
    )
    assert r.entity_id_warnings
    combined = " ".join(r.entity_id_warnings)
    assert tail in combined
    # New wording (openinference_output_text_fix_PREREG.md §2.4): one-line
    # summary + Full context URL. The 요지 for correlation-style tails is
    # "identify calls, not entities".
    assert "identify calls" in combined
    assert "https://github.com/boxdawn/boxdawn/blob/main/docs/ID_BRIDGE_SCOPE_PRINCIPLE.md" in combined


def test_transaction_id_uses_ambiguous_wording():
    r = resolve_user_tools(
        {"pay_x": "side_effect"},
        {"pay_x": "response.transaction_id"},
    )
    assert r.entity_id_warnings
    warn = r.entity_id_warnings[0]
    assert "payment/financial" in warn
    # Payment-domain 요지 + URL.
    assert "payment_id or ticket_id" in warn
    assert "https://github.com/boxdawn/boxdawn/blob/main/docs/ID_BRIDGE_SCOPE_PRINCIPLE.md" in warn


def test_message_id_produces_no_warn():
    """Q3 correction — message_id is a legitimate entity ID for send tools."""
    r = resolve_user_tools(
        {"send_email": "side_effect"},
        {"send_email": "response.message_id"},
    )
    assert r.entity_id_warnings == ()


def test_event_id_produces_no_warn():
    """Q3 correction — event_id is a legitimate entity ID for create_event tools."""
    r = resolve_user_tools(
        {"create_event": "side_effect"},
        {"create_event": "response.event_id"},
    )
    assert r.entity_id_warnings == ()


def test_casefold_and_dash_normalization_matches():
    r = resolve_user_tools(
        {"log_x": "side_effect"},
        {"log_x": "response.REQUEST-ID"},
    )
    assert r.entity_id_warnings  # normalized match


def test_emit_load_warnings_prints_entity_id_warns():
    r = resolve_user_tools(
        {"log_x": "side_effect"},
        {"log_x": "response.request_id"},
    )
    buf = io.StringIO()
    emit_load_warnings(r, stream=buf)
    out = buf.getvalue()
    assert "request_id" in out


# ── Q5 extraction ratio computation + format ───────────────────────────────


def test_compute_ratios_all_failed():
    c1 = IdBridgeCandidate("s1", "s2", "create_x", "no_id", None, None, source="user")
    c2 = IdBridgeCandidate("s3", "s4", "create_x", "no_id", None, None, source="user")
    ratios = compute_user_extraction_ratios([c1, c2])
    assert ratios == {"create_x": (4, 4)}


def test_compute_ratios_all_success():
    c1 = IdBridgeCandidate("s1", "s2", "create_x", "differ", "A", "B", source="user")
    ratios = compute_user_extraction_ratios([c1])
    assert ratios == {"create_x": (0, 2)}


def test_compute_ratios_partial_failure():
    c1 = IdBridgeCandidate("s1", "s2", "create_x", "no_id", "A", None, source="user")
    c2 = IdBridgeCandidate("s3", "s4", "create_x", "differ", "A", "B", source="user")
    ratios = compute_user_extraction_ratios([c1, c2])
    assert ratios == {"create_x": (1, 4)}


def test_compute_ratios_ignores_builtin_source():
    c_user = IdBridgeCandidate("s1", "s2", "create_x", "no_id", None, None, source="user")
    c_bi = IdBridgeCandidate("s3", "s4", "gh_write", "no_id", None, None, source="built-in")
    ratios = compute_user_extraction_ratios([c_user, c_bi])
    assert "gh_write" not in ratios


def test_format_ratios_labels_full_failure():
    out = format_extraction_ratios({"create_x": (4, 4)})
    assert out is not None
    assert "4/4" in out
    assert "path likely misconfigured" in out


def test_format_ratios_labels_partial():
    out = format_extraction_ratios({"send_x": (1, 8)})
    assert out is not None
    assert "1/8" in out
    assert "partial, response variance" in out


def test_format_ratios_omits_zero_failure_line():
    """0/N — no line emitted (Q5 confirmed noise reduction)."""
    out = format_extraction_ratios({"clean_x": (0, 6)})
    assert out is None


def test_format_ratios_includes_envelope_prefix_hint_on_failure():
    """Tier 1 §5.2 hint: any failure line triggers an envelope-prefix hint
    that names LlamaIndex explicitly (measured envelope) and points to the
    Tier 1 results doc. See docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md §5.2."""
    out = format_extraction_ratios({"create_x": (4, 4)})
    assert out is not None
    # Existing lines must still be present (unchanged).
    assert "4/4" in out
    assert "path likely misconfigured" in out
    # New hint line.
    assert "hint:" in out
    assert "LlamaIndex" in out
    assert "raw_output" in out
    assert "OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md" in out


def test_format_ratios_hint_absent_when_no_failures():
    """The hint is meaningful only alongside a failure line. When all-success
    the output stays None (no line at all), so the hint doesn't leak into an
    unrelated context."""
    out = format_extraction_ratios({"clean_x": (0, 6)})
    assert out is None


def test_format_ratios_hint_appears_once_regardless_of_tool_count():
    """Multiple failing tools still emit a single hint line at the end."""
    out = format_extraction_ratios({"a_tool": (3, 3), "b_tool": (2, 4)})
    assert out is not None
    assert out.count("hint:") == 1


def test_format_ratios_multi_tool_sorted():
    out = format_extraction_ratios({
        "zebra": (2, 2),
        "alpha": (1, 3),
    })
    assert out is not None
    # Alpha first (alphabetical).
    idx_alpha = out.index("alpha")
    idx_zebra = out.index("zebra")
    assert idx_alpha < idx_zebra


# ── §3 parity anchor ───────────────────────────────────────────────────────


def test_id_bridge_builtin_pool_unchanged_by_user_config_without_entity_ids():
    """Loading clew.yaml with categories but no entity_id must not touch built-in pool."""
    r = resolve_user_tools({"my_tool": "side_effect"}, {})
    # No entity_id → user_entity_id_map empty.
    assert not r.has_user_entity_ids
    # The built-in side_effect set is now extended (Phase 1 behavior) but that
    # is orthogonal to the built-in ID bridge pool.
    assert "my_tool" in r.side_effect
    assert r.user_entity_id_map == {}


def test_reserved_field_id_regex_url_rejected(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text(
        "version: 1\ntools:\n  x:\n    category: side_effect\n    id_regex_url: '/pull/(\\d+)'\n",
        encoding="utf-8",
    )
    with pytest.raises(UserToolConfigError, match="reserved field"):
        load_user_config(p)


def test_reserved_field_entity_type_rejected(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text(
        "version: 1\ntools:\n  x:\n    category: side_effect\n    entity_type: ticket\n",
        encoding="utf-8",
    )
    with pytest.raises(UserToolConfigError, match="reserved field"):
        load_user_config(p)


def test_forbidden_word_provable_absent_from_banner():
    """The frozen precision footnote must not smuggle 'provable' back in."""
    r = resolve_user_tools(
        {"create_x": "side_effect"},
        {"create_x": "id"},
    )
    trace = _pair_trace(
        "create_x",
        out_a=json.dumps({"id": "e-1"}),
        out_b=json.dumps({"id": "e-2"}),
    )
    md = render_markdown(trace, _make_cr(), [], user_tools=r)
    assert "provable" not in md.lower()
