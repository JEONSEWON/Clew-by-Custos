# Spec: docs/CONTEXT_RESEND_DETECTOR_PREREG.md (pinned Rule 8 prereg).
"""Context Resend Detector — deterministic detection of resent LLM input chunks.

Given a trace with `metadata["llm_calls"]` populated (per prereg §3), the
detector flags message chunks that appear in the input of two or more LLM
calls within the same trace. Chunk boundary follows the JSON-first rule
(§2); system-role chunks are exempt (§1.2). Cost is estimated by per-call
apportionment of the provider-reported input tokens to chunks proportional
to their tokenized length (§4).

Deterministic guarantees (§8): sha256 hashing, JSON-parse chunk boundary,
tiktoken with pinned version for share calculation. No LLM-as-judge, no
embedding.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

from clew.model import Trace


CostAccuracy = Literal["accurate", "estimated"]


@dataclass
class ResentEvent:
    llm_span_id: str
    origin_llm_span_id: str
    chunk_hash: str
    chunk_role: str | None
    resent_input_tokens: int
    resent_cost: float


@dataclass
class ContextResendResult:
    trace_id: str
    resent_events: list[ResentEvent] = field(default_factory=list)
    resent_input_tokens: int = 0
    resent_cost: float = 0.0
    total_llm_input_tokens: int = 0
    total_llm_input_cost: float = 0.0
    cost_accuracy_flag: CostAccuracy = "accurate"


# ── Chunk boundary (prereg §2) ───────────────────────────────────────────────

def _chunk_boundary(input_text: str) -> list[tuple[str, str | None]]:
    """Return list of (chunk_text_for_hashing, role_or_None) per prereg §2.

    Priority (first match):
      1. JSON list -> each element is one chunk.
      2. JSON dict with `messages` key whose value is a list -> each element.
      3. Otherwise (parse failure or unrecognized shape) -> entire input as
         one chunk.

    Chunk text for hashing is json.dumps(elem, sort_keys=True,
    ensure_ascii=False) for parsed elements, or the raw string in the
    fallback case. Role extraction: dict element with "role" key -> that
    value; else None.
    """
    try:
        parsed = json.loads(input_text)
    except (json.JSONDecodeError, TypeError):
        return [(input_text, None)]

    elements: list[Any] | None = None
    if isinstance(parsed, list):
        elements = parsed
    elif isinstance(parsed, dict):
        messages = parsed.get("messages")
        if isinstance(messages, list):
            elements = messages

    if elements is None:
        # Recognized JSON but not the expected shape — treat whole string as
        # one chunk (fallback). Rehash the original input_text verbatim so
        # cross-call byte-exactness holds without re-serialization drift.
        return [(input_text, None)]

    out: list[tuple[str, str | None]] = []
    for elem in elements:
        text = json.dumps(elem, sort_keys=True, ensure_ascii=False)
        role: str | None = None
        if isinstance(elem, dict):
            r = elem.get("role")
            if isinstance(r, str):
                role = r
        out.append((text, role))
    return out


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Token share (prereg §4) ──────────────────────────────────────────────────

def _chunk_token_len(text: str, model: str | None) -> int:
    """tiktoken length for share calculation only (prereg §4).

    Encoding pick (frozen for v1):
      - Any model containing 'gpt-4o' or 'o200k' -> o200k_base
      - Anthropic Claude family (name contains 'claude') -> cl100k_base
        (Anthropic tokenizer is not tiktoken-native; this is an
        approximation, acceptable because these values enter only into
        chunk share ratios, not absolute token counts)
      - Everything else (including gpt-4, gpt-3.5, unknown) -> cl100k_base
      - tiktoken import failure or encoding failure -> len(text) // 4 + 1

    A minimum of 1 token per non-empty chunk protects the share ratio
    from divide-by-zero when all chunks are extremely short.
    """
    try:
        import tiktoken
    except ImportError:
        return max(1, len(text) // 4) if text else 0

    if not text:
        return 0

    encoding_name = "cl100k_base"
    if model:
        low = model.lower()
        if "gpt-4o" in low or "o200k" in low:
            encoding_name = "o200k_base"

    try:
        enc = tiktoken.get_encoding(encoding_name)
        return max(1, len(enc.encode(text)))
    except Exception:
        return max(1, len(text) // 4)


# ── Detector entry point ────────────────────────────────────────────────────

def find_context_resend(trace: Trace, n: int = 2) -> ContextResendResult:
    """Detect and cost context resend events within a single trace (prereg §1).

    Args:
        trace: post-preprocess trace with `metadata["llm_calls"]` populated.
        n: minimum occurrences (>= 2) for a chunk to be flagged. Default 2.

    Returns:
        `ContextResendResult` with per-event breakdown, sums, denominators,
        and `cost_accuracy_flag` per §4.
    """
    if n < 2:
        raise ValueError("n must be >= 2")

    llm_calls: list[dict[str, Any]] = list(trace.metadata.get("llm_calls") or [])
    result = ContextResendResult(trace_id=trace.trace_id)

    if not llm_calls:
        return result

    # Decide cost accuracy: "accurate" if every call has input_cost_rate set.
    any_legacy = any(c.get("input_cost_rate") is None for c in llm_calls)
    result.cost_accuracy_flag = "estimated" if any_legacy else "accurate"

    # Pre-compute per-call chunk annotations and running denominators.
    #
    # per_call[i] = list of (chunk_text, role, chunk_token_len)
    # occurrence_count[chunk_hash] = total occurrences across whole trace
    per_call: list[list[tuple[str, str | None, int]]] = []
    occurrence_count: dict[str, int] = {}
    total_input_tokens = 0
    total_input_cost = 0.0

    for call in llm_calls:
        input_text: str = call.get("input_text") or ""
        model: str | None = call.get("model")
        input_tokens_val = call.get("input_tokens")
        input_tokens = int(input_tokens_val) if input_tokens_val is not None else 0

        input_cost_rate = call.get("input_cost_rate")
        legacy_rate = call.get("cost_rate_legacy")
        rate_for_denominator = (
            input_cost_rate if input_cost_rate is not None else legacy_rate
        )
        rate_for_denominator = (
            float(rate_for_denominator) if rate_for_denominator is not None else 0.0
        )

        total_input_tokens += input_tokens
        total_input_cost += input_tokens * rate_for_denominator

        chunks = _chunk_boundary(input_text)
        annotated: list[tuple[str, str | None, int]] = []
        for chunk_text, role in chunks:
            chash = _sha256_hex(chunk_text)
            annotated.append((chunk_text, role, _chunk_token_len(chunk_text, model)))
            occurrence_count[chash] = occurrence_count.get(chash, 0) + 1
        per_call.append(annotated)

    result.total_llm_input_tokens = total_input_tokens
    result.total_llm_input_cost = total_input_cost

    # Second pass — walk chunks in trace order. Count running occurrences of
    # each hash. The first `n-1` occurrences are the "origin plus any pre-n
    # repeats"; from the `n`-th occurrence onward, flag as resent (prereg §1:
    # "all occurrences after the first"). Track origin span_id for reporting.
    running_count: dict[str, int] = {}
    origin_span_for_hash: dict[str, str] = {}

    for i, call in enumerate(llm_calls):
        annotated = per_call[i]
        if not annotated:
            continue

        input_tokens_val = call.get("input_tokens")
        input_tokens = int(input_tokens_val) if input_tokens_val is not None else 0
        input_cost_rate = call.get("input_cost_rate")
        legacy_rate = call.get("cost_rate_legacy")
        rate = input_cost_rate if input_cost_rate is not None else legacy_rate
        rate = float(rate) if rate is not None else 0.0

        share_total = sum(t for _, _, t in annotated)
        if share_total == 0:
            continue

        for chunk_text, role, chunk_toks in annotated:
            chash = _sha256_hex(chunk_text)

            new_count = running_count.get(chash, 0) + 1
            running_count[chash] = new_count

            if chash not in origin_span_for_hash:
                origin_span_for_hash[chash] = call["span_id"]

            # First occurrence never flagged (necessary payload, prereg §1).
            # And only flag if the chunk's total across-trace count reaches n.
            if new_count < n:
                continue
            if occurrence_count[chash] < n:
                continue

            # §1.2 system-role exemption
            if role == "system":
                continue

            share = chunk_toks / share_total
            resent_toks = int(round(share * input_tokens))
            resent_cost = resent_toks * rate

            result.resent_events.append(ResentEvent(
                llm_span_id=call["span_id"],
                origin_llm_span_id=origin_span_for_hash[chash],
                chunk_hash=chash,
                chunk_role=role,
                resent_input_tokens=resent_toks,
                resent_cost=resent_cost,
            ))
            result.resent_input_tokens += resent_toks
            result.resent_cost += resent_cost

    return result
