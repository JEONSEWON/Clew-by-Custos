"""tests/test_generator.py — 4 pattern generators + paired structural matching verification."""

from __future__ import annotations

import json

import pytest

from eval.generators.patterns import PATTERNS
from eval.generators.patterns.base import FORBIDDEN_HINTS, topology_signature


PATTERN_NAMES = list(PATTERNS.keys())


@pytest.mark.parametrize("pattern", PATTERN_NAMES)
def test_positive_validates(pattern):
    pos_fn, _ = PATTERNS[pattern]
    gen = pos_fn(trace_id=f"t-pos-{pattern}", seed=42)
    assert gen.class_ == "positive"
    assert gen.pattern == pattern
    assert len(gen.trace.spans) > 0


@pytest.mark.parametrize("pattern", PATTERN_NAMES)
def test_clean_validates(pattern):
    _, clean_fn = PATTERNS[pattern]
    gen = clean_fn(trace_id=f"t-clean-{pattern}", seed=42)
    assert gen.class_ == "negative"
    assert gen.pattern == pattern
    assert len(gen.trace.spans) > 0


@pytest.mark.parametrize("pattern", PATTERN_NAMES)
def test_positive_waste_ids_subset_of_span_ids(pattern):
    pos_fn, _ = PATTERNS[pattern]
    gen = pos_fn(trace_id=f"t-pos-{pattern}", seed=42)
    all_ids = {s.span_id for s in gen.trace.spans}
    assert set(gen.waste_span_ids) <= all_ids
    assert len(gen.waste_span_ids) > 0  # positive must have 1+ labeled waste


@pytest.mark.parametrize("pattern", PATTERN_NAMES)
def test_clean_has_no_waste_label(pattern):
    _, clean_fn = PATTERNS[pattern]
    gen = clean_fn(trace_id=f"t-clean-{pattern}", seed=42)
    assert gen.waste_span_ids == []


@pytest.mark.parametrize("pattern", PATTERN_NAMES)
def test_structural_pairing(pattern):
    """positive and clean twins have exactly identical *structural topology*.

    The agent_or_node_id sequence, span_kind sequence, and parent-edge sequence must match
    so a "structure-only detector" cannot memorize the pattern. (Prevents v1 self-deception recurrence.)
    """
    pos_fn, clean_fn = PATTERNS[pattern]
    pos = pos_fn(trace_id=f"t-pos-{pattern}", seed=42)
    clean = clean_fn(trace_id=f"t-clean-{pattern}", seed=42)
    assert topology_signature(pos.trace) == topology_signature(clean.trace), (
        f"pattern {pattern!r}: positive/clean topology MUST match — if clean is "
        "flatter, a structure-only detector fires GO (v1 recurrence)"
    )


@pytest.mark.parametrize("pattern", PATTERN_NAMES)
def test_no_hint_words_in_trace_body(pattern):
    """No label hint word appears anywhere in the trace body."""
    pos_fn, clean_fn = PATTERNS[pattern]
    for fn, label in ((pos_fn, "positive"), (clean_fn, "clean")):
        gen = fn(trace_id=f"t-{label}-{pattern}", seed=42)
        body = []
        for s in gen.trace.spans:
            body.extend([s.agent_or_node_id, s.input_text, s.output_text])
        body.append(json.dumps(gen.trace.metadata, ensure_ascii=False))
        blob = " ".join(body).lower()
        for hint in FORBIDDEN_HINTS:
            assert hint.lower() not in blob, (
                f"pattern {pattern!r} ({label}) trace body contains forbidden hint "
                f"word {hint!r} — leakage risk"
            )


@pytest.mark.parametrize("pattern", PATTERN_NAMES)
def test_seed_determinism(pattern):
    """Same seed -> byte-identical trace."""
    pos_fn, _ = PATTERNS[pattern]
    a = pos_fn(trace_id="t-det", seed=42)
    b = pos_fn(trace_id="t-det", seed=42)
    assert a.trace.model_dump_json() == b.trace.model_dump_json()
    assert a.waste_span_ids == b.waste_span_ids


@pytest.mark.parametrize("pattern", PATTERN_NAMES)
def test_positive_clean_same_length(pattern):
    """Length matching (identical span count) — blocks length bias."""
    pos_fn, clean_fn = PATTERNS[pattern]
    pos = pos_fn(trace_id=f"t-pos-{pattern}", seed=42)
    clean = clean_fn(trace_id=f"t-clean-{pattern}", seed=42)
    assert len(pos.trace.spans) == len(clean.trace.spans)


@pytest.mark.parametrize("pattern", ["repeat_node", "regen_handoff", "pingpong_aba"])
def test_waste_output_differs_from_origin_by_bytes(pattern):
    """Realism guard: for the 3 LLM regen/repeat patterns (repeat_node, regen_handoff, pingpong_aba),
    waste-labeled spans must NOT be byte-identical to their *origin* span.

    Same meaning but different surface form is needed to reproduce the reality of LLM re-invocation
    (same task, different expression). Byte-identical is unrealistic and opens a self-deception path
    for a 'string equality detector' to fire GO.

    `requery_known` is the exception — identical re-lookup with the same key normally returns
    identical output, and byte-identical output itself is the waste signal, so it is excluded here.
    """
    pos_fn, _ = PATTERNS[pattern]
    gen = pos_fn(trace_id=f"t-pos-{pattern}", seed=42)
    by_id = {s.span_id: s for s in gen.trace.spans}
    assert gen.near_duplicate_of, (
        f"{pattern}: positive must declare near_duplicate_of mapping "
        "(waste span -> origin span) for realism guard"
    )
    for waste_id, origin_id in gen.near_duplicate_of.items():
        wo = by_id[waste_id].output_text
        oo = by_id[origin_id].output_text
        assert wo != oo, (
            f"{pattern}: waste span {waste_id!r} has BYTE-IDENTICAL output_text to "
            f"origin {origin_id!r} — unrealistic (LLM rarely produces byte-identical "
            "reruns; this opens a string-equality detector to spurious GO)"
        )


def test_requery_known_declares_no_near_duplicate_pairs():
    """requery_known's positive leaves near_duplicate_of empty — re-lookup with the same key
    normally returns identical output, so this is explicitly out of scope of the realism guard above.
    """
    pos = PATTERNS["requery_known"][0](trace_id="t-r", seed=42)
    assert pos.near_duplicate_of == {}, (
        "requery_known: for positive, byte-identical re-lookup is the normal signal — "
        "leave near_duplicate_of intentionally empty"
    )
