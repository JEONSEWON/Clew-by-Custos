"""Verification judge axis (VERIFICATION_JUDGE_PREREG §8 step 2).

No API calls. What is tested here is the three things that can be wrong without
the API being involved: the view the judge is shown, the parsing of what it
returns, and the metric that decides whether it passed.

★ The metric test is required by the pre-registration rather than chosen. §5
names the way this axis could look successful while finding nothing: the
labelled set is 13 true and 27 false, so a judge answering `checked: true`
everywhere scores 0.675 on accuracy. §8 says such a judge must be shown
failing, not described as failing.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from clew.detect.llm_judge.verification_judge import (
    CheckedVerdict,
    VerificationJudge,
    precision_recall,
    render_trace_for_judge,
)
from clew.detect.llm_judge.verification_prompts import (
    TOOL_OUTPUT_MAX_CHARS,
    VIEW_MAX_CHARS,
    build_verification_message,
)
from clew.model import Span, Trace

BASE = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def _t(sec: int) -> datetime:
    return BASE + timedelta(seconds=sec)


def _tool(span_id: str, tool: str, payload: dict, sec: int, out: str = "ok") -> Span:
    return Span(
        trace_id="T", span_id=span_id, parent_span_id="root",
        agent_or_node_id=tool, span_kind="tool",
        start_time=_t(sec), end_time=_t(sec + 1),
        input_text=json.dumps(payload, sort_keys=True), output_text=out,
    )


def _trace(spans: list[Span], llm_calls: list[dict] | None = None) -> Trace:
    root = Span(
        trace_id="T", span_id="root", parent_span_id=None,
        agent_or_node_id="root", span_kind="chain",
        start_time=_t(0), end_time=_t(9999), input_text="", output_text="[root]",
    )
    md: dict = {}
    if llm_calls is not None:
        md["llm_calls"] = llm_calls
    return Trace(trace_id="T", spans=[root, *spans], metadata=md)


def _call(messages: list[dict]) -> dict:
    return {"input_text": json.dumps(messages), "span_id": "s", "model": "m"}


# ── the view the judge is shown ────────────────────────────────────────────


def test_actions_appear_in_time_order_not_list_order():
    """Distinguishes reading `trace.spans` as given. Order is the whole
    evidence for "edited, then ran it" versus "ran it, then edited"."""
    view = render_trace_for_judge(_trace([
        _tool("s2", "Bash", {"command": "pytest -q"}, 300),
        _tool("s1", "Edit", {"file_path": "a.py"}, 100),
    ]))
    assert view.index("Edit") < view.index("Bash")


def test_edits_and_commands_are_marked():
    """The judge is told which actions change files and which run things,
    rather than being left to infer it from tool names it has not seen."""
    view = render_trace_for_judge(_trace([
        _tool("s1", "Edit", {"file_path": "a.py"}, 10),
        _tool("s2", "Bash", {"command": "ls"}, 20),
        _tool("s3", "Read", {"file_path": "b.py"}, 30),
    ]))
    assert "changes a file" in view
    assert "runs a command" in view
    # `Read` is neither, and must not be dressed up as either.
    read_line = [ln for ln in view.splitlines() if "ACTION Read" in ln][0]
    assert "changes a file" not in read_line and "runs a command" not in read_line


def test_a_long_tool_output_is_truncated_but_its_command_survives():
    """Distinguishes dropping long outputs entirely. A truncated `pytest`
    output still shows the run happened, which is the whole question."""
    view = render_trace_for_judge(_trace([
        _tool("s1", "Bash", {"command": "pytest -q"}, 10, out="x" * 50_000),
    ]))
    assert "pytest -q" in view
    assert "output truncated" in view
    assert len(view) < 50_000


def test_the_whole_view_is_bounded_and_says_so():
    """Distinguishes a silent cut. The largest labelled candidate is 357 KB,
    and a verdict on a silently dropped tail cannot be reproduced."""
    spans = [_tool(f"s{i}", "Bash", {"command": "echo " + "y" * 500}, i)
             for i in range(600)]
    msg = build_verification_message(render_trace_for_judge(_trace(spans)))
    assert "view truncated here" in msg
    assert len(msg) < VIEW_MAX_CHARS + 2_000


def test_assistant_text_is_recovered_from_accumulated_prompts():
    """The adapter keeps no assistant output text, so the only source is what
    accumulated into later prompts. Lossy, and stated as a limit in the prereg;
    what is tested here is that the lossy path works at all."""
    view = render_trace_for_judge(
        _trace([_tool("s1", "Edit", {"file_path": "a.py"}, 10)],
               llm_calls=[
                   _call([{"role": "user", "content": "fix it"}]),
                   _call([{"role": "user", "content": "fix it"},
                          {"role": "assistant",
                           "content": [{"type": "text",
                                        "text": "I will run the tests next."}]}]),
               ]))
    assert "AGENT SAID: I will run the tests next." in view


def test_a_line_the_agent_said_twice_appears_once():
    """Prompts accumulate, so every earlier turn reappears in every later one.
    Without dedup a twenty-call session repeats its first sentence twenty
    times and the view is mostly echo."""
    said = {"role": "assistant",
            "content": [{"type": "text", "text": "Checking the file now."}]}
    view = render_trace_for_judge(
        _trace([_tool("s1", "Edit", {"file_path": "a.py"}, 10)],
               llm_calls=[_call([said]), _call([said]), _call([said])]))
    assert view.count("Checking the file now.") == 1


def test_empty_thinking_blocks_contribute_nothing():
    """Claude Code stores thinking blocks with empty content: 2,736 of them on
    the author's machine, all zero-length. They are structure without
    evidence."""
    view = render_trace_for_judge(
        _trace([_tool("s1", "Edit", {"file_path": "a.py"}, 10)],
               llm_calls=[_call([
                   {"role": "assistant",
                    "content": [{"type": "thinking", "thinking": "",
                                 "signature": "abc"}]}])]))
    assert "AGENT SAID" not in view


def test_a_prompt_that_will_not_parse_is_skipped_not_fatal():
    view = render_trace_for_judge(
        _trace([_tool("s1", "Edit", {"file_path": "a.py"}, 10)],
               llm_calls=[{"input_text": "{not json", "span_id": "s"}]))
    assert "ACTION Edit" in view


# ── parsing what comes back ────────────────────────────────────────────────


class _Resp:
    def __init__(self, text: str, in_tok: int = 100, out_tok: int = 20) -> None:
        self.content = [type("B", (), {"text": text})()]
        self.usage = type("U", (), {"input_tokens": in_tok,
                                    "output_tokens": out_tok})()


def _judge() -> VerificationJudge:
    """A judge with no client. `_parse_checked` needs only `self.pricing`."""
    j = VerificationJudge.__new__(VerificationJudge)
    from clew.cost.pricing import get_pricing
    j.pricing = get_pricing("claude-haiku-4-5")
    j.model = "claude-haiku-4-5"
    return j


def test_a_finding_parses():
    v = _judge()._parse_checked(_Resp(
        '{"checked": false, "evidence": "no command was run", "confidence": 0.9}'))
    assert v.checked is False
    assert v.evidence == "no command was run"
    assert v.confidence == pytest.approx(0.9)
    assert not v.parse_failed
    assert v.cost_usd > 0


def test_a_fenced_response_parses():
    """Claude models wrap JSON in fences despite the instruction; the
    semantic-duplicate axis needed the same strip."""
    v = _judge()._parse_checked(_Resp(
        '```json\n{"checked": true, "evidence": "ran pytest", '
        '"confidence": 0.8}\n```'))
    assert v.checked is True
    assert not v.parse_failed


@pytest.mark.parametrize("text", [
    "not json at all",
    '{"confidence": 0.9}',                    # no `checked`
    '["checked"]',                            # not an object
    "",
])
def test_an_unusable_response_is_not_a_finding(text):
    """★ Distinguishes failing open. An axis whose errors produce findings
    reports the API's bad day as the agent's mistake, and the finding here is
    `checked: false`, so a parse failure must return True."""
    v = _judge()._parse_checked(_Resp(text))
    assert v.checked is True
    assert v.parse_failed is True


def test_a_parse_failure_still_reports_what_it_cost():
    v = _judge()._parse_checked(_Resp("garbage", in_tok=5_000, out_tok=100))
    assert v.parse_failed
    assert v.input_tokens == 5_000
    assert v.cost_usd > 0


# ── the metric, and the judge that finds nothing ───────────────────────────


LABELS_40 = [True] * 13 + [False] * 27          # the committed label balance


def test_a_judge_that_always_says_checked_finds_nothing_and_fails():
    """★ Required by prereg §8. Answering `checked: true` everywhere scores
    0.675 on accuracy while making zero findings. Precision and recall both
    have to report that as a failure, and accuracy is not returned at all."""
    findings = [False] * 40                     # never says checked: false
    m = precision_recall(LABELS_40, findings)
    assert m["findings"] == 0
    assert m["recall"] == 0.0
    assert m["precision"] == 0.0
    assert m["recall"] < 0.60                   # prereg §6 P2
    assert "accuracy" not in m


def test_a_judge_that_always_finds_scores_the_base_rate():
    """The other degenerate direction: flagging everything gets recall 1.0 and
    precision equal to the label base rate, which is below the gate."""
    m = precision_recall(LABELS_40, [True] * 40)
    assert m["recall"] == 1.0
    assert m["precision"] == pytest.approx(13 / 40)
    assert m["precision"] < 0.70                # prereg §6 P1


def test_a_judge_that_clears_both_gates():
    """Ten of thirteen found, two false alarms: precision 10/12, recall 10/13."""
    findings = [True] * 10 + [False] * 3 + [True] * 2 + [False] * 25
    m = precision_recall(LABELS_40, findings)
    assert m["precision"] == pytest.approx(10 / 12)
    assert m["recall"] == pytest.approx(10 / 13)
    assert m["precision"] >= 0.70 and m["recall"] >= 0.60


def test_mismatched_lengths_are_refused():
    with pytest.raises(ValueError):
        precision_recall([True, False], [True])


def test_the_verdict_carries_evidence_in_both_directions():
    """P4 counts verdicts whose evidence is absent from the trace, which is
    only possible if the field is always populated."""
    for body in ('{"checked": true, "evidence": "ran pytest -q", "confidence": 1}',
                 '{"checked": false, "evidence": "only ls was run", "confidence": 1}'):
        v = _judge()._parse_checked(_Resp(body))
        assert v.evidence
        assert isinstance(v, CheckedVerdict)


def test_the_output_cap_leaves_room_for_evidence():
    """Distinguishes reusing the 256-token cap of the other axis. This verdict
    quotes a command verbatim, and a truncated response is a parse failure."""
    import inspect
    src = inspect.getsource(VerificationJudge.judge_checked)
    assert "max_tokens=512" in src
