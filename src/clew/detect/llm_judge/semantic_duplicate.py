# Spec: docs/LLM_JUDGE_SEMANTIC_DUPLICATE_PREREG.md (Rule 8 prereg).
"""Semantic duplicate detector — LLM-judge extension of context_resend.

Detects paraphrased re-sends: two message chunks with different bytes
but the same meaning. Sits ON TOP of the deterministic context_resend
detector — chunks already flagged by byte-exact match are excluded
here (that's the deterministic detector's territory, prereg §1).

Opt-in ONLY. Default OFF. Requires `CLEW_ENABLE_LLM_JUDGE=1` (or
CLI --llm-judge) AND `ANTHROPIC_API_KEY`. Without both, returns an
empty result with `enabled=False`.

Prereg §5 Jaccard pre-filter: candidate pairs with jaccard char-3-gram
similarity < 0.30 are dropped before the judge call. This saves 90%+
of judge calls in typical workloads.

Non-determinism: judge verdicts are non-reproducible even at
temperature=0. The result's `cost_accuracy_flag` remains
"estimated" whenever any judge call was made.
"""
from __future__ import annotations

import logging
import os
import sys
import warnings
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from clew.detect.context_resend import _chunk_boundary, _sha256_hex
from clew.detect.llm_judge.anthropic_client import (
    AnthropicJudge,
    JudgeUnavailableError,
    JudgeVerdict,
)
from clew.detect.llm_judge.prompts import CONFIDENCE_THRESHOLD
from clew.model import Trace


logger = logging.getLogger(__name__)


DEFAULT_JUDGE_MODEL = "claude-haiku-4-5"  # prereg §3 frozen default
DEFAULT_MAX_CALLS = 50                     # prereg §5 frozen default
HARD_CAP_MAX_CALLS = 500                   # prereg §8 frozen hard cap
JACCARD_THRESHOLD = 0.30                   # prereg §5 frozen
DEFAULT_COST_CAP_USD = 10.0                # prereg §8 frozen default


@dataclass
class LLMJudgeMatch:
    kind: Literal["semantic_duplicate"]
    chunk_a_hash: str
    chunk_b_hash: str
    origin_llm_span_id: str
    candidate_llm_span_id: str
    equivalent: bool
    confidence: float
    reasoning: str
    judge_model: str
    judge_cost: float


@dataclass
class LLMJudgeResult:
    trace_id: str
    matches: list[LLMJudgeMatch] = field(default_factory=list)
    total_judge_calls: int = 0
    total_judge_cost: float = 0.0
    total_semantic_resent_tokens: int = 0
    total_semantic_resent_cost: float = 0.0
    enabled: bool = False


# ── Jaccard pre-filter (deterministic) ───────────────────────────────────────

def _char_3grams(text: str) -> set[str]:
    if len(text) < 3:
        return {text}
    return {text[i:i + 3] for i in range(len(text) - 2)}


def _jaccard(a: str, b: str) -> float:
    ga = _char_3grams(a)
    gb = _char_3grams(b)
    if not ga or not gb:
        return 0.0
    inter = ga & gb
    union = ga | gb
    return len(inter) / len(union) if union else 0.0


# ── Candidate assembly ──────────────────────────────────────────────────────

def _extract_chunks(
    llm_calls: list[dict[str, Any]],
) -> list[tuple[str, str, str | None, int]]:
    """Return list of (chunk_text, chunk_hash, role, source_llm_span_index).

    Roles that are "system" are filtered out (prereg §1.2 inherited).
    """
    out: list[tuple[str, str, str | None, int]] = []
    for i, call in enumerate(llm_calls):
        input_text = call.get("input_text") or ""
        for chunk_text, role in _chunk_boundary(input_text):
            if role == "system":
                continue
            out.append((chunk_text, _sha256_hex(chunk_text), role, i))
    return out


# ── JudgeClient protocol ────────────────────────────────────────────────────

# For testability the detector accepts an optional `judge_fn` callable.
# In production it defaults to an AnthropicJudge.judge bound method.
JudgeFn = Callable[[str, str], JudgeVerdict]


# ── Detector entry point ────────────────────────────────────────────────────

def _resolve_enabled(
    enabled_arg: bool | None,
) -> bool:
    """Prereg §2: enabled iff CLI arg true OR env var set."""
    if enabled_arg is True:
        return True
    if enabled_arg is False:
        return False
    return os.environ.get("CLEW_ENABLE_LLM_JUDGE") == "1"


def _resolve_max_calls(max_calls: int | None) -> int:
    if max_calls is None:
        env_val = os.environ.get("CLEW_LLM_JUDGE_MAX_CALLS")
        if env_val:
            try:
                max_calls = int(env_val)
            except ValueError:
                max_calls = DEFAULT_MAX_CALLS
        else:
            max_calls = DEFAULT_MAX_CALLS
    return min(max(1, max_calls), HARD_CAP_MAX_CALLS)


def _resolve_cost_cap(cost_cap_usd: float | None) -> float:
    if cost_cap_usd is None:
        env_val = os.environ.get("CLEW_LLM_JUDGE_MAX_COST_USD")
        if env_val:
            try:
                return float(env_val)
            except ValueError:
                pass
        return DEFAULT_COST_CAP_USD
    return cost_cap_usd


def _next_llm_rate_for_span_index(
    llm_calls: list[dict[str, Any]], call_index: int,
) -> float:
    """Effective per-token input rate for the LLM call at `call_index`
    (used to attribute cost of the resent chunk)."""
    from clew.detect.context_resend import _rate_and_cost_for_call  # noqa: PLC0415

    if not (0 <= call_index < len(llm_calls)):
        return 0.0
    rate, _, _ = _rate_and_cost_for_call(llm_calls[call_index])
    return rate


def find_llm_judge_semantic_duplicates(
    trace: Trace,
    *,
    enabled: bool | None = None,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    max_calls: int | None = None,
    cost_cap_usd: float | None = None,
    judge_fn: JudgeFn | None = None,
) -> LLMJudgeResult:
    """Detect semantic-duplicate chunk pairs via LLM judge (prereg §1-6).

    `judge_fn` (optional): callable that takes two chunk strings and
    returns a `JudgeVerdict`. Used for testing. When None, an
    `AnthropicJudge` is constructed lazily.
    """
    result = LLMJudgeResult(trace_id=trace.trace_id)

    is_enabled = _resolve_enabled(enabled)
    if not is_enabled:
        return result

    result.enabled = True
    max_calls_resolved = _resolve_max_calls(max_calls)
    cost_cap = _resolve_cost_cap(cost_cap_usd)

    llm_calls = list(trace.metadata.get("llm_calls") or [])
    if len(llm_calls) < 2:
        return result

    # Extract candidate chunks across all calls (skipping system-role).
    chunks = _extract_chunks(llm_calls)
    if len(chunks) < 2:
        return result

    # Build candidate pairs: different calls, non-identical bytes.
    # Prereg §5: Jaccard >= 0.30 pre-filter.
    candidates: list[tuple[int, int, float]] = []  # (i, j, jaccard)
    seen_pair_hashes: set[tuple[str, str]] = set()
    for i in range(len(chunks)):
        for j in range(i + 1, len(chunks)):
            text_i, hash_i, _role_i, call_i = chunks[i]
            text_j, hash_j, _role_j, call_j = chunks[j]
            if call_i == call_j:
                continue
            if hash_i == hash_j:
                continue  # byte-exact — context_resend territory
            # Deduplicate pair hashes (same chunk pair appearing across
            # multiple calls should be judged once).
            pair_key = (hash_i, hash_j) if hash_i < hash_j else (hash_j, hash_i)
            if pair_key in seen_pair_hashes:
                continue
            seen_pair_hashes.add(pair_key)

            jac = _jaccard(text_i, text_j)
            if jac < JACCARD_THRESHOLD:
                continue
            candidates.append((i, j, jac))

    if not candidates:
        return result

    # Prereg §5: cap to max_calls, ordered by Jaccard desc (higher
    # similarity → more likely paraphrase → judge first).
    candidates.sort(key=lambda t: t[2], reverse=True)
    candidates = candidates[:max_calls_resolved]

    # Pre-run cost estimate (prereg §5).
    est_max_cost = _estimate_max_cost(judge_model, len(candidates))
    print(
        f"boxdawn: LLM judge enabled — {len(candidates)} candidate pairs, "
        f"est. max cost ${est_max_cost:.4f}",
        file=sys.stderr,
    )

    # Lazy-construct judge client (unless test-injected).
    if judge_fn is None:
        try:
            judge_client = AnthropicJudge(model=judge_model)
        except JudgeUnavailableError as e:
            warnings.warn(str(e), stacklevel=2)
            result.enabled = False
            return result
        judge_fn = judge_client.judge

    # Execute judge calls, respecting cost cap.
    accumulated_cost = 0.0
    for i, j, _jac in candidates:
        if accumulated_cost >= cost_cap:
            warnings.warn(
                f"boxdawn judge: cost cap ${cost_cap} reached "
                f"({accumulated_cost:.4f} spent); stopping",
                stacklevel=2,
            )
            break

        text_i, hash_i, _role_i, call_i = chunks[i]
        text_j, hash_j, _role_j, call_j = chunks[j]

        verdict = judge_fn(text_i, text_j)
        result.total_judge_calls += 1
        result.total_judge_cost += verdict.cost_usd
        accumulated_cost += verdict.cost_usd

        # Prereg §1 gate: equivalent AND confidence >= threshold.
        if not verdict.equivalent:
            continue
        if verdict.confidence < CONFIDENCE_THRESHOLD:
            continue

        # Origin = earliest call between the two.
        if call_i <= call_j:
            origin_call, cand_call = call_i, call_j
            origin_hash, cand_hash = hash_i, hash_j
            cand_text = text_j
        else:
            origin_call, cand_call = call_j, call_i
            origin_hash, cand_hash = hash_j, hash_i
            cand_text = text_i

        origin_span = llm_calls[origin_call].get("span_id", "?")
        cand_span = llm_calls[cand_call].get("span_id", "?")

        # Cost attribution: candidate chunk's token count × downstream rate.
        cand_tokens = _tokenize_len(cand_text, llm_calls[cand_call].get("model"))
        cand_rate = _next_llm_rate_for_span_index(llm_calls, cand_call)
        cand_cost = cand_tokens * cand_rate

        result.matches.append(LLMJudgeMatch(
            kind="semantic_duplicate",
            chunk_a_hash=origin_hash,
            chunk_b_hash=cand_hash,
            origin_llm_span_id=origin_span,
            candidate_llm_span_id=cand_span,
            equivalent=True,
            confidence=verdict.confidence,
            reasoning=verdict.reasoning,
            judge_model=judge_model,
            judge_cost=verdict.cost_usd,
        ))
        result.total_semantic_resent_tokens += cand_tokens
        result.total_semantic_resent_cost += cand_cost

    return result


# ── Cost estimate (prereg §5) ────────────────────────────────────────────────

def _estimate_max_cost(judge_model: str, num_calls: int) -> float:
    """Rough upper bound: each call ~4000 input + 256 output tokens max."""
    from clew.cost.pricing import get_pricing  # noqa: PLC0415

    pricing = get_pricing(judge_model)
    per_call = (
        (4000 * pricing.base_input_per_mtok)
        + (256 * pricing.output_per_mtok)
    ) / 1_000_000.0
    return per_call * num_calls


def _tokenize_len(text: str, model: str | None) -> int:
    """Best-effort token count for cost attribution (same as
    redundant_read._tiktoken_len). Uses tiktoken when available, else
    char/4 fallback."""
    if not text:
        return 0
    try:
        import tiktoken  # noqa: PLC0415

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
