# Spec: docs/REDUNDANT_READ_DETECTOR_PREREG.md (frozen Rule 8 prereg).
"""Redundant Read Detector — cross-adapter deterministic detection.

Detects tool span pairs where the same read tool is invoked on the same
target within a single trace, with no intervening write to that target
and no Bash/PowerShell in the interval (conservative gate — payload-
opaque tools may mutate state).

Cost model: waste tokens = tokens(cand.output_text); waste_cost =
waste_tokens × next-turn LLM input rate (tier-aware via pricing.py).

Deterministic guarantees:
- sha256 chunk equality (target hash for search-style tools)
- Fixed tool-name sets reused from `report/_enrich.py`
- pricing.py resolution (soft-fails to default)

No LLM-as-judge, no embedding. Prereg §5 interface frozen.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from clew.cost.pricing import get_pricing
from clew.detect.context_resend import _rate_and_cost_for_call
from clew.detect.structural import _nearest_agent_ancestor_id
from clew.model import Span, Trace

if TYPE_CHECKING:
    from clew.config import ResolvedTools


# Local helpers — inlined to avoid the report → detect circular import.
# The authoritative definitions still live in clew/report/_enrich.py; these
# are read-only copies of the small helpers used by this detector.

_FILE_KEYS = ("file_path", "path", "filename", "notebook_path")


def _parse_input(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _file_path_of(obj: Any) -> str | None:
    if not isinstance(obj, dict):
        return None
    for k in _FILE_KEYS:
        v = obj.get(k)
        if isinstance(v, str) and v:
            return v
    return None


CostAccuracy = Literal["accurate", "estimated"]


# ── Frozen tool-name sets (prereg §2) ───────────────────────────────────────

# Excluded from _IDEMPOTENT_TOOLS despite being idempotent — they are not
# "reads" in the sense that returns content the LLM will re-consume.
_NON_READ_IDEMPOTENT = frozenset({
    "local-claim_done",             # declarative marker
    "filesystem-create_directory",  # state-changing but no-op on repeat
})

# Shell / payload-opaque tools — conservative gate (§1 gate 4).
_SHELL_TOOLS: frozenset[str] = frozenset({
    "Bash", "PowerShell",
    "terminal-run_command", "local-python-execute",
})

# _READ_TOOLS / _WRITE_TOOLS come from clew.report._enrich sets. Imported
# lazily inside _resolve_tool_sets() to break the report → detect
# circular import (report/__init__.py loads json_report which loads this
# module).

_READ_TOOLS_CACHE: frozenset[str] | None = None
_WRITE_TOOLS_CACHE: frozenset[str] | None = None


def _load_tool_sets() -> tuple[frozenset[str], frozenset[str]]:
    """Lazy load the read/write tool sets from report._enrich."""
    global _READ_TOOLS_CACHE, _WRITE_TOOLS_CACHE
    if _READ_TOOLS_CACHE is None or _WRITE_TOOLS_CACHE is None:
        # Local import breaks the circular chain: report/__init__.py
        # → json_report → this module → report._enrich → __init__ (cycle).
        # By deferring the import to first-call, module load succeeds.
        from clew.report._enrich import (  # noqa: PLC0415
            _BW_SIDE_EFFECT_TOOLS,
            _IDEMPOTENT_TOOLS,
        )
        _READ_TOOLS_CACHE = frozenset(_IDEMPOTENT_TOOLS) - _NON_READ_IDEMPOTENT
        _WRITE_TOOLS_CACHE = frozenset(_BW_SIDE_EFFECT_TOOLS)
    return _READ_TOOLS_CACHE, _WRITE_TOOLS_CACHE


# ── Target extraction (prereg §3) ───────────────────────────────────────────

_URL_KEYS = ("url", "uri", "endpoint")


def _extract_target(input_text: str) -> str | None:
    """Prereg §3: path key → URL → query hash → None. Deterministic."""
    parsed = _parse_input(input_text)
    if not isinstance(parsed, dict):
        return None

    # (1) path-like key
    fp = _file_path_of(parsed)
    if fp:
        return os.path.normpath(fp).casefold()

    # (2) URL
    for k in _URL_KEYS:
        v = parsed.get(k)
        if isinstance(v, str) and v:
            u = v.lower().rstrip("/")
            return u

    # (3) query hash — canonical JSON, sorted keys
    try:
        canonical = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return None
    if not canonical:
        return None
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── Token estimation (prereg §4) ────────────────────────────────────────────

def _tiktoken_len(text: str, model: str | None = None) -> int:
    """Best-effort token length. tiktoken when available, else char/4."""
    if not text:
        return 0
    try:
        import tiktoken

        enc_name = "cl100k_base"
        if model and ("gpt-4o" in model.lower() or "o200k" in model.lower()):
            enc_name = "o200k_base"
        try:
            enc = tiktoken.get_encoding(enc_name)
            return max(1, len(enc.encode(text)))
        except Exception:
            return max(1, len(text) // 4)
    except ImportError:
        return max(1, len(text) // 4)


# ── Interface ───────────────────────────────────────────────────────────────

@dataclass
class RedundantReadEvent:
    read_span_id: str
    origin_read_span_id: str
    tool_name: str
    target: str
    waste_tokens: int
    waste_cost: float
    confirmed: bool


@dataclass
class RedundantReadResult:
    trace_id: str
    events: list[RedundantReadEvent] = field(default_factory=list)
    total_waste_tokens: int = 0
    total_waste_cost: float = 0.0
    cost_accuracy_flag: CostAccuracy = "accurate"


# ── Detector ───────────────────────────────────────────────────────────────

def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _resolve_tool_sets(
    tools: "ResolvedTools | None",
) -> tuple[frozenset[str], frozenset[str]]:
    """Read / write tool sets, extended with user config when provided."""
    read_tools, write_tools = _load_tool_sets()
    if tools is None:
        return read_tools, write_tools

    # ResolvedTools has .idempotent / .side_effect / .bw_side_effect. The
    # user's idempotent set may include entries the built-in read set
    # excluded (e.g. local-claim_done). We keep the built-in exclusion —
    # user-declared entries that overlap with _NON_READ_IDEMPOTENT stay
    # excluded to avoid mis-classifying non-content tools as reads.
    user_reads = frozenset(tools.idempotent) - _NON_READ_IDEMPOTENT
    reads = read_tools | user_reads
    writes = write_tools | frozenset(tools.bw_side_effect)
    return reads, writes


def _next_llm_call_after(
    llm_calls: list[dict[str, Any]], after_time: datetime,
) -> dict[str, Any] | None:
    """First LLM call whose start_time is strictly after `after_time`.

    Falls back to the most recent call if none is strictly-after
    (retrospective attribution per prereg §4).
    """
    if not llm_calls:
        return None
    for call in llm_calls:
        ts = call.get("start_time")
        try:
            call_time = datetime.fromisoformat(ts.replace("Z", "+00:00")) if isinstance(ts, str) else None
        except (ValueError, AttributeError):
            call_time = None
        if call_time and call_time > after_time:
            return call
    return llm_calls[-1]


def _resolve_rate_for_read(
    trace: Trace, cand_end: datetime,
) -> tuple[float, bool]:
    """(per-token input rate at next LLM call, was_accurate).

    Prereg §4: use tier-aware pricing via _rate_and_cost_for_call. If no
    LLM calls in trace, use pricing.py default. If no next call after
    cand_end, use the most recent call (retrospective).
    """
    llm_calls = list(trace.metadata.get("llm_calls") or [])
    next_call = _next_llm_call_after(llm_calls, cand_end)
    if next_call is None:
        pricing = get_pricing(None)
        return pricing.base_input_per_mtok / 1_000_000.0, False

    eff_rate, _, _ = _rate_and_cost_for_call(next_call)
    # Consider accurate iff the call had tier-split or explicit rate. Same
    # rule as _rate_and_cost_for_call's own accuracy determination.
    has_split = (
        next_call.get("input_tokens_uncached") is not None
        or next_call.get("input_tokens_cache_read") is not None
        or next_call.get("input_tokens_cache_write") is not None
    )
    has_flat = next_call.get("input_cost_rate") is not None
    accurate = has_split or has_flat
    return eff_rate, accurate


def find_redundant_reads(
    trace: Trace,
    *,
    tools: "ResolvedTools | None" = None,
) -> RedundantReadResult:
    """Detect and cost redundant read events (prereg §1-4).

    Args:
        trace: post-preprocess trace.
        tools: optional user-tool resolution (`clew.yaml`). Extends
            read/write sets when provided.

    Returns:
        `RedundantReadResult` with per-event breakdown and totals.
    """
    result = RedundantReadResult(trace_id=trace.trace_id)
    reads, writes = _resolve_tool_sets(tools)

    # Filter to tool spans, ordered by start_time.
    tool_spans = sorted(
        [s for s in trace.spans if s.span_kind == "tool"],
        key=lambda s: s.start_time,
    )
    if len(tool_spans) < 2:
        return result

    spans_by_id = {s.span_id: s for s in trace.spans}

    # Pre-compute target and read-flag per tool span.
    span_meta: dict[str, tuple[str | None, bool, bool, bool]] = {}
    for s in tool_spans:
        name = s.agent_or_node_id
        is_read = name in reads
        is_write = name in writes
        is_shell = name in _SHELL_TOOLS
        target = _extract_target(s.input_text) if is_read or is_write else None
        span_meta[s.span_id] = (target, is_read, is_write, is_shell)

    # Group read spans by target (only reads with a real target).
    reads_by_target: dict[str, list[Span]] = {}
    for s in tool_spans:
        target, is_read, _, _ = span_meta[s.span_id]
        if is_read and target is not None:
            reads_by_target.setdefault(target, []).append(s)

    all_accurate = True
    aggregated_events: list[RedundantReadEvent] = []

    for target, read_spans in reads_by_target.items():
        if len(read_spans) < 2:
            continue
        # For each read pair (origin, candidate) — origin is the first
        # in the target group; every subsequent read after the last
        # eligible origin is a candidate.
        origin = read_spans[0]
        origin_agent = _nearest_agent_ancestor_id(origin.parent_span_id, spans_by_id)

        for cand in read_spans[1:]:
            cand_agent = _nearest_agent_ancestor_id(cand.parent_span_id, spans_by_id)
            if cand_agent != origin_agent:
                continue

            # Interval gate — no write-same-target, no shell tool between.
            interval_start = origin.end_time
            interval_end = cand.start_time
            interval_clean = True
            for other in tool_spans:
                if other.span_id in (origin.span_id, cand.span_id):
                    continue
                if not (interval_start < other.start_time < interval_end):
                    continue
                t2, _, is_write, is_shell = span_meta[other.span_id]
                if is_shell:
                    interval_clean = False
                    break
                if is_write and t2 == target:
                    interval_clean = False
                    break
            if not interval_clean:
                continue

            # Redundant read event.
            confirmed = (
                _sha256_hex(origin.output_text) == _sha256_hex(cand.output_text)
            )

            # Waste tokens from candidate output — this is what the next
            # LLM call will re-consume.
            model = cand.model  # usually None on tool spans; use downstream call's model
            waste_tokens = _tiktoken_len(cand.output_text, model)

            rate, rate_accurate = _resolve_rate_for_read(trace, cand.end_time)
            waste_cost = waste_tokens * rate
            if not rate_accurate:
                all_accurate = False

            aggregated_events.append(RedundantReadEvent(
                read_span_id=cand.span_id,
                origin_read_span_id=origin.span_id,
                tool_name=cand.agent_or_node_id,
                target=target,
                waste_tokens=waste_tokens,
                waste_cost=waste_cost,
                confirmed=confirmed,
            ))

    # Order events by cand time indirectly (by iterating tool_spans order in a stable way).
    # For determinism prefer sorting by (read_span_id) — matches Trace's ordering.
    aggregated_events.sort(key=lambda e: e.read_span_id)

    result.events = aggregated_events
    result.total_waste_tokens = sum(e.waste_tokens for e in aggregated_events)
    result.total_waste_cost = sum(e.waste_cost for e in aggregated_events)
    result.cost_accuracy_flag = "accurate" if all_accurate else "estimated"
    return result
