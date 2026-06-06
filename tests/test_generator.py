"""tests/test_generator.py — 패턴 생성기 4종 + paired structural matching 검증."""

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
    assert len(gen.waste_span_ids) > 0  # positive는 반드시 라벨된 낭비가 1+


@pytest.mark.parametrize("pattern", PATTERN_NAMES)
def test_clean_has_no_waste_label(pattern):
    _, clean_fn = PATTERNS[pattern]
    gen = clean_fn(trace_id=f"t-clean-{pattern}", seed=42)
    assert gen.waste_span_ids == []


@pytest.mark.parametrize("pattern", PATTERN_NAMES)
def test_structural_pairing(pattern):
    """★ positive와 clean 트윈의 *구조 토폴로지*가 정확히 동일.

    agent_or_node_id 시퀀스, span_kind 시퀀스, parent-edge 시퀀스가 같아야
    "구조 단독 탐지기"가 패턴을 못 외운다. (v1 자기기만 재발 방지.)
    """
    pos_fn, clean_fn = PATTERNS[pattern]
    pos = pos_fn(trace_id=f"t-pos-{pattern}", seed=42)
    clean = clean_fn(trace_id=f"t-clean-{pattern}", seed=42)
    assert topology_signature(pos.trace) == topology_signature(clean.trace), (
        f"pattern {pattern!r}: positive/clean topology MUST match — clean이 더 "
        "평평하면 구조 단독 탐지기가 GO를 띄움 (v1 재발)"
    )


@pytest.mark.parametrize("pattern", PATTERN_NAMES)
def test_no_hint_words_in_trace_body(pattern):
    """라벨 hint 단어가 트레이스 본문 어디에도 등장하지 않음."""
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
    """같은 seed → 바이트 단위 동일 트레이스."""
    pos_fn, _ = PATTERNS[pattern]
    a = pos_fn(trace_id="t-det", seed=42)
    b = pos_fn(trace_id="t-det", seed=42)
    assert a.trace.model_dump_json() == b.trace.model_dump_json()
    assert a.waste_span_ids == b.waste_span_ids


@pytest.mark.parametrize("pattern", PATTERN_NAMES)
def test_positive_clean_same_length(pattern):
    """길이 매칭(스팬 수 동일) — 길이 편향 차단."""
    pos_fn, clean_fn = PATTERNS[pattern]
    pos = pos_fn(trace_id=f"t-pos-{pattern}", seed=42)
    clean = clean_fn(trace_id=f"t-clean-{pattern}", seed=42)
    assert len(pos.trace.spans) == len(clean.trace.spans)


@pytest.mark.parametrize("pattern", ["repeat_node", "regen_handoff", "pingpong_aba"])
def test_waste_output_differs_from_origin_by_bytes(pattern):
    """현실성 가드: LLM 재생성/반복 패턴 3종(repeat_node·regen_handoff·pingpong_aba)에서
    낭비-라벨된 스팬은 그 *원본* 스팬과 바이트 단위로 동일하지 않아야 한다.

    의미는 같지만 표면 표현은 달라야 LLM 재호출의 현실(같은 작업, 다른 표현)을 재현.
    바이트 동일은 비현실적이고 'string equality 탐지기'가 GO 띄우는 자기기만 통로.

    `requery_known`은 예외 — 동일 키 재조회는 동일 출력이 정상이며, 출력 바이트 동일
    자체가 낭비 신호이므로 이 가드에서 제외.
    """
    pos_fn, _ = PATTERNS[pattern]
    gen = pos_fn(trace_id=f"t-pos-{pattern}", seed=42)
    by_id = {s.span_id: s for s in gen.trace.spans}
    assert gen.near_duplicate_of, (
        f"{pattern}: positive must declare near_duplicate_of mapping "
        "(낭비 스팬 → 원본 스팬) for realism guard"
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
    """requery_known의 positive는 near_duplicate_of를 비워둔다 — 같은 키 재조회는
    동일 출력이 정상 신호이므로 위 현실성 가드 대상이 아님을 명시.
    """
    pos = PATTERNS["requery_known"][0](trace_id="t-r", seed=42)
    assert pos.near_duplicate_of == {}, (
        "requery_known: positive는 byte-identical 재조회가 정상 신호 — "
        "near_duplicate_of를 의도적으로 비워둘 것"
    )
