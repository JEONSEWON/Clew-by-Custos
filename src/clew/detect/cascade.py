"""Cascade combination + waste cost (SPEC §8 2.3, §22.10.2, §22.11.2).

Waste determination:
- span_kind == "tool"   -> structural candidate AND (no compact boundary in window)
                          AND sha256(origin.output) == sha256(cand.output).
                          Does not invoke phi. Tool outputs have no paraphrase.
- span_kind != "tool"   -> structural candidate AND cos(origin, cand) >= phi (existing path).

compact window gate (§22.11.2):
- If Trace.metadata["compact_boundaries"] has a timestamp list,
  exclude from waste when a b exists such that origin.start_time < b < candidate.start_time.
- If this key is absent (non-CC loaders like OTel/OpenInference), the gate is a no-op.

Waste span = candidate side (origin is treated as normal since it is the first occurrence).
Cost = sum(token_count * cost_rate) over candidate spans.

No label arguments. Only evaluate.py performs the comparison.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime

from clew.detect.semantic import Embedder, cosine
from clew.detect.structural import find_candidates
from clew.model import Span, Trace


@dataclass
class CascadeResult:
    trace_id: str
    wasteful: bool
    waste_span_ids: list[str] = field(default_factory=list)
    waste_tokens: int = 0
    waste_cost: float = 0.0


def _sha256_bytes(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _has_compact_between(boundaries: list[datetime], o_start: datetime, c_start: datetime) -> bool:
    return any(o_start < b < c_start for b in boundaries)


def confirm_pair(
    origin: Span,
    candidate: Span,
    embedder: Embedder,
    phi: float,
    compact_boundaries: list[datetime] | None = None,
) -> bool:
    """Whether one structural candidate pair is a duplicate. The whole cascade
    verdict for a single pair, with no trace-wide work.

    Lives outside `cascade()` because the live path calls it one pair at a time
    (LIVE_FAILURE_ALERT_PREREG §2, §4). §4 requires that a pair the batch path
    calls a duplicate is the same pair live; sharing the function is what makes
    that structural rather than a claim to be maintained by hand.
    """
    boundaries = compact_boundaries or []
    if candidate.span_kind == "tool":
        # CASCADE_ABSENCE_SENTINEL_AMENDMENT_PREREG §4: absence is not
        # expression — the same principle the non-tool branch below already
        # applies. model.py forbids an empty tool output_text precisely so
        # this sha256 gate cannot match empty-vs-empty; a vendor placeholder
        # for "no output" is non-empty and walked straight through that
        # guard. Measured: 22 of 31 flags across 40 Claude Code sessions
        # were such placeholders; 0 of 347 on Corpus B.
        if candidate.output_is_absent or origin.output_is_absent:
            return False
        if _has_compact_between(boundaries, origin.start_time, candidate.start_time):
            return False
        return _sha256_bytes(origin.output_text) == _sha256_bytes(candidate.output_text)
    # ── non-tool branch ────────────────────────────────────────────
    # R2 relaxation (docs/ADAPTER_R2_RELAXATION_PREREG.md §2.1 · §2.5):
    # empty output_text is absence, not expression. cosine on absence is
    # a malformed question — cosine(embed(""), embed("")) = 1.0 measured
    # against phi=0.514345 would trigger a false waste flag. Skip both
    # empty-vs-empty and empty-vs-value (§2.1 widened principle: absence
    # on either side is not judgeable).
    if not (origin.output_text.strip() and candidate.output_text.strip()):
        return False
    return cosine(embedder.embed(origin.output_text), embedder.embed(candidate.output_text)) >= phi


def cascade(trace: Trace, embedder: Embedder, n: int, phi: float) -> CascadeResult:
    spans_by_id = {s.span_id: s for s in trace.spans}
    waste_span_ids: list[str] = []
    seen_candidates: set[str] = set()
    compact_boundaries: list[datetime] = list(
        trace.metadata.get("compact_boundaries", []) or []
    )

    for origin, candidate in find_candidates(trace, n):
        if candidate.span_id in seen_candidates:
            continue
        if confirm_pair(origin, candidate, embedder, phi, compact_boundaries):
            waste_span_ids.append(candidate.span_id)
            seen_candidates.add(candidate.span_id)

    waste_tokens = 0
    waste_cost = 0.0
    for sid in waste_span_ids:
        s = spans_by_id[sid]
        tc = s.token_count or 0
        cr = s.cost_rate or 0.0
        waste_tokens += tc
        waste_cost += tc * cr

    return CascadeResult(
        trace_id=trace.trace_id,
        wasteful=bool(waste_span_ids),
        waste_span_ids=waste_span_ids,
        waste_tokens=waste_tokens,
        waste_cost=waste_cost,
    )
