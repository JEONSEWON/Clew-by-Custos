"""The three outcomes, and the caps that keep the third one honest.

`docs/VERIFICATION_JUDGE_SHIPPING_PREREG.md` §3 and §4. Every assertion here is
a frozen position: a failure means the code and the prereg disagree.

The one that matters most is §7 P4 — "not judged" must never render as "not
verified". The rule this axis replaced scored 0.3250 precisely by treating a
check it could not see as a check that had not happened, and the same collapse
in the presentation layer would waste the 0.9286 that replaced it.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from clew.detect.llm_judge.verification_axis import (
    CALLS_PER_TRACE,
    ENV_FLAG,
    VerificationAxisResult,
    find_verification_failure,
)
from clew.detect.llm_judge.verification_judge import CheckedVerdict
from clew.model import Span, Trace
from clew.report.json_report import render_json
from clew.report.markdown import render_markdown

T0 = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)


class _StubJudge:
    """Counts calls, so §4's cap is measured rather than assumed."""

    def __init__(self, verdict: CheckedVerdict) -> None:
        self.verdict = verdict
        self.calls = 0

    def judge_checked(self, session_view: str) -> CheckedVerdict:
        self.calls += 1
        return self.verdict


def _verdict(checked: bool, *, parse_failed: bool = False) -> CheckedVerdict:
    return CheckedVerdict(
        checked=checked,
        evidence="ACTION Bash  input: pytest -q" if checked else "no check appears",
        confidence=0.9,
        input_tokens=1000,
        output_tokens=50,
        cost_usd=0.0046,
        parse_failed=parse_failed,
    )


def _span(sid, node, minute, kind="tool"):
    return Span(
        trace_id="t", span_id=sid, parent_span_id="root", agent_or_node_id=node,
        span_kind=kind, start_time=T0 + timedelta(minutes=minute),
        end_time=T0 + timedelta(minutes=minute, seconds=1),
        input_text="{}", output_text="ok",
    )


def _trace(spans):
    root = Span(
        trace_id="t", span_id="root", parent_span_id=None, agent_or_node_id="main",
        span_kind="agent", start_time=T0, end_time=T0 + timedelta(hours=1),
        input_text="", output_text="done",
    )
    return Trace(trace_id="t", spans=[root, *spans], metadata={})


def _edited():
    return _trace([_span("a", "Edit", 1), _span("b", "Read", 2)])


# ── §2: off unless asked ───────────────────────────────────────────────────

def test_off_by_default(monkeypatch):
    monkeypatch.delenv(ENV_FLAG, raising=False)
    judge = _StubJudge(_verdict(False))
    result = find_verification_failure(_edited(), judge=judge)
    assert result.enabled is False
    assert judge.calls == 0


def test_the_env_var_turns_it_on(monkeypatch):
    monkeypatch.setenv(ENV_FLAG, "1")
    judge = _StubJudge(_verdict(True))
    assert find_verification_failure(_edited(), judge=judge).enabled is True


def test_an_explicit_false_beats_the_env_var(monkeypatch):
    monkeypatch.setenv(ENV_FLAG, "1")
    judge = _StubJudge(_verdict(False))
    assert find_verification_failure(_edited(), enabled=False, judge=judge).enabled is False
    assert judge.calls == 0


# ── §3: three outcomes, and they stay three ────────────────────────────────

def test_a_session_that_checked_produces_no_finding():
    judge = _StubJudge(_verdict(True))
    result = find_verification_failure(_edited(), enabled=True, judge=judge)
    assert result.judged is True
    assert result.finding is False
    assert result.not_judged_reason is None


def test_a_session_that_did_not_check_produces_a_finding():
    judge = _StubJudge(_verdict(False))
    result = find_verification_failure(_edited(), enabled=True, judge=judge)
    assert result.judged is True
    assert result.finding is True
    assert result.evidence


@pytest.mark.parametrize("build,reason_fragment", [
    (lambda: _trace([_span("a", "Read", 1)]), "changed no files"),
    (lambda: _edited(), "did not answer"),
])
def test_not_judged_is_never_a_finding(build, reason_fragment):
    """The third outcome. `judge_checked` returns `checked=True` on failure so
    an outage cannot manufacture findings; this asserts the axis reports that
    as "could not tell" rather than passing the non-finding off as a verdict."""
    judge = _StubJudge(_verdict(True, parse_failed=True))
    result = find_verification_failure(build(), enabled=True, judge=judge)
    assert result.judged is False
    assert result.finding is False
    assert reason_fragment in result.not_judged_reason


def test_judged_and_not_judged_are_mutually_exclusive():
    """The invariant the type exists to hold: no state is both."""
    for result in (
        VerificationAxisResult(enabled=True, finding=True),
        VerificationAxisResult(enabled=True, finding=False),
        VerificationAxisResult(enabled=True, not_judged_reason="x"),
        VerificationAxisResult(),
    ):
        assert result.judged is not (result.not_judged_reason is not None
                                     or not result.enabled)


def test_a_judge_that_cannot_start_is_not_judged_rather_than_a_crash(monkeypatch):
    """§7 P4 is a stop condition: telling somebody with no API key that they
    did not verify their work is the failure this axis is built to avoid."""
    import clew.detect.llm_judge.verification_axis as axis

    def no_key(*a, **k):
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    monkeypatch.setattr(axis, "VerificationJudge", no_key)
    result = find_verification_failure(_edited(), enabled=True)
    assert result.judged is False
    assert result.finding is False
    assert "could not start" in result.not_judged_reason


# ── §4: exactly one call ───────────────────────────────────────────────────

def test_exactly_one_call_per_trace():
    judge = _StubJudge(_verdict(False))
    result = find_verification_failure(
        _trace([_span(f"s{i}", "Edit", i) for i in range(12)]),
        enabled=True, judge=judge,
    )
    assert judge.calls == CALLS_PER_TRACE == 1
    assert result.calls == 1


def test_no_call_when_nothing_was_edited():
    judge = _StubJudge(_verdict(False))
    find_verification_failure(_trace([_span("a", "Grep", 1)]), enabled=True, judge=judge)
    assert judge.calls == 0


# ── the shipped artifact: what the report actually prints ──────────────────

def _report(verification):
    from clew.detect.cascade import CascadeResult

    return render_markdown(
        _edited(), CascadeResult(trace_id="t", wasteful=False), [],
        verification=verification,
    )


def test_the_report_never_says_not_verified_when_it_could_not_tell():
    """Asserted on the rendered markdown, not on the dataclass. The collapse
    this guards against would happen in the renderer, not in the type."""
    md = _report(VerificationAxisResult(
        enabled=True, not_judged_reason="the judge did not answer"))
    assert "not judged" in md
    assert "did not answer" in md
    for forbidden in ("changed code and no check", "not verified", "⚠"):
        assert forbidden not in md


def test_the_report_states_the_finding_when_there_is_one():
    md = _report(VerificationAxisResult(
        enabled=True, finding=True, evidence="no check appears", confidence=0.9))
    assert "no check of it appears in the trace" in md
    assert "no check appears" in md
    # Both figures, and which view each belongs to. A guard that asks only for
    # "0.9286" goes green when the other half is dropped, and 0.9286 alone
    # describes a view the product stopped using when the request was added
    # (JUDGE_VIEW_USER_TURN_AMENDMENT_RESULTS §5). A guard that asks only for
    # "1.0000" is worse: it is a ceiling number on n=40 that this project has
    # said in writing must not be read as an improvement.
    for required in ("0.9286", "1.0000", "without the request", "with it"):
        assert required in md, (
            "the verification note has to name both measured figures and the "
            "view each belongs to; missing " + repr(required)
        )
    assert "unchanged" in md, (
        "one session apart is not an improvement, and the note has to say so "
        "rather than leaving a reader to compare the two numbers"
    )


def test_the_report_is_silent_when_the_axis_passed_or_was_off():
    for result in (VerificationAxisResult(enabled=True, finding=False),
                   VerificationAxisResult(),
                   None):
        assert "## Verification" not in _report(result)


def test_the_badge_sits_above_the_lists():
    """A session-level verdict answers "is something wrong here" and the lists
    answer "what specifically". Somebody scanning the page asks the first."""
    md = _report(VerificationAxisResult(enabled=True, finding=True, evidence="x"))
    assert "## Verification" in md
    assert md.index("## Verification") < md.index("## Result")


def test_json_keeps_the_three_outcomes_apart():
    """Separate keys rather than one status string: a consumer must not be
    able to read "could not tell" as "no"."""
    from clew.detect.cascade import CascadeResult

    def block(verification):
        return json.loads(render_json(
            _edited(), CascadeResult(trace_id="t", wasteful=False), [],
            verification=verification,
        ))["verification"]

    assert block(None) == {"enabled": False}

    unjudged = block(VerificationAxisResult(enabled=True, not_judged_reason="no key"))
    assert unjudged["judged"] is False
    assert unjudged["finding"] is None          # not False
    assert unjudged["not_judged_reason"] == "no key"

    found = block(VerificationAxisResult(enabled=True, finding=True, evidence="e"))
    assert found["judged"] is True and found["finding"] is True

    clean = block(VerificationAxisResult(enabled=True, finding=False))
    assert clean["judged"] is True and clean["finding"] is False


def test_the_axis_enters_no_cost_figure():
    """§5: it adds a section and contributes to no metric."""
    from clew.detect.cascade import CascadeResult

    args = (_edited(), CascadeResult(trace_id="t", wasteful=False), [])
    without = render_json(*args)
    with_axis = render_json(*args, verification=VerificationAxisResult(
        enabled=True, finding=True, evidence="e", cost_usd=0.0046))

    a, b = json.loads(without), json.loads(with_axis)
    a.pop("verification", None)
    b.pop("verification", None)
    assert a == b
