"""Structural candidate detection (SPEC §8 2.1, §22.8).

In a node sequence ordered by start_time:
- Repeat nodes: same agent_or_node_id appears N+ times -> (first occurrence, re-occurrence) pairs within each subgroup.
  Nodes with span_kind=="tool" are subgrouped by `(agent_or_node_id, _normalize_input(input_text))`
  (§22.8.1: origin pinning removed - pair every re-occurrence with the same signature).
  Other kinds are grouped by agent_or_node_id alone (input gate not applied).
- Pingpong: A->B->A->B -> 2nd-round A and B pairs. Only when all 4 spans in the 4-window have span_kind=="llm"
  (§22.8.2: tool call alternation is normal work, not pingpong).
- requery: a special form of repeated tool node -> subgrouping works as-is.

No label references. Neither the evaluation set nor dev set directory is read.
"""

from __future__ import annotations

from clew.model import Span, Trace


def _normalize_input(s: str) -> str:
    """SPEC §8 2.1 normalized-equal: normalize only whitespace and case. Anything more lacks data justification."""
    return s.strip().casefold()


def _spans_by_start_time(trace: Trace) -> list[Span]:
    return sorted(trace.spans, key=lambda s: s.start_time)


def _nearest_agent_ancestor_id(
    start_id: str | None, spans_by_id: dict[str, Span]
) -> str | None:
    """Walk up the parent_span_id chain and return the span_id of the first ancestor with span_kind=='agent'.

    None if none exists (single-agent/flat trace). None==None -> gate not applied (preserves existing behavior).
    SPEC §16: if the two spans' return values differ, exclude from repeat candidates.
    """
    current_id = start_id
    while current_id is not None:
        span = spans_by_id.get(current_id)
        if span is None:
            return None
        if span.span_kind == "agent":
            return span.span_id
        current_id = span.parent_span_id
    return None


def find_repeat_candidates(trace: Trace, n: int) -> list[tuple[Span, Span]]:
    """When the same agent_or_node_id appears n+ times, return (first occurrence, re-occurrence) pairs within each subgroup.

    tool kind: subgrouped by `(agent_or_node_id, _normalize_input(input_text))`
        (§22.8.1: pair every re-occurrence with the same signature. O(n) via dict).
    Other kinds: grouped by `agent_or_node_id` alone (input gate not applied).
    SPEC §16 parent-AGENT gate: if the two spans' nearest ancestor AGENT differs, exclude from candidates.
    """
    if n < 2:
        raise ValueError("n must be >= 2 (a single occurrence is not a repeat)")
    ordered = _spans_by_start_time(trace)
    spans_by_id = {s.span_id: s for s in trace.spans}
    groups: dict[tuple[str, str | None], list[Span]] = {}
    for s in ordered:
        if s.span_kind == "tool":
            key = (s.agent_or_node_id, _normalize_input(s.input_text))
        else:
            key = (s.agent_or_node_id, None)
        groups.setdefault(key, []).append(s)
    pairs: list[tuple[Span, Span]] = []
    for occurrences in groups.values():
        if len(occurrences) < n:
            continue
        origin = occurrences[0]
        origin_agent = _nearest_agent_ancestor_id(origin.parent_span_id, spans_by_id)
        for cand in occurrences[1:]:
            if _nearest_agent_ancestor_id(cand.parent_span_id, spans_by_id) != origin_agent:
                continue
            pairs.append((origin, cand))
    return pairs


def find_pingpong_candidates(trace: Trace) -> list[tuple[Span, Span]]:
    """When A->B->A->B alternation is found, return 2nd-round (A, A_prev) + (B, B_prev) pairs.

    §22.8.2: candidate only when all 4 spans in the 4-window have `span_kind == "llm"`.
    Tool call alternation is normal work, not pingpong.
    """
    ordered = _spans_by_start_time(trace)
    pairs: list[tuple[Span, Span]] = []
    for i in range(len(ordered) - 3):
        a1, b1, a2, b2 = ordered[i], ordered[i + 1], ordered[i + 2], ordered[i + 3]
        if not (
            a1.span_kind == "llm"
            and b1.span_kind == "llm"
            and a2.span_kind == "llm"
            and b2.span_kind == "llm"
        ):
            continue
        if (
            a1.agent_or_node_id == a2.agent_or_node_id
            and b1.agent_or_node_id == b2.agent_or_node_id
            and a1.agent_or_node_id != b1.agent_or_node_id
        ):
            pairs.append((a1, a2))
            pairs.append((b1, b2))
    return pairs


def find_candidates(trace: Trace, n: int) -> list[tuple[Span, Span]]:
    """Combine repeat + pingpong candidates and return a (origin, candidate) pair list. Deduplicated."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[Span, Span]] = []
    for origin, cand in find_repeat_candidates(trace, n) + find_pingpong_candidates(trace):
        key = (origin.span_id, cand.span_id)
        if key in seen:
            continue
        seen.add(key)
        out.append((origin, cand))
    return out
