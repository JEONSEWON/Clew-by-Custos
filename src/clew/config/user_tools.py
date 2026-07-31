"""clew.yaml user-tool registration — loader + schema validation.

Design doc: field_test/diagnostics/clew_yaml_user_tools_PREREG.md (local, uncommitted).

Phase 1 scope: 4-category classification only.
  read_only         → _IDEMPOTENT_TOOLS
  side_effect       → _SIDE_EFFECT_TOOLS + _BW_SIDE_EFFECT_TOOLS
  payload_dependent → _BW_SIDE_EFFECT_TOOLS + _BW_BLACKBOX_TOOLS (unclassified stays)
  declarative       → _BW_DECLARATIVE_TOOLS + _IDEMPOTENT_TOOLS

Discovery: --config PATH  >  clew.yaml walk-up from trace file  >  ~/.clew/config.yaml.
No merging; first found wins.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ALLOWED_CATEGORIES = ("read_only", "side_effect", "payload_dependent", "declarative")
_SUPPORTED_VERSIONS = frozenset({1})
_WALK_UP_LIMIT = 5


class UserToolConfigError(ValueError):
    """Raised for any clew.yaml schema/validation failure."""


@dataclass(frozen=True)
class ResolvedTools:
    """Frozen union of built-in and user tool sets, plus provenance for the banner.

    All set fields are frozensets so shared state cannot be mutated.

    Provenance:
      user_names        — tool names registered by user (any category)
      override_names    — subset of user_names that override a built-in category
      override_details  — tuples of (name, built_in_category, user_category) for stderr line
    """

    idempotent: frozenset[str]
    side_effect: frozenset[str]
    bw_side_effect: frozenset[str]
    bw_declarative: frozenset[str]
    bw_blackbox: frozenset[str]

    user_names: frozenset[str] = frozenset()
    override_names: frozenset[str] = frozenset()
    override_details: tuple[tuple[str, str, str], ...] = ()

    @property
    def has_user_tools(self) -> bool:
        return bool(self.user_names)


def _builtin_snapshot() -> ResolvedTools:
    """Snapshot of the built-in tool sets as-imported. Fresh call each time."""
    # Local import avoids a circular reference at module import.
    from clew.report._enrich import (  # noqa: PLC0415
        _BW_BLACKBOX_TOOLS,
        _BW_DECLARATIVE_TOOLS,
        _BW_SIDE_EFFECT_TOOLS,
        _IDEMPOTENT_TOOLS,
        _SIDE_EFFECT_TOOLS,
    )
    return ResolvedTools(
        idempotent=_IDEMPOTENT_TOOLS,
        side_effect=_SIDE_EFFECT_TOOLS,
        bw_side_effect=_BW_SIDE_EFFECT_TOOLS,
        bw_declarative=_BW_DECLARATIVE_TOOLS,
        bw_blackbox=_BW_BLACKBOX_TOOLS,
    )


def builtin_tools() -> ResolvedTools:
    """No-op default when no clew.yaml is loaded. Preserves §3 gate parity."""
    return _builtin_snapshot()


def _builtin_category_of(name: str, snap: ResolvedTools) -> str | None:
    """Return the built-in classification of `name`, or None if unrecognized.

    Ordering mirrors the report-side priority:
      side_effect > idempotent > payload_dependent (bw-only) > None
    """
    if name in snap.side_effect:
        return "side_effect"
    if name in snap.bw_declarative:
        return "declarative"
    if name in snap.idempotent:
        return "read_only"
    if name in snap.bw_blackbox:
        return "payload_dependent"
    if name in snap.bw_side_effect:
        # Reached only when the tool sits in bw-side-effect but not the outer side_effect
        # set (e.g. Bash/PowerShell). Report the operational classification.
        return "payload_dependent"
    return None


# ── YAML load + schema validation ────────────────────────────────────────────


def load_user_config(path: Path) -> ResolvedTools:
    """Load clew.yaml, validate schema, and compose ResolvedTools.

    Raises UserToolConfigError on any schema violation (§2.6 fail-fast).
    """
    try:
        import yaml  # noqa: PLC0415
    except ImportError as exc:
        raise UserToolConfigError(
            f"{path}: pyyaml is required to load clew.yaml (`pip install pyyaml`)"
        ) from exc

    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise UserToolConfigError(f"{path}: invalid YAML — {exc}") from exc

    if data is None:
        raise UserToolConfigError(
            f"{path}: empty config — expected 'version: 1' and 'tools' mapping"
        )
    if not isinstance(data, dict):
        raise UserToolConfigError(
            f"{path}: top-level must be a mapping, got {type(data).__name__}"
        )

    if "version" not in data:
        raise UserToolConfigError(
            f"{path}: missing 'version' — expected 'version: 1'"
        )
    version = data["version"]
    if version not in _SUPPORTED_VERSIONS:
        raise UserToolConfigError(
            f"{path}: unsupported version {version!r} (this Clew supports "
            f"version {sorted(_SUPPORTED_VERSIONS)})"
        )

    if "tools" not in data:
        raise UserToolConfigError(
            f"{path}: missing 'tools' key — nothing to register"
        )
    tools_raw = data["tools"]
    if not isinstance(tools_raw, dict):
        raise UserToolConfigError(
            f"{path}: 'tools' must be a mapping, got {type(tools_raw).__name__}"
        )

    # Reject Phase 2 fields early so mixed configs fail loud.
    _reject_phase2_fields(path, tools_raw)

    user_categories = _validate_tools_dict(path, tools_raw)
    return resolve_user_tools(user_categories)


def _reject_phase2_fields(path: Path, tools_raw: dict) -> None:
    phase2_keys = {"id_field", "id_regex_url", "id_extractor"}
    for tool_name, spec in tools_raw.items():
        if not isinstance(spec, dict):
            continue
        offenders = phase2_keys & set(spec.keys())
        if offenders:
            raise UserToolConfigError(
                f"{path}: tool {tool_name!r} contains Phase 2 field(s) "
                f"{sorted(offenders)} — not supported in this Clew version"
            )


def _validate_tools_dict(path: Path, tools_raw: dict) -> dict[str, str]:
    """Return {tool_name: category} after §2.6 validation."""
    seen: dict[str, str] = {}
    for name, spec in tools_raw.items():
        if not isinstance(name, str):
            raise UserToolConfigError(
                f"{path}: tool name must be a string, got {type(name).__name__} "
                f"({name!r})"
            )
        if not name:
            raise UserToolConfigError(f"{path}: empty tool name is not allowed")
        if name in seen:
            raise UserToolConfigError(f"{path}: tool {name!r} defined twice")
        if not isinstance(spec, dict):
            raise UserToolConfigError(
                f"{path}: tool {name!r} — value must be a mapping, got "
                f"{type(spec).__name__}"
            )
        if "category" not in spec:
            raise UserToolConfigError(
                f"{path}: tool {name!r} missing 'category'"
            )
        category = spec["category"]
        if category not in _ALLOWED_CATEGORIES:
            raise UserToolConfigError(
                f"{path}: tool {name!r} — unknown category {category!r} "
                f"(allowed: {', '.join(_ALLOWED_CATEGORIES)})"
            )
        seen[name] = category
    return seen


def resolve_user_tools(user_categories: dict[str, str]) -> ResolvedTools:
    """Compose ResolvedTools from user_categories dict + built-in snapshot.

    Rebuildable purely from `user_categories` — used by loader and tests.
    """
    snap = _builtin_snapshot()

    idem = set(snap.idempotent)
    side = set(snap.side_effect)
    bw_side = set(snap.bw_side_effect)
    bw_decl = set(snap.bw_declarative)
    bw_bb = set(snap.bw_blackbox)

    user_names: set[str] = set()
    override_names: set[str] = set()
    override_details: list[tuple[str, str, str]] = []

    for name, category in user_categories.items():
        user_names.add(name)
        built_in = _builtin_category_of(name, snap)
        if built_in is not None and built_in != category:
            override_names.add(name)
            override_details.append((name, built_in, category))

        # Category assignment per §2.2 table.
        if category == "read_only":
            idem.add(name)
        elif category == "side_effect":
            side.add(name)
            bw_side.add(name)
        elif category == "payload_dependent":
            bw_side.add(name)
            bw_bb.add(name)
            # NOTE: payload_dependent stays out of _SIDE_EFFECT_TOOLS by design
            # (report category remains 'unclassified' — mirrors Bash/PowerShell).
        elif category == "declarative":
            bw_decl.add(name)
            idem.add(name)

    return ResolvedTools(
        idempotent=frozenset(idem),
        side_effect=frozenset(side),
        bw_side_effect=frozenset(bw_side),
        bw_declarative=frozenset(bw_decl),
        bw_blackbox=frozenset(bw_bb),
        user_names=frozenset(user_names),
        override_names=frozenset(override_names),
        override_details=tuple(sorted(override_details)),
    )


# ── Discovery ────────────────────────────────────────────────────────────────


def find_clew_yaml(
    trace_path: Path | None,
    *,
    explicit: Path | None = None,
    home: Path | None = None,
) -> Path | None:
    """§2.1 discovery: explicit --config > trace-file walk-up > ~/.clew/config.yaml.

    Returns the first existing path or None. Never merges.

    `home` is an injection point for tests.
    """
    if explicit is not None:
        if not explicit.exists():
            raise UserToolConfigError(f"--config {explicit}: file not found")
        return explicit

    # Walk-up from trace file's directory (max 5 levels or git root).
    if trace_path is not None:
        start = trace_path.resolve().parent
        current = start
        for _ in range(_WALK_UP_LIMIT + 1):
            candidate = current / "clew.yaml"
            if candidate.is_file():
                return candidate
            # Stop at git root or filesystem root.
            if (current / ".git").exists():
                break
            if current.parent == current:
                break
            current = current.parent

    # Fallback: ~/.clew/config.yaml
    if home is None:
        home = Path.home()
    global_config = home / ".clew" / "config.yaml"
    if global_config.is_file():
        return global_config

    return None


def format_override_warning(tools: ResolvedTools) -> str | None:
    """One-line stderr warning when overrides exist (§2.4, Q3 confirmed).

    Returns None when no overrides — no warning printed.
    """
    if not tools.override_names:
        return None
    names = ", ".join(sorted(tools.override_names))
    return f"clew.yaml overrides built-in mappings: {names}"


def format_ignored_files(ignored: list[Path], winner: Path) -> list[str]:
    """§2.1: additional clew.yaml files beyond the first found → stderr info lines."""
    return [
        f"clew: ignored clew.yaml at {p} (already loaded {winner})"
        for p in ignored
    ]


def emit_load_warnings(
    tools: ResolvedTools,
    *,
    stream=None,
) -> None:
    """Print load-time warnings (§2.4 override, Q3) to stderr.

    Called once per CLI invocation, right after loading clew.yaml.
    """
    if stream is None:
        stream = sys.stderr
    line = format_override_warning(tools)
    if line is not None:
        print(line, file=stream)
