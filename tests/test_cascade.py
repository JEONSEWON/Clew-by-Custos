"""tests/test_cascade.py — 구조 AND 의미 결합 + 비용 산출.

(i)   구조만 (반복) + 의미 미달 → 깨끗
(ii)  구조 + 의미 모두 충족 → 낭비, candidate 토큰/비용 누적
(iii) 깨끗한 트레이스 → wasteful=False
(iv)  같은 candidate 중복 등록 방지
(v)   라벨 인자 시그니처에 없음 (사이드채널 차단)
(vi)  본문에 'labels' 문자열 0개
"""

from __future__ import annotations

import hashlib
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from clew.detect.cascade import CascadeResult, cascade
from clew.detect.semantic import Embedder
from clew.model import Span, Trace


def _ts(o: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=o)


def _span(sid: str, parent: str | None, agent: str, t: int, out: str, tokens: int = 10) -> Span:
    return Span(
        trace_id="t",
        span_id=sid,
        parent_span_id=parent,
        agent_or_node_id=agent,
        span_kind="llm" if parent else "chain",
        start_time=_ts(t),
        end_time=_ts(t + 1),
        input_text="",
        output_text=out,
        token_count=tokens,
        model="fake",
        cost_rate=1e-6,
    )


def _trace(spans: list[Span]) -> Trace:
    return Trace(trace_id="t", spans=spans)


def _fake_compute(self: Embedder, text: str) -> list[float]:
    h = hashlib.sha256(text.encode("utf-8")).digest()[:16]
    return [b / 255.0 for b in h]


@pytest.fixture
def embedder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Embedder:
    monkeypatch.setattr(Embedder, "_compute", _fake_compute)
    return Embedder(model_name="fake", revision="rev-0000", cache_dir=tmp_path)


def test_structure_only_no_semantic_duplicate_is_clean(embedder: Embedder):
    """반복은 있지만 출력이 서로 달라 cos<φ → 낭비 아님."""
    spans = [
        _span("s1", None, "run", 0, "root"),
        _span("s2", "s1", "analyze", 1, "alpha"),
        _span("s3", "s1", "analyze", 2, "beta"),
    ]
    res = cascade(_trace(spans), embedder, n=2, phi=0.95)
    assert res.wasteful is False
    assert res.waste_span_ids == []
    assert res.waste_tokens == 0
    assert res.waste_cost == 0.0


def test_structure_and_semantic_marks_wasteful(embedder: Embedder):
    """반복 + 같은 출력 → cos=1.0 → 낭비. candidate 토큰만 누적."""
    spans = [
        _span("s1", None, "run", 0, "root"),
        _span("s2", "s1", "analyze", 1, "same payload", tokens=20),
        _span("s3", "s1", "analyze", 2, "same payload", tokens=30),
    ]
    res = cascade(_trace(spans), embedder, n=2, phi=0.99)
    assert res.wasteful is True
    assert res.waste_span_ids == ["s3"]
    assert res.waste_tokens == 30
    assert res.waste_cost == pytest.approx(30 * 1e-6)


def test_three_repeats_count_two_candidates(embedder: Embedder):
    spans = [
        _span("s1", None, "run", 0, "root"),
        _span("s2", "s1", "analyze", 1, "x", tokens=10),
        _span("s3", "s1", "analyze", 2, "x", tokens=20),
        _span("s4", "s1", "analyze", 3, "x", tokens=40),
    ]
    res = cascade(_trace(spans), embedder, n=2, phi=0.99)
    assert sorted(res.waste_span_ids) == ["s3", "s4"]
    assert res.waste_tokens == 60


def test_clean_trace(embedder: Embedder):
    spans = [
        _span("s1", None, "run", 0, "root"),
        _span("s2", "s1", "start", 1, "init"),
        _span("s3", "s1", "analyze", 2, "ok"),
        _span("s4", "s1", "report", 3, "done"),
    ]
    res = cascade(_trace(spans), embedder, n=2, phi=0.9)
    assert res.wasteful is False


def test_cascade_signature_has_no_labels_arg():
    sig = inspect.signature(cascade)
    params = sig.parameters
    for forbidden in ("labels", "labels_path", "ground_truth", "gt"):
        assert forbidden not in params, f"cascade exposes label sidechannel: {forbidden}"


def test_cascade_source_does_not_reference_labels():
    src = Path(__file__).parent.parent / "src" / "clew" / "detect" / "cascade.py"
    text = src.read_text(encoding="utf-8")
    assert "labels" not in text
    assert "eval/" not in text


def test_c2_requery_known_positive_is_flagged(embedder: Embedder):
    """CRITERIA C2: requery_known positive (동일 input 재조회) → cascade flag.

    positive 의 두 lookup 출력은 byte-identical → fake _compute(sha256) 에서 cos=1.0
    → φ=0.5 통과 → wasteful=True. recall 회귀 방지.
    """
    from eval.generators.patterns.requery_known import make_positive

    gen = make_positive(trace_id="t-c2", seed=42)
    res = cascade(gen.trace, embedder, n=2, phi=0.5)
    assert res.wasteful is True
    assert res.waste_span_ids != []
    # positive 의 2회차 lookup span_id 가 낭비로 라벨됨
    assert set(res.waste_span_ids) == set(gen.waste_span_ids)
