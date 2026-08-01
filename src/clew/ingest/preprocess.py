"""src/clew/ingest/preprocess.py

Ingest preprocessing pipeline - post-processing stage of otel_spans_to_trace().

Three transforms:
  1. extract_output_text  - remove JSON state-dict scaffolding
  2. mark_worker_span_ids - compute set of span_ids that have llm/tool descendants (router discrimination)
  3. collapse_llm_spans   - remove llm sub-spans + token rollup + ReAct re-parent
  4. filter_router_spans  - remove router chain spans
"""

from __future__ import annotations

import json
from typing import Any

from clew.model import Span, Trace


# -- 1. JSON extraction --------------------------------------------------------

def extract_output_text(raw: str) -> str:
    """Recursively traverse a JSON dict/list and return the longest string leaf.

    Rules:
    - json.loads success -> recursively explore dict/list -> collect str leaves
      -> return the longest non-empty string (first in traversal order on ties)
    - json.loads failure or no str leaves -> return raw text

    Independent of key order, so does not mis-select short fields like status.
    """
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw

    leaves: list[str] = []
    _collect_str_leaves(obj, leaves)
    non_empty = [s for s in leaves if s.strip()]
    if not non_empty:
        return raw
    return max(non_empty, key=len)


def _collect_str_leaves(obj: Any, out: list[str]) -> None:
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_str_leaves(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_str_leaves(item, out)


# -- 2. Compute worker span set ------------------------------------------------

def mark_worker_span_ids(spans: list[Span]) -> set[str]:
    """Return the set of span_ids that have (transitive) llm/tool descendants.

    Uses descendants rather than direct children - prevents mistakenly removing a
    chain node whose llm/tool call is at grandchild depth as a router.
    """
    children_map: dict[str, list[str]] = {s.span_id: [] for s in spans}
    kinds: dict[str, str] = {s.span_id: s.span_kind for s in spans}
    for s in spans:
        if s.parent_span_id is not None and s.parent_span_id in children_map:
            children_map[s.parent_span_id].append(s.span_id)

    result: set[str] = set()
    for s in spans:
        if _has_llm_or_tool_descendant(s.span_id, children_map, kinds):
            result.add(s.span_id)
    return result


def _has_llm_or_tool_descendant(
    span_id: str,
    children_map: dict[str, list[str]],
    kinds: dict[str, str],
) -> bool:
    """True if any descendant of span_id has kind llm/tool (BFS)."""
    queue = list(children_map.get(span_id, []))
    while queue:
        child_id = queue.pop()
        if kinds.get(child_id) in ("llm", "tool"):
            return True
        queue.extend(children_map.get(child_id, []))
    return False


# -- 3. LLM span collapse + ReAct re-parent -----------------------------------

def collapse_llm_spans(
    spans: list[Span],
    worker_ids: set[str],
) -> tuple[list[Span], int]:
    """Remove llm sub-spans + roll up token_count/cost_rate into the parent chain.

    ReAct orphan handling:
        Children (tool, etc.) of a removed llm span are re-parented to that llm's parent_span_id.
        This lifts tool spans directly under the worker chain with no dangling.

    token_count rollup:
        Accumulate the removed llm span's token_count into the parent chain.
        If parent already has token_count, sum; otherwise set.
    """
    llm_ids = {s.span_id for s in spans if s.span_kind == "llm"}

    # Collect (token_count, parent_span_id) per llm span
    llm_info: dict[str, tuple[int | None, str | None]] = {
        s.span_id: (s.token_count, s.parent_span_id)
        for s in spans if s.span_kind == "llm"
    }

    # Accumulate token_count per parent
    parent_token_delta: dict[str, int] = {}
    for llm_id, (tc, parent_id) in llm_info.items():
        if parent_id is not None and tc is not None:
            parent_token_delta[parent_id] = parent_token_delta.get(parent_id, 0) + tc

    kept: list[Span] = []
    for s in spans:
        if s.span_kind == "llm":
            continue  # remove

        # ReAct re-parent: if parent is an llm span, lift to the llm's parent
        new_parent = s.parent_span_id
        if new_parent in llm_ids:
            new_parent = llm_info[new_parent][1]  # llm's parent_span_id

        # token_count rollup
        new_token_count = s.token_count
        if s.span_id in parent_token_delta:
            base = s.token_count or 0
            new_token_count = base + parent_token_delta[s.span_id]

        if new_parent != s.parent_span_id or new_token_count != s.token_count:
            s = s.model_copy(update={
                "parent_span_id": new_parent,
                "token_count": new_token_count,
            })

        kept.append(s)

    return kept, len(llm_ids)


# -- 4. Router span filter ----------------------------------------------------

def filter_router_spans(spans: list[Span], worker_ids: set[str]) -> list[Span]:
    """Remove non-root chain/agent spans not in worker_ids.

    Condition: span_kind in (chain, agent) AND parent_span_id is not None AND
          span_id not in worker_ids
    Root span (parent_span_id=None) is always preserved.
    """
    return [
        s for s in spans
        if not (
            s.span_kind in ("chain", "agent")
            and s.parent_span_id is not None
            and s.span_id not in worker_ids
        )
    ]


# -- Pipeline entry point ------------------------------------------------------

def preprocess_trace(trace: Trace) -> Trace:
    """Ingest preprocessing 4-stage pipeline.

    (1) extract_output_text  - remove JSON scaffolding from each span's output_text
    (2) mark_worker_span_ids - compute worker set from original tree before collapse
    (3) collapse_llm_spans   - remove llm + token rollup + ReAct re-parent
    (4) filter_router_spans  - remove router chain spans

    Order guarantee: (2) is before (3) (llm spans disappear after collapse); (3) is before (4).
    """
    # (1) JSON extraction - update Span.output_text
    # For tool spans, preserve the original payload in raw_output_text so
    # downstream consumers (id_bridge) can traverse the original structure.
    # Non-tool spans do not populate raw_output_text (fallback reads output_text).
    spans: list[Span] = []
    for s in trace.spans:
        extracted = extract_output_text(s.output_text)
        if extracted != s.output_text:
            update: dict[str, Any] = {"output_text": extracted}
            if s.span_kind == "tool":
                update["raw_output_text"] = s.output_text
            s = s.model_copy(update=update)
        spans.append(s)

    # (2) Compute worker set (based on topology before collapse)
    worker_ids = mark_worker_span_ids(spans)

    # (3) collapse
    spans, removed_count = collapse_llm_spans(spans, worker_ids)

    # (4) Router filter
    spans = filter_router_spans(spans, worker_ids)

    new_meta = {
        **trace.metadata,
        "collapsed_llm_spans": removed_count,
        "filtered_router_spans": len(trace.spans) - removed_count - len(spans),
    }
    return Trace(trace_id=trace.trace_id, spans=spans, metadata=new_meta)
