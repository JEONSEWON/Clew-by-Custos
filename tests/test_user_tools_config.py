"""tests/test_user_tools_config.py — clew.yaml loader + report threading.

Covers gates §5.2–§5.6 from the local design doc
(field_test/diagnostics/clew_yaml_user_tools_PREREG.md).

§5.1 no-config parity is enforced by the existing 343-test suite — those
tests never pass `user_tools`, so any regression would show up there.
This module adds explicit parity assertions on top.
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from clew.config import (
    ResolvedTools,
    UserToolConfigError,
    builtin_tools,
    emit_load_warnings,
    find_clew_yaml,
    format_override_warning,
    load_user_config,
    resolve_user_tools,
)
from clew.detect.cascade import CascadeResult
from clew.model import Span, Trace
from clew.report._enrich import (
    _classify_between_window,
    _classify_category,
    coverage_stats,
    enrich,
)
from clew.report.markdown import (
    _COVERAGE_PRECISION_FOOTNOTE,
    _format_coverage_provenance,
    render_markdown,
)
from clew.report.json_report import render_json


T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _tool_span(sid: str, name: str, out: str = "ok") -> Span:
    return Span(
        trace_id="t", span_id=sid, parent_span_id="root",
        agent_or_node_id=name, span_kind="tool",
        start_time=T0, end_time=T0,
        input_text="q", output_text=out,
    )


def _minimal_trace(names: list[str]) -> Trace:
    spans = [
        Span(
            trace_id="t", span_id="root", parent_span_id=None,
            agent_or_node_id="root", span_kind="chain",
            start_time=T0, end_time=T0,
            input_text="x", output_text="root",
        ),
    ] + [_tool_span(f"s{i}", n) for i, n in enumerate(names, 1)]
    return Trace(trace_id="t", spans=spans)


def _make_cr() -> CascadeResult:
    return CascadeResult(trace_id="t", wasteful=False, waste_span_ids=[])


# ── §5.2 config-loaded regression ────────────────────────────────────────────


def test_read_only_maps_to_idempotent(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text("version: 1\ntools:\n  my_search: {category: read_only}\n", encoding="utf-8")
    r = load_user_config(p)
    assert "my_search" in r.idempotent
    assert "my_search" not in r.side_effect


def test_side_effect_maps_to_both_side_effect_sets(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text(
        "version: 1\ntools:\n  create_ticket: {category: side_effect}\n",
        encoding="utf-8",
    )
    r = load_user_config(p)
    assert "create_ticket" in r.side_effect
    assert "create_ticket" in r.bw_side_effect


def test_payload_dependent_stays_out_of_side_effect(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text(
        "version: 1\ntools:\n  my_shell: {category: payload_dependent}\n",
        encoding="utf-8",
    )
    r = load_user_config(p)
    # Report category stays 'unclassified': my_shell NOT in outer side_effect.
    assert "my_shell" not in r.side_effect
    assert "my_shell" not in r.idempotent
    # But between_window treats it as state-changing (Bash-style).
    assert "my_shell" in r.bw_side_effect
    assert "my_shell" in r.bw_blackbox


def test_declarative_maps_to_bw_declarative_and_idempotent(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text(
        "version: 1\ntools:\n  finalize: {category: declarative}\n",
        encoding="utf-8",
    )
    r = load_user_config(p)
    assert "finalize" in r.bw_declarative
    assert "finalize" in r.idempotent


def test_classify_category_uses_user_tools():
    tools = resolve_user_tools({"my_search": "read_only", "create_x": "side_effect"})
    s_search = _tool_span("s1", "my_search")
    s_create = _tool_span("s2", "create_x")
    assert _classify_category(s_search, tools) == "idempotent"
    assert _classify_category(s_create, tools) == "side_effect"


def test_classify_category_without_tools_unchanged():
    """§5.1 parity anchor: tools=None must reproduce built-in-only classification."""
    s = _tool_span("s1", "my_search")
    assert _classify_category(s) == "unclassified"


def test_classify_between_window_uses_user_bw_declarative():
    tools = resolve_user_tools({"finalize": "declarative"})
    trace = _minimal_trace(["finalize"])
    origin = trace.spans[1]
    cand = trace.spans[1]  # same span — declarative check hits before the interval scan
    assert _classify_between_window(trace, origin, cand, tools) == "declarative"


# ── §5.3 override banner + 3-count sum ───────────────────────────────────────


def test_override_names_populated():
    # Bash is a built-in payload_dependent tool
    r = resolve_user_tools({"Bash": "read_only"})
    assert "Bash" in r.override_names
    assert r.override_details == (("Bash", "payload_dependent", "read_only"),)


def test_override_not_flagged_when_category_matches_builtin():
    """User declaring the same category as built-in should not count as override."""
    # `Read` is already idempotent (read-only). Declaring it read_only is a no-op.
    r = resolve_user_tools({"Read": "read_only"})
    assert "Read" in r.user_names
    assert "Read" not in r.override_names


def test_coverage_stats_three_count_sum_equals_recognized():
    tools = resolve_user_tools({
        "my_search": "read_only",       # new
        "create_x": "side_effect",      # new
        "Bash": "read_only",            # override
    })
    # Trace: my_search, create_x, Bash (all recognized after user config), plus Read (built-in)
    trace = _minimal_trace(["my_search", "create_x", "Bash", "Read"])
    cov = coverage_stats(trace, [], tools)
    assert cov["recognized_tools"] == 4
    total = (
        cov["built_in_count"]
        + cov["user_count"]
        + cov["user_overriding_built_in_count"]
    )
    assert total == 4
    assert cov["user_overriding_built_in_count"] == 1  # Bash


def test_coverage_stats_no_provenance_keys_when_no_user_tools():
    trace = _minimal_trace(["Read"])
    cov = coverage_stats(trace, [])
    assert "built_in_count" not in cov
    assert "user_count" not in cov
    assert "user_overriding_built_in_count" not in cov


def test_render_markdown_provenance_line_present_with_user_tools():
    tools = resolve_user_tools({"my_search": "read_only", "Bash": "read_only"})
    trace = _minimal_trace(["my_search", "Bash"])
    cr = _make_cr()
    md = render_markdown(trace, cr, [], user_tools=tools)
    assert "Mapping source" in md
    assert "user-overriding-built-in" in md


def test_render_markdown_precision_footnote_present_with_user_tools():
    tools = resolve_user_tools({"my_search": "read_only"})
    trace = _minimal_trace(["my_search"])
    cr = _make_cr()
    md = render_markdown(trace, cr, [], user_tools=tools)
    assert "Precision bounds were measured on built-in mappings" in md
    assert "user-registered tools are unverified" in md


def test_render_markdown_no_provenance_when_no_user_tools():
    """§5.1 parity: baseline banner must not carry user-tool language."""
    trace = _minimal_trace(["my_search"])
    cr = _make_cr()
    md = render_markdown(trace, cr, [])
    assert "Mapping source" not in md
    assert "user-registered tools are unverified" not in md


def test_json_user_tools_applied_field_present():
    tools = resolve_user_tools({"my_search": "read_only", "Bash": "read_only"})
    trace = _minimal_trace(["my_search", "Bash"])
    cr = _make_cr()
    jstr = render_json(trace, cr, [], user_tools=tools)
    data = json.loads(jstr)
    assert data["user_tools_applied"] is not None
    assert "Bash" in data["user_tools_applied"]["override_names"]
    assert sorted(data["user_tools_applied"]["user_names"]) == ["Bash", "my_search"]


def test_json_user_tools_applied_field_null_without_config():
    """§5.1 parity: baseline JSON must carry user_tools_applied=null."""
    trace = _minimal_trace(["my_search"])
    cr = _make_cr()
    jstr = render_json(trace, cr, [])
    data = json.loads(jstr)
    assert data["user_tools_applied"] is None


# ── §5.4 validation error regression (9 error cases) ─────────────────────────


def test_missing_version_raises(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text("tools:\n  x: {category: read_only}\n", encoding="utf-8")
    with pytest.raises(UserToolConfigError, match="missing 'version'"):
        load_user_config(p)


def test_unsupported_version_raises(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text("version: 2\ntools: {}\n", encoding="utf-8")
    with pytest.raises(UserToolConfigError, match="unsupported version"):
        load_user_config(p)


def test_missing_tools_raises(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text("version: 1\n", encoding="utf-8")
    with pytest.raises(UserToolConfigError, match="missing 'tools'"):
        load_user_config(p)


def test_tools_not_mapping_raises(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text("version: 1\ntools: [a, b]\n", encoding="utf-8")
    with pytest.raises(UserToolConfigError, match="'tools' must be a mapping"):
        load_user_config(p)


def test_tool_missing_category_raises(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text("version: 1\ntools:\n  x: {description: foo}\n", encoding="utf-8")
    with pytest.raises(UserToolConfigError, match="missing 'category'"):
        load_user_config(p)


def test_unknown_category_raises(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text(
        "version: 1\ntools:\n  x: {category: idempotent}\n",  # 'idempotent' is internal, not user-facing
        encoding="utf-8",
    )
    with pytest.raises(UserToolConfigError, match="unknown category"):
        load_user_config(p)


def test_tool_spec_not_mapping_raises(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text("version: 1\ntools:\n  x: read_only\n", encoding="utf-8")
    with pytest.raises(UserToolConfigError, match="value must be a mapping"):
        load_user_config(p)


def test_yaml_parse_error_raises(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text("version: 1\ntools:\n  x: {category: read_only\n", encoding="utf-8")
    with pytest.raises(UserToolConfigError, match="invalid YAML"):
        load_user_config(p)


def test_empty_yaml_raises(tmp_path: Path):
    p = tmp_path / "clew.yaml"
    p.write_text("", encoding="utf-8")
    with pytest.raises(UserToolConfigError, match="empty config"):
        load_user_config(p)


def test_reserved_field_rejected(tmp_path: Path):
    """`id_field` was the design-draft name; Phase 2 shipped as `entity_id`.
    Reject the older / reserved field name to fail loud on typos."""
    p = tmp_path / "clew.yaml"
    p.write_text(
        "version: 1\ntools:\n  create_x:\n    category: side_effect\n    id_field: response.id\n",
        encoding="utf-8",
    )
    with pytest.raises(UserToolConfigError, match="reserved field"):
        load_user_config(p)


def test_empty_tools_dict_is_allowed(tmp_path: Path):
    """Explicit `tools: {}` is a valid no-op — no user tools registered."""
    p = tmp_path / "clew.yaml"
    p.write_text("version: 1\ntools: {}\n", encoding="utf-8")
    r = load_user_config(p)
    assert not r.has_user_tools


# ── §5.5 discovery order (mocked filesystem) ─────────────────────────────────


def test_discovery_explicit_beats_walk_up(tmp_path: Path):
    trace_dir = tmp_path / "project" / "traces"
    trace_dir.mkdir(parents=True)
    walk_up = tmp_path / "project" / "clew.yaml"
    walk_up.write_text("version: 1\ntools: {}\n", encoding="utf-8")

    explicit = tmp_path / "override.yaml"
    explicit.write_text("version: 1\ntools: {}\n", encoding="utf-8")

    trace_path = trace_dir / "trace.json"
    trace_path.write_text("{}", encoding="utf-8")

    found = find_clew_yaml(trace_path, explicit=explicit)
    assert found == explicit


def test_discovery_walk_up_from_trace_directory(tmp_path: Path):
    root = tmp_path / "project"
    trace_dir = root / "traces" / "day1"
    trace_dir.mkdir(parents=True)
    (root / "clew.yaml").write_text("version: 1\ntools: {}\n", encoding="utf-8")
    trace_path = trace_dir / "trace.json"
    trace_path.write_text("{}", encoding="utf-8")

    found = find_clew_yaml(trace_path)
    assert found == root / "clew.yaml"


def test_discovery_home_fallback(tmp_path: Path):
    fake_home = tmp_path / "home"
    (fake_home / ".clew").mkdir(parents=True)
    home_config = fake_home / ".clew" / "config.yaml"
    home_config.write_text("version: 1\ntools: {}\n", encoding="utf-8")

    lone_trace_dir = tmp_path / "elsewhere"
    lone_trace_dir.mkdir()
    trace_path = lone_trace_dir / "trace.json"
    trace_path.write_text("{}", encoding="utf-8")

    found = find_clew_yaml(trace_path, home=fake_home)
    assert found == home_config


def test_discovery_returns_none_when_nothing_found(tmp_path: Path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    trace_dir = tmp_path / "elsewhere"
    trace_dir.mkdir()
    trace_path = trace_dir / "trace.json"
    trace_path.write_text("{}", encoding="utf-8")
    assert find_clew_yaml(trace_path, home=fake_home) is None


def test_discovery_explicit_missing_file_raises(tmp_path: Path):
    with pytest.raises(UserToolConfigError, match="file not found"):
        find_clew_yaml(None, explicit=tmp_path / "nope.yaml")


# ── §5.6 banner text + override warning format ──────────────────────────────


def test_override_warning_format_matches_q3():
    r = resolve_user_tools({"Bash": "read_only", "Write": "read_only"})
    line = format_override_warning(r)
    # Alphabetical order, one line only.
    assert line == "clew.yaml overrides built-in mappings: Bash, Write"


def test_override_warning_absent_when_no_override():
    r = resolve_user_tools({"my_search": "read_only"})
    assert format_override_warning(r) is None


def test_emit_load_warnings_writes_to_stream():
    r = resolve_user_tools({"Bash": "read_only"})
    buf = io.StringIO()
    emit_load_warnings(r, stream=buf)
    assert "clew.yaml overrides built-in mappings: Bash" in buf.getvalue()


def test_emit_load_warnings_silent_when_no_override():
    r = resolve_user_tools({"my_search": "read_only"})
    buf = io.StringIO()
    emit_load_warnings(r, stream=buf)
    assert buf.getvalue() == ""


def test_precision_footnote_constant_matches_spec():
    """Q2 confirmed text — locked so we notice if someone rephrases it."""
    assert _COVERAGE_PRECISION_FOOTNOTE == (
        "_Precision bounds were measured on built-in mappings; "
        "user-registered tools are unverified._"
    )


def test_forbidden_word_provable_absent_in_markdown():
    """Forbidden-word grep gate: banner extension must not introduce 'provable'."""
    tools = resolve_user_tools({"my_search": "read_only", "Bash": "read_only"})
    trace = _minimal_trace(["my_search", "Bash"])
    cr = _make_cr()
    md = render_markdown(trace, cr, [], user_tools=tools)
    assert "provable" not in md.lower()


def test_format_coverage_provenance_none_without_keys():
    assert _format_coverage_provenance({"recognized_tools": 2}) is None


# ── §5.1 parity anchor (belt-and-suspenders) ────────────────────────────────


def test_builtin_tools_matches_module_frozensets():
    """builtin_tools() must equal the module-level frozensets exactly."""
    from clew.report._enrich import (
        _BW_BLACKBOX_TOOLS,
        _BW_DECLARATIVE_TOOLS,
        _BW_SIDE_EFFECT_TOOLS,
        _IDEMPOTENT_TOOLS,
        _SIDE_EFFECT_TOOLS,
    )
    bt = builtin_tools()
    assert bt.idempotent == _IDEMPOTENT_TOOLS
    assert bt.side_effect == _SIDE_EFFECT_TOOLS
    assert bt.bw_side_effect == _BW_SIDE_EFFECT_TOOLS
    assert bt.bw_declarative == _BW_DECLARATIVE_TOOLS
    assert bt.bw_blackbox == _BW_BLACKBOX_TOOLS
    assert not bt.has_user_tools


# ─────────────── §5.6 URL grep regression (openinference §2.4) ─────────────

def test_no_local_docs_path_left_in_user_facing_messages():
    """§5.6 (widened after friction #7 regression on 2026-08-01):
    NO user-facing message in src/ may reference ANY `docs/*.md` file as a
    local path. pip-install users have no docs/ tree. The previous version
    of this guard only checked docs/ID_BRIDGE_SCOPE_PRINCIPLE.md, so when a
    second such reference was added (docs/OPENINFERENCE_FRAMEWORK_EXPANSION_
    RESULTS.md in _ENVELOPE_PREFIX_HINT), the guard didn't catch it. Widened
    to any quoted docs/…/*.md pattern.

    Comments in the codebase (`# docs/…`) remain allowed; the guard scans
    string literals only (leading `#` lines skipped)."""
    import re
    from pathlib import Path
    src_root = Path(__file__).resolve().parents[1] / "src"
    # Widened pattern: any quoted docs/<anything>.md reference.
    # Matches `"docs/...md"`, `'docs/...md'`, backtick `` `docs/...md` ``.
    string_literal = re.compile(r'''['"`]docs/[A-Za-z0-9_/-]+\.md''')
    offenders = []
    for py in src_root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if string_literal.search(line):
                offenders.append(f"{py.relative_to(src_root)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "docs/*.md must not appear in user-facing string literals — pip-install "
        "users have no docs/ tree. Use the GitHub URL constant (_GITHUB_BASE) "
        "instead. Offenders:\n" + "\n".join(offenders)
    )


def test_no_local_docs_path_left_in_readme():
    """§5.6 companion: README.md is `readme = "README.md"` in pyproject.toml,
    so it becomes the PyPI project description — pip users see it without a
    docs/ tree. Any `docs/*.md` reference inside a link URL (i.e. the target
    of a Markdown link `](docs/...)`) breaks for those users.

    Guard: no `](docs/<...>.md` sequence may appear in README.md. Bare
    references like ``docs/CC_TRANSCRIPT.md §29`` outside a link are allowed
    (they are locators, not links)."""
    import re
    from pathlib import Path
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    # Match markdown link URL that points at a relative docs/*.md path.
    offenders = re.findall(r"\]\(docs/[A-Za-z0-9_/-]+\.md[^)]*\)", readme)
    assert not offenders, (
        "README.md contains relative `](docs/...)` links — pip users see this "
        "as PyPI long_description and have no docs/ tree. Use the GitHub URL "
        "(https://github.com/boxdawn/boxdawn/blob/main/docs/...) "
        "instead. Offenders:\n" + "\n".join(offenders)
    )


def test_entity_id_messages_use_github_url_and_one_line_summary():
    """§5.6 companion: the three affected messages carry the GitHub URL and
    surface a one-line 요지 before the URL. Failing this test signals someone
    stripped the summary back to a bare URL (which was the anti-pattern
    called out in the design doc)."""
    from clew.config.user_tools import _ID_BRIDGE_URL, _suspicious_warn_for
    assert _ID_BRIDGE_URL.startswith("https://github.com/boxdawn/boxdawn")
    # CREATE-only error uses the same URL and carries "NEWLY CREATES" summary.
    p = Path("clew.yaml.dummy")
    from clew.config.user_tools import _validate_entity_id
    try:
        _validate_entity_id(p, "get_x", "read_only", "id")
        raise AssertionError("expected raise")
    except UserToolConfigError as exc:
        msg = str(exc)
        assert "NEWLY CREATES" in msg
        assert _ID_BRIDGE_URL in msg
    # Suspicious tail warn (generic) carries the one-line "identify calls" summary.
    warn = _suspicious_warn_for("log_x", "response.request_id")
    assert warn is not None and "identify calls" in warn and _ID_BRIDGE_URL in warn
    # Transaction tail carries the payment nuance + URL.
    tx = _suspicious_warn_for("pay_x", "response.transaction_id")
    assert tx is not None and "payment_id or ticket_id" in tx and _ID_BRIDGE_URL in tx


def test_enrich_with_none_tools_matches_baseline():
    """Explicit assertion that tools=None reproduces default behavior."""
    from clew.report._model import WasteDetail

    trace = _minimal_trace(["Read", "Read"])
    o = trace.spans[1]
    c = trace.spans[2]
    wd = WasteDetail(origin=o, candidate=c, cosine=1.0)
    e_none = enrich(trace, [wd], None)
    e_default = enrich(trace, [wd])
    assert e_none.enriched[0].category == e_default.enriched[0].category
    assert e_none.enriched[0].between_window == e_default.enriched[0].between_window
