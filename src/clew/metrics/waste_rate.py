# Spec: docs/WASTE_RATE_METRIC_PREREG.md (pinned Rule 8 prereg).
"""Waste-rate metric — session-level summary across 4 deterministic detectors.

Aggregates results from repeat/cascade, context_resend, redundant_read, and
duplicate_creation_check (id-bridge scan) into three metrics per detector +
union: WR_char (UTF-8 byte ratio), WR_cost (cost ratio), and support for
SDR@10 (session detection threshold at 10% WR_char).

Frozen positions per prereg §1-5:
- Detector set: 4 deterministic (LLM-judge, pingpong excluded, §3).
- Tie-break order for union WR_cost: [repeat, context_resend, redundant_read,
  duplicate_creation] (§3, §4.2).
- Byte accounting: tool-span bytes and chunk bytes kept in separate buckets;
  no cross-category dedup (§4.2 caveat).
- Threshold for SDR: WR_char >= 0.10 (§5).

No new detector code. No pricing table changes. Consumers of detector outputs
only.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from clew.detect.cascade import cascade
from clew.detect.context_resend import _chunk_boundary, find_context_resend
from clew.detect.redundant_read import find_redundant_reads
from clew.model import Trace

# NOTE: `clew.report._enrich` is imported LAZILY inside
# `_duplicate_creation_metric` below. Eager import creates a cycle
# through `clew.report.__init__` → `clew.report.json_report` →
# `clew.metrics.waste_rate` after §6.1 report-integration wires
# `waste_rate` back into the JSON renderer.

if TYPE_CHECKING:
    from clew.config.user_tools import ResolvedTools
    from clew.detect.semantic import Embedder


DETECTOR_ORDER: tuple[str, ...] = (
    "repeat",
    "context_resend",
    "redundant_read",
    "duplicate_creation",
)

SDR_THRESHOLD: float = 0.10  # Prereg §5 frozen


@dataclass
class PerDetectorMetric:
    detector: str
    waste_bytes: int
    waste_cost: float
    wr_char: float | None
    wr_cost: float | None
    flagged_span_ids: frozenset[str] = field(default_factory=frozenset)
    # Chunk-level flags (context_resend only). Tuple of (llm_span_id, chunk_hash).
    flagged_chunks: frozenset[tuple[str, str]] = field(default_factory=frozenset)


@dataclass
class WasteRateMetric:
    trace_id: str
    total_input_bytes: int
    total_input_cost: float
    per_detector: dict[str, PerDetectorMetric]
    union_waste_bytes: int
    union_waste_cost: float
    union_wr_char: float | None
    union_wr_cost: float | None
    # None when the trace was included; "no_llm_calls" when metrics are
    # None because trace has no LLM span input. Consumers of the aggregate
    # exclude these traces from WR_char denominators.
    excluded_reason: str | None = None


# ── helpers ────────────────────────────────────────────────────────────────

def _bytes_utf8(text: str) -> int:
    return len(text.encode("utf-8"))


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _compute_total_input(trace: Trace) -> tuple[int, float]:
    """Total input bytes and input cost across all llm_calls.

    Bytes: sum of UTF-8 byte length of each call's `input_text`.
    Cost: sum of `input_tokens * input_cost_rate` (or `cost_rate_legacy`
    fallback per CONTEXT_RESEND_DETECTOR_PREREG §4). Missing token count
    or rate contributes 0.0 for that call.
    """
    total_bytes = 0
    total_cost = 0.0
    llm_calls = list(trace.metadata.get("llm_calls") or [])
    for call in llm_calls:
        input_text = call.get("input_text") or ""
        total_bytes += _bytes_utf8(input_text)
        tokens = call.get("input_tokens") or 0
        rate = call.get("input_cost_rate")
        if rate is None:
            rate = call.get("cost_rate_legacy")
        if rate is not None and tokens:
            total_cost += tokens * rate
    return total_bytes, total_cost


def _ratio(numerator: float, denominator: float) -> float | None:
    """Safe ratio: None if denominator is zero (prereg §1.1, §1.2)."""
    if denominator == 0:
        return None
    return numerator / denominator


# ── per-detector metrics ───────────────────────────────────────────────────

def _repeat_metric(
    trace: Trace,
    total_bytes: int,
    total_cost: float,
    *,
    embedder: "Embedder",
    n: int,
    phi: float,
) -> PerDetectorMetric:
    result = cascade(trace, embedder, n, phi)
    flagged = frozenset(result.waste_span_ids)
    spans_by_id = {s.span_id: s for s in trace.spans}
    waste_bytes = sum(
        _bytes_utf8(spans_by_id[sid].output_text)
        for sid in flagged
        if sid in spans_by_id
    )
    waste_cost = float(result.waste_cost)
    return PerDetectorMetric(
        detector="repeat",
        waste_bytes=waste_bytes,
        waste_cost=waste_cost,
        wr_char=_ratio(waste_bytes, total_bytes),
        wr_cost=_ratio(waste_cost, total_cost),
        flagged_span_ids=flagged,
    )


def _context_resend_metric(
    trace: Trace, total_bytes: int, total_cost: float,
) -> PerDetectorMetric:
    result = find_context_resend(trace)
    # Group flagged chunks by their carrying LLM span.
    resent_by_span: dict[str, set[str]] = {}
    for ev in result.resent_events:
        resent_by_span.setdefault(ev.llm_span_id, set()).add(ev.chunk_hash)
    flagged_chunks: set[tuple[str, str]] = set()
    waste_bytes = 0
    # Recompute chunk bytes: for each llm_call that carries flagged chunks,
    # re-split via the same boundary rule and match by hash. Byte-uniqueness
    # is guaranteed by (llm_span_id, chunk_hash) tuple identity.
    llm_calls = list(trace.metadata.get("llm_calls") or [])
    for call in llm_calls:
        span_id = call.get("span_id")
        hashes = resent_by_span.get(span_id)
        if not hashes:
            continue
        input_text = call.get("input_text") or ""
        counted: set[str] = set()
        for chunk_text, _role in _chunk_boundary(input_text):
            h = _sha256_hex(chunk_text)
            if h in hashes and h not in counted:
                waste_bytes += _bytes_utf8(chunk_text)
                counted.add(h)
                flagged_chunks.add((span_id, h))
    waste_cost = float(result.resent_cost)
    return PerDetectorMetric(
        detector="context_resend",
        waste_bytes=waste_bytes,
        waste_cost=waste_cost,
        wr_char=_ratio(waste_bytes, total_bytes),
        wr_cost=_ratio(waste_cost, total_cost),
        flagged_chunks=frozenset(flagged_chunks),
    )


def _redundant_read_metric(
    trace: Trace,
    total_bytes: int,
    total_cost: float,
    *,
    tools: "ResolvedTools | None" = None,
) -> PerDetectorMetric:
    result = find_redundant_reads(trace, tools=tools)
    flagged = frozenset(ev.read_span_id for ev in result.events)
    spans_by_id = {s.span_id: s for s in trace.spans}
    waste_bytes = sum(
        _bytes_utf8(spans_by_id[sid].output_text)
        for sid in flagged
        if sid in spans_by_id
    )
    waste_cost = float(result.total_waste_cost)
    return PerDetectorMetric(
        detector="redundant_read",
        waste_bytes=waste_bytes,
        waste_cost=waste_cost,
        wr_char=_ratio(waste_bytes, total_bytes),
        wr_cost=_ratio(waste_cost, total_cost),
        flagged_span_ids=flagged,
    )


def _duplicate_creation_metric(
    trace: Trace,
    total_bytes: int,
    total_cost: float,
    *,
    tools: "ResolvedTools | None" = None,
) -> PerDetectorMetric:
    # Lazy import to break the circular chain (see module-level note).
    from clew.report._enrich import scan_id_bridge_candidates
    cands = scan_id_bridge_candidates(trace, tools=tools)
    # Prereg §3: only "differ" verdicts feed the waste aggregation.
    flagged = frozenset(
        c.candidate_span_id for c in cands if c.verdict == "differ"
    )
    spans_by_id = {s.span_id: s for s in trace.spans}
    waste_bytes = sum(
        _bytes_utf8(spans_by_id[sid].output_text)
        for sid in flagged
        if sid in spans_by_id
    )
    waste_cost = 0.0
    for sid in flagged:
        s = spans_by_id.get(sid)
        if s is None:
            continue
        tokens = s.token_count or 0
        rate = s.cost_rate or 0.0
        waste_cost += tokens * rate
    return PerDetectorMetric(
        detector="duplicate_creation",
        waste_bytes=waste_bytes,
        waste_cost=waste_cost,
        wr_char=_ratio(waste_bytes, total_bytes),
        wr_cost=_ratio(waste_cost, total_cost),
        flagged_span_ids=flagged,
    )


# ── main entry point ───────────────────────────────────────────────────────

def compute_waste_rate(
    trace: Trace,
    *,
    embedder: "Embedder",
    n: int,
    phi: float,
    tools: "ResolvedTools | None" = None,
) -> WasteRateMetric:
    """Compute per-detector + union waste-rate metrics for a single trace.

    Deterministic on the same inputs. Prereg §1-4.

    Args:
        trace: post-preprocess Trace with `metadata["llm_calls"]` populated
            (per CONTEXT_RESEND_DETECTOR_PREREG §3).
        embedder: cascade needs a semantic embedder for non-tool paths.
            Callers that don't have torch installed can pass a stub that
            never triggers cosine (tool-only cascade) — see cascade.py.
        n: cascade `N` (frozen at 2).
        phi: cascade `phi` (frozen at 0.514345).
        tools: optional user-tool resolution (`clew.yaml`).

    Returns:
        `WasteRateMetric` with per-detector breakdown and union metrics.
    """
    total_bytes, total_cost = _compute_total_input(trace)
    excluded = "no_llm_calls" if total_bytes == 0 else None

    per_detector: dict[str, PerDetectorMetric] = {
        "repeat": _repeat_metric(
            trace, total_bytes, total_cost, embedder=embedder, n=n, phi=phi,
        ),
        "context_resend": _context_resend_metric(trace, total_bytes, total_cost),
        "redundant_read": _redundant_read_metric(
            trace, total_bytes, total_cost, tools=tools,
        ),
        "duplicate_creation": _duplicate_creation_metric(
            trace, total_bytes, total_cost, tools=tools,
        ),
    }

    # Union bytes: prereg §4.2. Tool-span bytes are byte-unique across the
    # three span-level detectors (repeat, redundant_read, duplicate_creation)
    # — same span_id counted once. Chunk bytes (context_resend) live in a
    # separate bucket and are added at the end. The §4.2 caveat is that a
    # tool result whose bytes are re-hashed as a message chunk will be
    # counted twice; documented, deferred to v2.
    union_span_ids: set[str] = set()
    for det in ("repeat", "redundant_read", "duplicate_creation"):
        union_span_ids |= per_detector[det].flagged_span_ids
    spans_by_id = {s.span_id: s for s in trace.spans}
    span_bytes = sum(
        _bytes_utf8(spans_by_id[sid].output_text)
        for sid in union_span_ids
        if sid in spans_by_id
    )
    chunk_bytes = per_detector["context_resend"].waste_bytes
    union_waste_bytes = span_bytes + chunk_bytes

    # Union cost: tie-break by frozen DETECTOR_ORDER for spans. Chunk cost
    # comes directly from context_resend (no overlap with span cost by
    # construction — chunks aggregate input-side, spans aggregate output-side).
    span_first_flagger: dict[str, str] = {}
    for det in DETECTOR_ORDER:
        if det == "context_resend":
            continue
        for sid in per_detector[det].flagged_span_ids:
            span_first_flagger.setdefault(sid, det)
    span_cost = 0.0
    for sid in span_first_flagger:
        s = spans_by_id.get(sid)
        if s is None:
            continue
        tokens = s.token_count or 0
        rate = s.cost_rate or 0.0
        span_cost += tokens * rate
    union_waste_cost = span_cost + per_detector["context_resend"].waste_cost

    return WasteRateMetric(
        trace_id=trace.trace_id,
        total_input_bytes=total_bytes,
        total_input_cost=total_cost,
        per_detector=per_detector,
        union_waste_bytes=union_waste_bytes,
        union_waste_cost=union_waste_cost,
        union_wr_char=_ratio(union_waste_bytes, total_bytes),
        union_wr_cost=_ratio(union_waste_cost, total_cost),
        excluded_reason=excluded,
    )
