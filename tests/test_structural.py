"""tests/test_structural.py — 구조 후보 탐지 단위 테스트.

(i) 반복 노드 N=2: 같은 agent_or_node_id가 2회 → 1쌍
(ii) 핑퐁:        A→B→A→B → 2쌍
(iii) 깨끗한 트레이스: 빈 리스트
(iv) 라벨 미참조: 본문에 'labels' 문자열 0개
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from clew.detect.structural import (
    find_candidates,
    find_pingpong_candidates,
    find_repeat_candidates,
)
from clew.model import Span, Trace


def _ts(offset: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset)


def _span(trace_id: str, sid: str, parent: str | None, agent: str, t: int, out: str = "x") -> Span:
    return Span(
        trace_id=trace_id,
        span_id=sid,
        parent_span_id=parent,
        agent_or_node_id=agent,
        span_kind="llm" if parent else "chain",
        start_time=_ts(t),
        end_time=_ts(t + 1),
        input_text="",
        output_text=out,
        token_count=10,
        model="fake",
        cost_rate=1e-6,
    )


def _trace(spans: list[Span]) -> Trace:
    return Trace(trace_id=spans[0].trace_id, spans=spans)


def test_repeat_candidates_n2_finds_pair():
    spans = [
        _span("t", "s1", None, "run", 0),
        _span("t", "s2", "s1", "analyze", 1, "first"),
        _span("t", "s3", "s1", "analyze", 2, "second"),
    ]
    pairs = find_repeat_candidates(_trace(spans), n=2)
    assert len(pairs) == 1
    origin, cand = pairs[0]
    assert origin.span_id == "s2" and cand.span_id == "s3"


def test_repeat_candidates_threshold_blocks_single_occurrence():
    """단일 등장은 N=2 임계로 후보가 아님."""
    spans = [
        _span("t", "s1", None, "run", 0),
        _span("t", "s2", "s1", "analyze", 1),
    ]
    assert find_repeat_candidates(_trace(spans), n=2) == []


def test_repeat_candidates_three_occurrences_emit_two_pairs():
    spans = [
        _span("t", "s1", None, "run", 0),
        _span("t", "s2", "s1", "analyze", 1, "a"),
        _span("t", "s3", "s1", "analyze", 2, "b"),
        _span("t", "s4", "s1", "analyze", 3, "c"),
    ]
    pairs = find_repeat_candidates(_trace(spans), n=2)
    assert sorted((o.span_id, c.span_id) for o, c in pairs) == [("s2", "s3"), ("s2", "s4")]


def test_pingpong_emits_two_pairs():
    spans = [
        _span("t", "s1", None, "run", 0),
        _span("t", "s2", "s1", "A", 1),
        _span("t", "s3", "s1", "B", 2),
        _span("t", "s4", "s1", "A", 3),
        _span("t", "s5", "s1", "B", 4),
    ]
    pairs = find_pingpong_candidates(_trace(spans))
    keys = sorted((o.span_id, c.span_id) for o, c in pairs)
    assert keys == [("s2", "s4"), ("s3", "s5")]


def test_pingpong_requires_alternation():
    """A→A→A는 핑퐁이 아님 (반복 노드로만 잡힘)."""
    spans = [
        _span("t", "s1", None, "run", 0),
        _span("t", "s2", "s1", "A", 1),
        _span("t", "s3", "s1", "A", 2),
        _span("t", "s4", "s1", "A", 3),
        _span("t", "s5", "s1", "A", 4),
    ]
    assert find_pingpong_candidates(_trace(spans)) == []


def test_clean_trace_no_candidates():
    spans = [
        _span("t", "s1", None, "run", 0),
        _span("t", "s2", "s1", "start", 1),
        _span("t", "s3", "s1", "analyze", 2),
        _span("t", "s4", "s1", "report", 3),
    ]
    assert find_candidates(_trace(spans), n=2) == []


def test_find_candidates_dedupes_repeat_and_pingpong_overlap():
    """반복 후보와 핑퐁 후보가 같은 쌍을 만들면 한 번만 반환."""
    spans = [
        _span("t", "s1", None, "run", 0),
        _span("t", "s2", "s1", "A", 1),
        _span("t", "s3", "s1", "B", 2),
        _span("t", "s4", "s1", "A", 3),
        _span("t", "s5", "s1", "B", 4),
    ]
    pairs = find_candidates(_trace(spans), n=2)
    keys = sorted((o.span_id, c.span_id) for o, c in pairs)
    assert keys == [("s2", "s4"), ("s3", "s5")]


def test_invalid_n_raises():
    spans = [
        _span("t", "s1", None, "run", 0),
        _span("t", "s2", "s1", "analyze", 1),
    ]
    with pytest.raises(ValueError):
        find_repeat_candidates(_trace(spans), n=1)


def test_structural_source_does_not_reference_labels():
    """structural.py 본문에 'labels' 문자열 0개 (누수 가드 보조)."""
    src = Path(__file__).parent.parent / "src" / "clew" / "detect" / "structural.py"
    text = src.read_text(encoding="utf-8")
    assert "labels" not in text
    assert "eval/" not in text


# ─── SPEC §8 2.1: span_kind 인지 입력 게이트 (tool kind 만 적용) ────────────────


def _tool_span(sid: str, parent: str, agent: str, t: int, input_text: str, out: str = "x") -> Span:
    return Span(
        trace_id="t",
        span_id=sid,
        parent_span_id=parent,
        agent_or_node_id=agent,
        span_kind="tool",
        start_time=_ts(t),
        end_time=_ts(t + 1),
        input_text=input_text,
        output_text=out,
        token_count=10,
        model="fake",
        cost_rate=1e-6,
    )


def _llm_span(sid: str, parent: str, agent: str, t: int, input_text: str, out: str) -> Span:
    return Span(
        trace_id="t",
        span_id=sid,
        parent_span_id=parent,
        agent_or_node_id=agent,
        span_kind="llm",
        start_time=_ts(t),
        end_time=_ts(t + 1),
        input_text=input_text,
        output_text=out,
        token_count=10,
        model="fake",
        cost_rate=1e-6,
    )


def test_tool_input_gate_blocks_different_inputs():
    """tool kind 반복 + input 다름 → 후보 아님 (정당한 무관 조회)."""
    spans = [
        _span("t", "s1", None, "run", 0),
        _tool_span("s2", "s1", "lookup", 1, input_text="customer_id=12345"),
        _tool_span("s3", "s1", "lookup", 2, input_text="customer_id=67890"),
    ]
    assert find_repeat_candidates(_trace(spans), n=2) == []


def test_tool_input_gate_passes_identical_inputs():
    """tool kind 반복 + input 동일 → 후보 박힘 (재조회 낭비 후보)."""
    spans = [
        _span("t", "s1", None, "run", 0),
        _tool_span("s2", "s1", "lookup", 1, input_text="customer_id=12345"),
        _tool_span("s3", "s1", "lookup", 2, input_text="customer_id=12345"),
    ]
    pairs = find_repeat_candidates(_trace(spans), n=2)
    assert [(o.span_id, c.span_id) for o, c in pairs] == [("s2", "s3")]


def test_tool_input_gate_normalizes_whitespace_and_case():
    """SPEC §8 2.1 normalized-equal = strip()+casefold(). 공백/대소문자 동등."""
    spans = [
        _span("t", "s1", None, "run", 0),
        _tool_span("s2", "s1", "lookup", 1, input_text="customer_id=12345"),
        _tool_span("s3", "s1", "lookup", 2, input_text="  Customer_ID=12345  "),
    ]
    pairs = find_repeat_candidates(_trace(spans), n=2)
    assert [(o.span_id, c.span_id) for o, c in pairs] == [("s2", "s3")]


def test_llm_kind_repeat_ignores_input_gate():
    """span_kind=='llm' 반복은 input 차이 무관 — 후보 박힘 (회귀 보호: 다른 3패턴)."""
    spans = [
        _span("t", "s1", None, "run", 0),
        _llm_span("s2", "s1", "analyze", 1, input_text="prompt_v1", out="r1"),
        _llm_span("s3", "s1", "analyze", 2, input_text="prompt_v2_DIFFERENT", out="r2"),
    ]
    pairs = find_repeat_candidates(_trace(spans), n=2)
    assert [(o.span_id, c.span_id) for o, c in pairs] == [("s2", "s3")]


def test_tool_gate_origin_basis_recovers_aba_repeat():
    """[A(k), B(k'), A(k)] tool 시퀀스: 중간 cand 가 origin과 input 다르면 skip,
    이후 같은 input 재등장은 다시 후보 — origin 기준 게이트 일관성."""
    spans = [
        _span("t", "s1", None, "run", 0),
        _tool_span("s2", "s1", "lookup", 1, input_text="key=A"),
        _tool_span("s3", "s1", "lookup", 2, input_text="key=B"),
        _tool_span("s4", "s1", "lookup", 3, input_text="key=A"),
    ]
    pairs = find_repeat_candidates(_trace(spans), n=2)
    assert [(o.span_id, c.span_id) for o, c in pairs] == [("s2", "s4")]


def test_c1_requery_known_hard_clean_yields_no_candidates():
    """CRITERIA C1: requery_known clean 의 hard 분기 인스턴스 → 구조 후보 0개.

    hard 분기 식별: 두 lookup input 모두 'customer_id=' 시작 + 값 다름.
    50회 중 ~25개 가 hard 에 떨어질 것으로 기대.
    """
    from eval.generators.patterns.requery_known import make_clean

    hard_count = 0
    for seed in range(50):
        gen = make_clean(trace_id=f"t-c1-{seed}", seed=seed)
        lookups = sorted(
            (s for s in gen.trace.spans if s.agent_or_node_id == "lookup"),
            key=lambda s: s.start_time,
        )
        assert len(lookups) == 2
        is_hard = (
            lookups[0].input_text.startswith("customer_id=")
            and lookups[1].input_text.startswith("customer_id=")
            and lookups[0].input_text != lookups[1].input_text
        )
        if is_hard:
            hard_count += 1
            assert find_candidates(gen.trace, n=2) == [], (
                f"seed={seed}: hard 인스턴스에서 후보 발생 — 입력 게이트 실패"
            )
    assert hard_count >= 10, f"hard 분기에 떨어진 인스턴스가 너무 적음: {hard_count}/50"
