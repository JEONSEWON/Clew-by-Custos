"""tests/test_cascade.py — structure AND semantics conjunction + cost accounting.

(i)   structure only (repeat) + semantics below threshold -> clean
(ii)  structure + semantics both satisfied -> waste, accumulate candidate tokens/cost
(iii) clean trace -> wasteful=False
(iv)  prevent duplicate registration of the same candidate
(v)   label argument not in signature (side-channel blocked)
(vi)  zero occurrences of the string 'labels' in the body
"""

from __future__ import annotations

import hashlib
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from clew.detect.cascade import cascade
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
    """Repetition exists but outputs differ -> cos<phi -> not waste."""
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
    """Repetition + identical output -> cos=1.0 -> waste. Only candidate tokens accumulate."""
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
    """CRITERIA C2: requery_known positive (re-lookup with identical input) -> cascade flag.

    Positive's two lookup outputs are byte-identical -> under fake _compute(sha256), cos=1.0
    -> passes phi=0.5 -> wasteful=True. Guards recall regression.
    """
    from eval.generators.patterns.requery_known import make_positive

    gen = make_positive(trace_id="t-c2", seed=42)
    res = cascade(gen.trace, embedder, n=2, phi=0.5)
    assert res.wasteful is True
    assert res.waste_span_ids != []
    # positive's 2nd lookup span_id is labeled as waste
    assert set(res.waste_span_ids) == set(gen.waste_span_ids)


# ─── §22.11.2 compact window gate ────────────────────────────────────────────

def _tool_span(sid: str, parent: str, agent: str, t: int, inp: str, out: str, tokens: int = 10) -> Span:
    return Span(
        trace_id="t",
        span_id=sid,
        parent_span_id=parent,
        agent_or_node_id=agent,
        span_kind="tool",
        start_time=_ts(t),
        end_time=_ts(t + 1),
        input_text=inp,
        output_text=out,
        token_count=tokens,
        model="fake",
        cost_rate=1e-6,
    )


def test_tool_sha256_equal_is_wasteful_without_compact(embedder: Embedder):
    """§22.11.2 control: without a compact boundary, sha256-identical re-lookup is caught."""
    root = _span("root", None, "run", 0, "root")
    spans = [
        root,
        _tool_span("s2", "root", "Read", 1, '{"file_path":"/tmp/a"}', "same output"),
        _tool_span("s3", "root", "Read", 5, '{"file_path":"/tmp/a"}', "same output", tokens=25),
    ]
    trace = Trace(trace_id="t", spans=spans)  # no metadata (other-loader case)
    res = cascade(trace, embedder, n=2, phi=0.99)
    assert res.wasteful is True
    assert res.waste_span_ids == ["s3"]
    assert res.waste_tokens == 25


# ─── absence sentinel (CASCADE_ABSENCE_SENTINEL_AMENDMENT_PREREG §4) ───────

def _absent_tool_span(sid: str, t: int, out: str) -> Span:
    s = _tool_span(sid, "root", "Bash", t, '{"command":"true"}', out)
    return s.model_copy(update={"output_is_absent": True})


def test_absent_output_not_wasteful(embedder: Embedder):
    """Two calls the adapter marked as producing no output are not each other's waste.

    Without the §4 skip these are sha256-identical and land in waste_span_ids: the
    vendor placeholder is non-empty, so model.py's tool-output invariant lets it
    through and the sha256 gate then matches absence against absence.
    """
    spans = [
        _span("root", None, "run", 0, "root"),
        _absent_tool_span("s2", 1, "(Bash completed with no output)"),
        _absent_tool_span("s3", 5, "(Bash completed with no output)"),
    ]
    res = cascade(Trace(trace_id="t", spans=spans), embedder, n=2, phi=0.99)
    assert res.wasteful is False
    assert res.waste_span_ids == []


def test_absent_origin_also_skips(embedder: Embedder):
    """The skip is symmetric: an absent origin cannot make a later span waste.

    Guards the direction a one-sided `candidate.output_is_absent` check would miss.
    """
    absent = _absent_tool_span("s2", 1, "(Bash completed with no output)")
    later = _tool_span("s3", "root", "Bash", 5, '{"command":"true"}',
                       "(Bash completed with no output)", tokens=25)
    spans = [_span("root", None, "run", 0, "root"), absent, later]
    res = cascade(Trace(trace_id="t", spans=spans), embedder, n=2, phi=0.99)
    assert res.wasteful is False
    assert res.waste_span_ids == []


def test_absent_flag_does_not_suppress_real_duplicates(embedder: Embedder):
    """Unmarked spans keep the pre-amendment behaviour — the skip is opt-in per span.

    This is the Corpus B guarantee in miniature: 347 flags there survived because no
    Toolathlon output is a marked sentinel.
    """
    spans = [
        _span("root", None, "run", 0, "root"),
        _tool_span("s2", "root", "send_email", 1, '{"to":"a@b.c"}', "Email sent"),
        _tool_span("s3", "root", "send_email", 5, '{"to":"a@b.c"}', "Email sent", tokens=25),
    ]
    res = cascade(Trace(trace_id="t", spans=spans), embedder, n=2, phi=0.99)
    assert res.wasteful is True
    assert res.waste_span_ids == ["s3"]


def test_output_is_absent_defaults_false():
    """Every other adapter and every stored trace keeps the old behaviour by default."""
    assert _tool_span("s", "root", "Read", 1, "{}", "out").output_is_absent is False


def test_tool_sha256_equal_excluded_when_compact_between(embedder: Embedder):
    """§22.11.2: if a compact boundary is within the origin<->cand window, exclude from waste."""
    root = _span("root", None, "run", 0, "root")
    spans = [
        root,
        _tool_span("s2", "root", "Read", 1, '{"file_path":"/tmp/a"}', "same output"),
        _tool_span("s3", "root", "Read", 5, '{"file_path":"/tmp/a"}', "same output", tokens=25),
    ]
    trace = Trace(
        trace_id="t", spans=spans,
        metadata={"source": "claude_code_jsonl", "compact_boundaries": [_ts(3)]},
    )
    res = cascade(trace, embedder, n=2, phi=0.99)
    assert res.wasteful is False
    assert res.waste_span_ids == []


def test_compact_boundary_before_origin_does_not_exclude(embedder: Embedder):
    """§22.11.2: boundary before origin is outside the window -> do not exclude."""
    root = _span("root", None, "run", 0, "root")
    spans = [
        root,
        _tool_span("s2", "root", "Read", 5, '{"file_path":"/tmp/a"}', "same"),
        _tool_span("s3", "root", "Read", 10, '{"file_path":"/tmp/a"}', "same", tokens=20),
    ]
    trace = Trace(
        trace_id="t", spans=spans,
        metadata={"compact_boundaries": [_ts(2)]},  # before origin(5)
    )
    res = cascade(trace, embedder, n=2, phi=0.99)
    assert res.wasteful is True
    assert res.waste_span_ids == ["s3"]


def test_compact_boundary_after_candidate_does_not_exclude(embedder: Embedder):
    """§22.11.2: boundary after cand is outside the window -> do not exclude."""
    root = _span("root", None, "run", 0, "root")
    spans = [
        root,
        _tool_span("s2", "root", "Read", 1, '{"file_path":"/tmp/a"}', "same"),
        _tool_span("s3", "root", "Read", 5, '{"file_path":"/tmp/a"}', "same", tokens=15),
    ]
    trace = Trace(
        trace_id="t", spans=spans,
        metadata={"compact_boundaries": [_ts(10)]},  # after cand(5)
    )
    res = cascade(trace, embedder, n=2, phi=0.99)
    assert res.wasteful is True
    assert res.waste_span_ids == ["s3"]


def test_compact_gate_no_op_when_metadata_missing(embedder: Embedder):
    """§22.11.2: no-op when the key is missing from Trace.metadata — no impact on other loaders."""
    root = _span("root", None, "run", 0, "root")
    spans = [
        root,
        _tool_span("s2", "root", "Read", 1, '{"file_path":"/tmp/a"}', "same"),
        _tool_span("s3", "root", "Read", 5, '{"file_path":"/tmp/a"}', "same", tokens=12),
    ]
    trace = Trace(trace_id="t", spans=spans, metadata={"source": "otel_json"})
    res = cascade(trace, embedder, n=2, phi=0.99)
    assert res.wasteful is True
    assert res.waste_span_ids == ["s3"]


def test_non_tool_empty_pair_skipped_before_cosine(embedder: Embedder, monkeypatch):
    """R2 relaxation (docs/ADAPTER_R2_RELAXATION_PREREG.md §2.5): the
    non-tool cascade branch must skip an empty-vs-empty pair BEFORE
    invoking the embedder. Two empty llm/chain outputs would otherwise
    hit cosine(embed(""), embed("")) = 1.0 > phi and land a false waste
    flag (the exact KILL scenario the prereg §3.b measured)."""
    root = _span("root", None, "run", 0, "root_out")
    a = _span("s-1", "root", "analyze", 1, "")
    b = _span("s-2", "root", "analyze", 2, "")
    trace = _trace([root, a, b])

    def _explode(self, text):
        raise AssertionError(
            f"embedder called on empty non-tool output — skip missing "
            f"(got text={text!r})"
        )
    monkeypatch.setattr(Embedder, "_compute", _explode)

    result = cascade(trace, embedder, n=2, phi=0.5)
    assert result.wasteful is False
    assert result.waste_span_ids == []


def test_non_tool_empty_vs_value_pair_skipped(embedder: Embedder):
    """R2 relaxation §2.1 widened principle: absence on either side is
    not judgeable. Even though `cosine(embed(''), embed(<text>))` was
    measured under phi (safe by luck, §3.b samples 0.009 ~ 0.315), the
    skip must fire on empty-vs-value too so that the running code matches
    the documented rule ('absence on either side is not judgeable')."""
    root = _span("root", None, "run", 0, "root_out")
    a = _span("s-1", "root", "analyze", 1, "")
    b = _span("s-2", "root", "analyze", 2, "some meaningful output text")
    trace = _trace([root, a, b])
    result = cascade(trace, embedder, n=2, phi=0.5)
    assert result.wasteful is False
    assert result.waste_span_ids == []


def test_non_tool_non_empty_pair_still_evaluated(embedder: Embedder):
    """R2 relaxation must not break normal non-tool cascade — two spans
    with identical non-empty outputs must still be flagged. Guards
    against over-broad skip."""
    root = _span("root", None, "run", 0, "root_out")
    a = _span("s-1", "root", "analyze", 1, "identical output")
    b = _span("s-2", "root", "analyze", 2, "identical output")
    trace = _trace([root, a, b])
    result = cascade(trace, embedder, n=2, phi=0.5)
    assert result.wasteful is True
    assert "s-2" in result.waste_span_ids


def test_compact_gate_does_not_affect_llm_kind(embedder: Embedder):
    """§22.11.2: gate targets tool kind only. llm path keeps phi judgment even with compact present."""
    spans = [
        _span("s1", None, "run", 0, "root"),
        _span("s2", "s1", "analyze", 1, "same payload", tokens=20),
        _span("s3", "s1", "analyze", 5, "same payload", tokens=30),
    ]
    trace = Trace(
        trace_id="t", spans=spans,
        metadata={"compact_boundaries": [_ts(3)]},  # no effect on llm path
    )
    res = cascade(trace, embedder, n=2, phi=0.99)
    assert res.wasteful is True
    assert res.waste_span_ids == ["s3"]
