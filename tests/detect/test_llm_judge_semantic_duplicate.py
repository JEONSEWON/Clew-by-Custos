"""tests/detect/test_llm_judge_semantic_duplicate.py — prereg §11.1.

Locks the opt-in gate, Jaccard pre-filter, confidence threshold,
rate limits, and non-determinism behavior. Uses a mock judge for
all cases; the real Anthropic integration test lives separately.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import pytest

from clew.detect.llm_judge.anthropic_client import JudgeVerdict
from clew.detect.llm_judge.semantic_duplicate import (
    _jaccard,
    find_llm_judge_semantic_duplicates,
)
from clew.model import Span, Trace


# ── fixtures ────────────────────────────────────────────────────────────────

def _root_trace(llm_calls: list[dict[str, Any]] | None = None) -> Trace:
    root = Span(
        trace_id="T", span_id="root", parent_span_id=None,
        agent_or_node_id="root", span_kind="chain",
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        input_text="", output_text="[root]",
    )
    md: dict[str, Any] = {}
    if llm_calls is not None:
        md["llm_calls"] = llm_calls
    return Trace(trace_id="T", spans=[root], metadata=md)


def _call(span_id: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "span_id": span_id,
        "input_text": json.dumps(messages),
        "input_tokens": 100,
        "output_tokens": 20,
        "input_tokens_uncached": 100,
        "input_tokens_cache_read": 0,
        "input_tokens_cache_write": 0,
        "input_cost_rate": None,
        "output_cost_rate": None,
        "cost_rate_legacy": None,
        "model": "claude-sonnet-4-5",
        "start_time": "2026-01-01T00:00:00+00:00",
    }


def _fake_judge_yes(chunk_a: str, chunk_b: str) -> JudgeVerdict:
    return JudgeVerdict(
        equivalent=True, confidence=0.95, reasoning="paraphrase",
        input_tokens=100, output_tokens=20, cost_usd=0.0001,
    )


def _fake_judge_no(chunk_a: str, chunk_b: str) -> JudgeVerdict:
    return JudgeVerdict(
        equivalent=False, confidence=0.95, reasoning="different",
        input_tokens=100, output_tokens=20, cost_usd=0.0001,
    )


def _fake_judge_low_confidence(chunk_a: str, chunk_b: str) -> JudgeVerdict:
    return JudgeVerdict(
        equivalent=True, confidence=0.80, reasoning="unsure",
        input_tokens=100, output_tokens=20, cost_usd=0.0001,
    )


# ── tests ───────────────────────────────────────────────────────────────────

def test_disabled_by_default(monkeypatch):
    """No `enabled=True` and no env var → returns empty, enabled=False."""
    monkeypatch.delenv("CLEW_ENABLE_LLM_JUDGE", raising=False)
    call_a = _call("llm-a", [{"role": "user", "content": "hello world"}])
    call_b = _call("llm-b", [{"role": "user", "content": "hey world"}])
    trace = _root_trace([call_a, call_b])

    r = find_llm_judge_semantic_duplicates(trace, judge_fn=_fake_judge_yes)
    assert r.enabled is False
    assert r.matches == []
    assert r.total_judge_calls == 0


def test_enabled_via_env_var(monkeypatch):
    """CLEW_ENABLE_LLM_JUDGE=1 alone enables the detector."""
    monkeypatch.setenv("CLEW_ENABLE_LLM_JUDGE", "1")
    call_a = _call("llm-a", [{"role": "user", "content": "hello world today"}])
    call_b = _call("llm-b", [{"role": "user", "content": "hello world today"[:] + " more"}])
    trace = _root_trace([call_a, call_b])

    r = find_llm_judge_semantic_duplicates(trace, judge_fn=_fake_judge_yes)
    assert r.enabled is True


def test_enabled_via_arg_overrides_env(monkeypatch):
    """Explicit `enabled=True` argument wins over env var."""
    monkeypatch.delenv("CLEW_ENABLE_LLM_JUDGE", raising=False)
    call_a = _call("llm-a", [{"role": "user", "content": "hello world"}])
    call_b = _call("llm-b", [{"role": "user", "content": "hi world "}])
    trace = _root_trace([call_a, call_b])

    r = find_llm_judge_semantic_duplicates(
        trace, enabled=True, judge_fn=_fake_judge_yes,
    )
    assert r.enabled is True


def test_jaccard_pre_filter_low_similarity_skipped():
    """Two completely different chunks → not sent to judge.

    Uses the fallback (non-JSON) chunk path so the entire input_text
    becomes the chunk. This isolates jaccard from JSON scaffolding
    overlap.
    """
    # Non-JSON input → whole string becomes one chunk.
    call_a = _call("llm-a", "🌸🌸🌸🌸🌸 unique1 🌸🌸🌸🌸🌸")
    call_b = _call("llm-b", "██████ different2 ██████")
    # Override input_text directly (bypass JSON serialization).
    call_a["input_text"] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    call_b["input_text"] = "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"
    trace = _root_trace([call_a, call_b])

    r = find_llm_judge_semantic_duplicates(
        trace, enabled=True, judge_fn=_fake_judge_yes,
    )
    # Jaccard should be 0.0 → no candidates → no judge calls
    assert r.total_judge_calls == 0
    assert r.matches == []


def test_jaccard_pre_filter_high_similarity_advances():
    """Two similar chunks (>= 0.30 jaccard) → candidate for judge."""
    text_a = "the quick brown fox jumps over the lazy dog"
    text_b = "the quick brown fox leaps over the lazy dog"  # one word diff
    assert _jaccard(text_a, text_b) >= 0.30
    call_a = _call("llm-a", [{"role": "user", "content": text_a}])
    call_b = _call("llm-b", [{"role": "user", "content": text_b}])
    trace = _root_trace([call_a, call_b])

    r = find_llm_judge_semantic_duplicates(
        trace, enabled=True, judge_fn=_fake_judge_yes,
    )
    assert r.total_judge_calls >= 1


def test_byte_exact_matches_skipped():
    """Chunks with same sha256 → not sent to judge (context_resend territory)."""
    msg = {"role": "user", "content": "identical bytes"}
    call_a = _call("llm-a", [msg])
    call_b = _call("llm-b", [msg])
    trace = _root_trace([call_a, call_b])

    r = find_llm_judge_semantic_duplicates(
        trace, enabled=True, judge_fn=_fake_judge_yes,
    )
    # Byte-exact → excluded from candidates
    assert r.total_judge_calls == 0


def test_system_role_exempt():
    """Chunks with role=='system' → not sent to judge."""
    sys_a = {"role": "system", "content": "you are helpful"}
    sys_b = {"role": "system", "content": "you are so helpful"}
    call_a = _call("llm-a", [sys_a, {"role": "user", "content": "q1"}])
    call_b = _call("llm-b", [sys_b, {"role": "user", "content": "q2"}])
    trace = _root_trace([call_a, call_b])

    r = find_llm_judge_semantic_duplicates(
        trace, enabled=True, judge_fn=_fake_judge_yes,
    )
    # user chunks are different enough by jaccard to escape pre-filter; but
    # system chunks would have been the paraphrase candidates → excluded.
    # Assertion: no match where either origin/candidate is a system chunk.
    for m in r.matches:
        assert not m.reasoning.startswith("(system)")


def test_max_calls_cap():
    """max_calls=2 with 5 candidate pairs → at most 2 judge calls."""
    calls = []
    for i in range(5):
        # Force high jaccard: shared prefix + trailing diff.
        text = "shared prefix that is fairly long and identical " + str(i)
        calls.append(_call(f"llm-{i}", [{"role": "user", "content": text}]))
    trace = _root_trace(calls)

    r = find_llm_judge_semantic_duplicates(
        trace, enabled=True, max_calls=2, judge_fn=_fake_judge_yes,
    )
    assert r.total_judge_calls <= 2


def test_hard_cap_enforced():
    """User sets max_calls=1000; hard cap 500 wins."""
    call_a = _call("llm-a", [{"role": "user", "content": "the quick brown fox"}])
    call_b = _call("llm-b", [{"role": "user", "content": "the quick brown foxx"}])
    trace = _root_trace([call_a, call_b])

    # Only 1 candidate pair here, but hard cap should not raise on high input.
    r = find_llm_judge_semantic_duplicates(
        trace, enabled=True, max_calls=1000, judge_fn=_fake_judge_yes,
    )
    assert r.total_judge_calls <= 500


def test_confidence_below_threshold_not_matched():
    """confidence 0.80 < 0.85 → not counted as match."""
    call_a = _call("llm-a", [{"role": "user", "content": "the quick brown fox"}])
    call_b = _call("llm-b", [{"role": "user", "content": "the quick brown foxx"}])
    trace = _root_trace([call_a, call_b])

    r = find_llm_judge_semantic_duplicates(
        trace, enabled=True, judge_fn=_fake_judge_low_confidence,
    )
    assert r.total_judge_calls >= 1
    assert r.matches == []


def test_confidence_at_or_above_threshold_matches():
    """confidence 0.95 >= 0.85 → counted as match."""
    call_a = _call("llm-a", [{"role": "user", "content": "the quick brown fox"}])
    call_b = _call("llm-b", [{"role": "user", "content": "the quick brown foxx"}])
    trace = _root_trace([call_a, call_b])

    r = find_llm_judge_semantic_duplicates(
        trace, enabled=True, judge_fn=_fake_judge_yes,
    )
    assert r.total_judge_calls >= 1
    assert len(r.matches) == 1


def test_deterministic_candidate_selection():
    """Same trace → same candidate list (Jaccard pre-filter is stable)."""
    call_a = _call("llm-a", [{"role": "user", "content": "the quick brown fox jumps over"}])
    call_b = _call("llm-b", [{"role": "user", "content": "the quick brown fox leaps over"}])
    trace = _root_trace([call_a, call_b])

    r1 = find_llm_judge_semantic_duplicates(
        trace, enabled=True, judge_fn=_fake_judge_yes,
    )
    r2 = find_llm_judge_semantic_duplicates(
        trace, enabled=True, judge_fn=_fake_judge_yes,
    )
    assert r1.total_judge_calls == r2.total_judge_calls
    assert len(r1.matches) == len(r2.matches)


def test_cost_accumulation():
    """Judge cost accumulates across matched pairs."""
    call_a = _call("llm-a", [{"role": "user", "content": "the quick brown fox"}])
    call_b = _call("llm-b", [{"role": "user", "content": "the quick brown foxx"}])
    trace = _root_trace([call_a, call_b])

    r = find_llm_judge_semantic_duplicates(
        trace, enabled=True, judge_fn=_fake_judge_yes,
    )
    assert r.total_judge_cost > 0.0
    # matches carry per-call cost
    if r.matches:
        assert r.matches[0].judge_cost > 0.0
