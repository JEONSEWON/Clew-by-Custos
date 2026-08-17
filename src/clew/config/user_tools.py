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

# User-facing messages reference the ID bridge scope doc via URL rather than
# a local docs/ path — `pip install boxdawn` users have no docs/ tree.
# The message body still carries the one-line summary so the URL is only for
# extra context, not required reading.
_GITHUB_BASE = "https://github.com/boxdawn/boxdawn/blob/main"
_ID_BRIDGE_URL = f"{_GITHUB_BASE}/docs/ID_BRIDGE_SCOPE_PRINCIPLE.md"

# Phase 2 entity_id validation
# Suspicious tail segments — Q3 confirmed frozen list. Message_id/event_id
# excluded because they are legitimate entity IDs for email `send` and
# calendar `create_event` respectively (see design doc §2.5).
_SUSPICIOUS_TAIL_PATTERNS = frozenset({
    "requestid", "reqid",
    "correlationid", "corrid",
    "traceid",
    "spanid",
    "sessionid",
    "callid", "runid",
    "transactionid", "txnid",
})
# Patterns that get the "transaction can be a first-class entity" nuance in
# the warn text (payment/financial domains).
_AMBIGUOUS_TAIL_PATTERNS = frozenset({"transactionid", "txnid"})
_PHASE3_KEYS = frozenset({
    # Reserved for future extensions. Reject to fail loud on typos / mixed configs.
    "id_field", "id_regex_url", "id_extractor", "entity_type",
})


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

    # Phase 2: user-registered entity_id paths. Stored as sorted tuple for
    # frozen-dataclass compatibility; access via `user_entity_id_map` property.
    user_entity_id_pairs: tuple[tuple[str, str], ...] = ()
    # Suspicious tail warns (frozen after resolve). Tuple to stay immutable.
    entity_id_warnings: tuple[str, ...] = ()

    @property
    def has_user_tools(self) -> bool:
        return bool(self.user_names)

    @property
    def user_entity_id_map(self) -> dict[str, str]:
        return dict(self.user_entity_id_pairs)

    @property
    def has_user_entity_ids(self) -> bool:
        return bool(self.user_entity_id_pairs)


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
            f"{path}: unsupported version {version!r} (this Boxdawn supports "
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

    # Reject Phase 3+ fields early so mixed configs fail loud.
    _reject_phase3_fields(path, tools_raw)

    user_categories, user_entity_ids = _validate_tools_dict(path, tools_raw)
    return resolve_user_tools(user_categories, user_entity_ids)


def _reject_phase3_fields(path: Path, tools_raw: dict) -> None:
    """Phase 2 owns `entity_id`. Everything else in the reserved list is future work."""
    for tool_name, spec in tools_raw.items():
        if not isinstance(spec, dict):
            continue
        offenders = _PHASE3_KEYS & set(spec.keys())
        if offenders:
            raise UserToolConfigError(
                f"{path}: tool {tool_name!r} contains reserved field(s) "
                f"{sorted(offenders)} — not supported in this Boxdawn version"
            )


def _validate_tools_dict(
    path: Path, tools_raw: dict
) -> tuple[dict[str, str], dict[str, str]]:
    """Return ({tool_name: category}, {tool_name: entity_id_path}) after §2.6/§2.1-§2.2 validation."""
    seen: dict[str, str] = {}
    entity_ids: dict[str, str] = {}
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

        # Phase 2 — entity_id validation.
        if "entity_id" in spec:
            _validate_entity_id(path, name, category, spec["entity_id"])
            entity_ids[name] = spec["entity_id"]

    return seen, entity_ids


def _validate_entity_id(path: Path, name: str, category: str, value: Any) -> None:
    """§2.1 CREATE-only + §2.2 dot-path grammar.

    Rejects:
      - non-side_effect category (Q1).
      - non-string value.
      - bracket / wildcard / JSONPath sigils.
      - empty string, empty segments, numeric segments (array index rejected, Q2).
    """
    # Q1 — CREATE-only: entity_id only allowed on side_effect.
    if category != "side_effect":
        raise UserToolConfigError(
            f"{path}: tool {name!r} has entity_id but category={category!r}. "
            f"entity_id is for tools whose call NEWLY CREATES an entity, not "
            f"for tools that returned an entity that was queried, opened, or "
            f"listed. Full context: {_ID_BRIDGE_URL}"
        )
    if not isinstance(value, str):
        raise UserToolConfigError(
            f"{path}: tool {name!r} — entity_id must be a string, got "
            f"{type(value).__name__}"
        )
    if not value:
        raise UserToolConfigError(
            f"{path}: tool {name!r} — entity_id must be non-empty"
        )
    # Q2 — grammar: reject sigils outright.
    for bad in ("[", "]", "*", "$"):
        if bad in value:
            raise UserToolConfigError(
                f"{path}: tool {name!r} — entity_id may not contain {bad!r}. "
                f"Only dot-separated path is supported (e.g. 'response.ticket.id'). "
                f"Array indices are intentionally rejected — see design doc §2.2."
            )
    segments = value.split(".")
    for i, seg in enumerate(segments):
        if not seg:
            raise UserToolConfigError(
                f"{path}: tool {name!r} — entity_id has empty segment at "
                f"position {i} in {value!r}"
            )
        if seg.isdigit():
            # Numeric segment == implicit array index. Also rejected (Q2).
            raise UserToolConfigError(
                f"{path}: tool {name!r} — entity_id segment {seg!r} is numeric. "
                f"Array indices are intentionally rejected — see design doc §2.2."
            )


def _normalize_tail(segment: str) -> str:
    """casefold + strip underscores/dashes for suspicious-tail match."""
    return segment.casefold().replace("_", "").replace("-", "")


def _suspicious_warn_for(name: str, path_str: str) -> str | None:
    """Return a warn line iff the last segment matches a suspicious tail pattern.

    Two message variants (Q3 confirmed):
      - transaction_id / txn_id → ambiguous (payment domain caveat).
      - other patterns → generic request-identifier warn.
    """
    tail = path_str.rsplit(".", 1)[-1]
    normalized = _normalize_tail(tail)
    if normalized not in _SUSPICIOUS_TAIL_PATTERNS:
        return None
    if normalized in _AMBIGUOUS_TAIL_PATTERNS:
        return (
            f"boxdawn: entity_id path for {name!r} ends in {tail!r} — transaction "
            f"identifiers are ambiguous: in payment/financial domains a "
            f"transaction can be a first-class entity, but elsewhere it names "
            f"the call, not what was created. Prefer payment_id or ticket_id "
            f"when the entity is what you want to dedupe. "
            f"Full context: {_ID_BRIDGE_URL}"
        )
    return (
        f"boxdawn: entity_id path for {name!r} ends in {tail!r} — correlation IDs "
        f"identify calls, not entities, so pinning entity_id to them will not "
        f"detect duplicate creation. "
        f"Full context: {_ID_BRIDGE_URL}"
    )


def resolve_user_tools(
    user_categories: dict[str, str],
    user_entity_ids: dict[str, str] | None = None,
) -> ResolvedTools:
    """Compose ResolvedTools from user_categories + user_entity_ids + built-in snapshot.

    Rebuildable purely from inputs — used by loader and tests.

    Also validates against the built-in ID bridge mapping: user cannot override
    an entity_id that Boxdawn already knows (frozen §3.1 gate). Suspicious tail
    warns are collected into `entity_id_warnings` (frozen tuple).
    """
    from clew.report._enrich import _ID_BRIDGE_MAPPING  # noqa: PLC0415

    if user_entity_ids is None:
        user_entity_ids = {}

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

    # Phase 2 — validate entity_id doesn't collide with the built-in mapping.
    warnings: list[str] = []
    for tool_name, path_str in user_entity_ids.items():
        if tool_name in _ID_BRIDGE_MAPPING:
            raise UserToolConfigError(
                f"tool {tool_name!r}: entity_id conflicts with built-in ID "
                f"mapping. Built-in extraction takes precedence — remove "
                f"entity_id from your config for this tool."
            )
        warn = _suspicious_warn_for(tool_name, path_str)
        if warn is not None:
            warnings.append(warn)

    return ResolvedTools(
        idempotent=frozenset(idem),
        side_effect=frozenset(side),
        bw_side_effect=frozenset(bw_side),
        bw_declarative=frozenset(bw_decl),
        bw_blackbox=frozenset(bw_bb),
        user_names=frozenset(user_names),
        override_names=frozenset(override_names),
        override_details=tuple(sorted(override_details)),
        user_entity_id_pairs=tuple(sorted(user_entity_ids.items())),
        entity_id_warnings=tuple(warnings),
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
        f"boxdawn: ignored clew.yaml at {p} (already loaded {winner})"
        for p in ignored
    ]


def emit_load_warnings(
    tools: ResolvedTools,
    *,
    stream=None,
) -> None:
    """Print load-time warnings (Phase 1 override + Phase 2 suspicious tails) to stderr.

    Called once per CLI invocation, right after loading clew.yaml.
    """
    if stream is None:
        stream = sys.stderr
    line = format_override_warning(tools)
    if line is not None:
        print(line, file=stream)
    for warn in tools.entity_id_warnings:
        print(warn, file=stream)
