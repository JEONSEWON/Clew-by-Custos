"""src/clew/ingest/exgentic.py — Exgentic Agent LLM Traces v2 (parquet) → Trace.

Contract: pre-registered in
WASTE_RATE_EXGENTIC_ADAPTER_AMENDMENT_PREREG §1 (PR #103, see repo
docs directory).

Source: `data/exgentic/*.parquet` shards from HuggingFace
`Exgentic/agent-llm-traces-v2` (10,057 sessions across 9 shards). Each
row is one session with 20 top-level metadata columns plus a `spans`
list of chat-kind spans following OTel GenAI semantic conventions.

Main decisions (§1):
- §1.2 Attribute namespace bridge OTel GenAI (`gen_ai.*`) →
  OpenInference (`llm.token_count.*` / `input.value` / `output.value`
  / `llm.model_name`). No cache-tier fields (Exgentic does not
  publish them → `cost_accuracy_flag == "estimated"` per Corpus B
  parity).
- §1.3 Synthetic CHAIN root per session. Every chat span reparented
  to it, because the dataset filters out `invoke_agent` /
  `execute_tool` parents (dataset README §Filtering step 3).
- §1.4 Multi-`trace_id` handled by majority-mode primary + collapse.
  Secondary count recorded in `trace.metadata["exgentic"]["trace_id_secondary_count"]`.
- §1.5 Chat-only scope. `gen_ai.operation.name != "chat"` spans are
  dropped with a per-session count in metadata; deterministic
  detectors `repeat` / `redundant_read` / `duplicate_creation`
  therefore return zero on Corpus C by construction (the tool spans
  they scan are structurally absent).
- §1.6 Cost pricing via caller-provided `input_cost_table` /
  `output_cost_table` mirroring the Toolathlon adapter's convention.
  No cache-tier keys populated.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from clew.model import Span, Trace


# ── ISO datetime handling ──────────────────────────────────────────────


def _iso_to_dt(v: Any) -> datetime:
    """ISO datetime str (or datetime already) → datetime with tzinfo.

    Exgentic timestamps arrive as timezone-aware ISO strings like
    `2026-04-12T07:27:42.923007+00:00`. pyarrow.parquet may pre-parse
    them into `datetime` objects when the parquet column type is a
    timestamp; accept both.
    """
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    raise TypeError(f"Exgentic: 시간 필드 타입 unsupported: {type(v).__name__}")


# ── §1.4 primary trace_id resolution ───────────────────────────────────


def _pick_primary_trace_id(
    span_records: list[dict[str, Any]],
) -> tuple[str, int]:
    """§1.4: primary = majority mode; tiebreak = first-seen order.

    Returns `(primary_trace_id, secondary_count)`. `secondary_count`
    is the number of spans whose `trace_id` differs from the primary
    (0 when all spans agree).
    """
    if not span_records:
        raise ValueError("Exgentic: 빈 spans 리스트 · primary trace_id 결정 불가")

    first_seen: dict[str, int] = {}
    counts: Counter[str] = Counter()
    for i, sp in enumerate(span_records):
        tid = sp["trace_id"]
        counts[tid] += 1
        if tid not in first_seen:
            first_seen[tid] = i

    # sort by (-count, first_seen_index) → majority wins, first-seen tiebreak
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], first_seen[kv[0]]))
    primary = ranked[0][0]
    secondary_count = sum(c for tid, c in counts.items() if tid != primary)
    return primary, secondary_count


# ── §1.3 synthetic CHAIN root span_id ──────────────────────────────────


def _synth_root_span_id(session_id: str) -> str:
    """Deterministic 16-hex span_id derived from session_id (§1.3)."""
    h = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return h[:16]


# ── §1.2 attribute namespace bridge ────────────────────────────────────


def _bridge_gen_ai_span(
    sp: dict[str, Any],
    *,
    trace_id: str,
    parent_span_id: str,
    input_cost_table: dict[str, float] | None,
    output_cost_table: dict[str, float] | None,
) -> tuple[Span, dict[str, Any]]:
    """Convert one Exgentic OTel GenAI span dict into a Boxdawn `Span`
    plus the matching `llm_calls` entry (OpenInference-attr shape
    the detectors already consume).

    Returns `(span, llm_call_dict)`.
    """
    attrs = sp.get("attributes") or {}

    # §1.2 attribute translation
    input_value: str = attrs.get("gen_ai.input.messages") or ""
    output_value: str = attrs.get("gen_ai.output.messages") or ""

    # Model: request first, response fallback (dataset README canonicalizes both)
    model: str | None = (
        attrs.get("gen_ai.request.model")
        or attrs.get("gen_ai.response.model")
        or None
    )

    input_tokens = attrs.get("gen_ai.usage.input_tokens")
    output_tokens = attrs.get("gen_ai.usage.output_tokens")
    input_tokens_int: int | None = int(input_tokens) if isinstance(input_tokens, int) else None
    output_tokens_int: int | None = int(output_tokens) if isinstance(output_tokens, int) else None

    total_tokens: int | None = None
    if input_tokens_int is not None and output_tokens_int is not None:
        total_tokens = input_tokens_int + output_tokens_int

    # §1.6 pricing (uncached tier only)
    input_cost_rate: float | None = None
    output_cost_rate: float | None = None
    if model and input_cost_table and model in input_cost_table:
        input_cost_rate = float(input_cost_table[model])
    if model and output_cost_table and model in output_cost_table:
        output_cost_rate = float(output_cost_table[model])

    span = Span(
        trace_id=trace_id,
        span_id=sp["span_id"],
        parent_span_id=parent_span_id,
        agent_or_node_id=sp.get("name") or "chat",
        span_kind="llm",
        start_time=_iso_to_dt(sp["start_time"]),
        end_time=_iso_to_dt(sp["end_time"]),
        input_text=input_value,
        output_text=output_value,
        token_count=total_tokens,
        model=model,
        cost_rate=input_cost_rate,
    )

    # OpenInference-shape llm_call entry (detector-facing)
    # Cache tier fields intentionally set to None per §1.2:
    #   Exgentic does not record `input_tokens_cache_read` /
    #   `input_tokens_cache_write`. The detector propagates None →
    #   `cost_accuracy_flag == "estimated"` (Corpus B parity).
    llm_call = {
        "span_id": sp["span_id"],
        "start_time": span.start_time.isoformat(),
        "model": model,
        "input_text": input_value,
        "input_tokens": input_tokens_int,
        "output_tokens": output_tokens_int,
        "input_tokens_uncached": input_tokens_int,
        "input_tokens_cache_read": None,
        "input_tokens_cache_write": None,
        "input_cost_rate": input_cost_rate,
        "output_cost_rate": output_cost_rate,
        "cost_rate_legacy": None,  # tier-split path preferred
    }
    return span, llm_call


# ── §1.1 public API ────────────────────────────────────────────────────


def ingest_exgentic_row(
    row: dict[str, Any],
    *,
    cost_table: dict[str, float] | None = None,  # legacy, unused (§3)
    input_cost_table: dict[str, float] | None = None,
    output_cost_table: dict[str, float] | None = None,
) -> Trace:
    """§1.1: Exgentic parquet row (one session) → Boxdawn canonical Trace.

    Args:
      row: dict from `pyarrow.parquet.read_table(...).to_pylist()[i]`.
      input_cost_table / output_cost_table: `{model → $/token}` maps,
        same convention as the Toolathlon adapter.
      cost_table: legacy single-rate table; accepted but unused since
        this adapter needs per-side rates for the uncached path.

    Raises:
      ValueError: session has no `spans` list, or all spans got
        filtered out by the chat-only rule (§1.5), or the
        primary-trace_id resolution fails (§1.4).
    """
    session_id: str = row.get("session_id") or "unknown"
    src_spans: list[dict[str, Any]] = row.get("spans") or []
    if not src_spans:
        raise ValueError(
            f"Exgentic session {session_id!r}: `spans` 필드 비어 있음"
        )

    # §1.5 chat-only filter — drop any non-chat span (dataset guarantees
    # all are chat, but we assert defensively per prereg §5.2(d))
    dropped_non_chat = 0
    chat_spans: list[dict[str, Any]] = []
    for sp in src_spans:
        attrs = sp.get("attributes") or {}
        op = attrs.get("gen_ai.operation.name")
        if op is None or op == "chat":
            chat_spans.append(sp)
        else:
            dropped_non_chat += 1
    if not chat_spans:
        raise ValueError(
            f"Exgentic session {session_id!r}: 모든 span 이 non-chat 으로 filter: "
            f"src {len(src_spans)}, dropped {dropped_non_chat}"
        )

    # §1.4 primary trace_id
    primary_trace_id, secondary_count = _pick_primary_trace_id(chat_spans)

    # §1.3 synthetic CHAIN root
    synth_root_span_id = _synth_root_span_id(session_id)

    # Bridge each chat span (§1.2) → Span + llm_call
    bridged: list[tuple[Span, dict[str, Any]]] = [
        _bridge_gen_ai_span(
            sp,
            trace_id=primary_trace_id,
            parent_span_id=synth_root_span_id,
            input_cost_table=input_cost_table,
            output_cost_table=output_cost_table,
        )
        for sp in chat_spans
    ]
    chat_spans_out: list[Span] = [s for s, _ in bridged]
    llm_calls: list[dict[str, Any]] = [lc for _, lc in bridged]

    root_start = min(s.start_time for s in chat_spans_out)
    root_end = max(s.end_time for s in chat_spans_out)
    root_span = Span(
        trace_id=primary_trace_id,
        span_id=synth_root_span_id,
        parent_span_id=None,
        agent_or_node_id=f"[exgentic-session-root] {session_id}",
        span_kind="chain",
        start_time=root_start,
        end_time=root_end,
        input_text="",
        output_text=f"[exgentic session: {session_id}]",
    )

    metadata: dict[str, Any] = {
        "source": "exgentic_parquet",
        "session_id": session_id,
        "benchmark": row.get("benchmark"),
        "benchmark_subset": row.get("benchmark_subset"),
        "harness": row.get("harness"),
        "run_id": row.get("run_id"),
        "models": row.get("models"),
        "success": row.get("success"),
        "status": row.get("status"),
        "steps": row.get("steps"),
        "action_count": row.get("action_count"),
        "score": row.get("score"),
        "execution_time": row.get("execution_time"),
        "exgentic_total_tokens": row.get("total_tokens"),
        "exgentic_max_tokens": row.get("max_tokens"),
        "exgentic": {
            "trace_id_secondary_count": secondary_count,
            "dropped_non_chat_spans": dropped_non_chat,
        },
        "llm_calls": llm_calls,
    }

    return Trace(
        trace_id=primary_trace_id,
        spans=[root_span] + chat_spans_out,
        metadata=metadata,
    )


def ingest_exgentic_parquet_iter(
    path: Path,
    *,
    input_cost_table: dict[str, float] | None = None,
    output_cost_table: dict[str, float] | None = None,
) -> Iterator[Trace]:
    """§1.1: iterate all rows of an Exgentic parquet shard, yielding
    one `Trace` per row. Rows that raise `ValueError` from
    `ingest_exgentic_row` are re-raised — the caller decides whether
    to catch and classify.
    """
    import pyarrow.parquet as pq

    table = pq.read_table(path)
    for i in range(table.num_rows):
        row = table.slice(i, 1).to_pylist()[0]
        yield ingest_exgentic_row(
            row,
            input_cost_table=input_cost_table,
            output_cost_table=output_cost_table,
        )
