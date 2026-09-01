# Spec: docs/VERIFICATION_JUDGE_SHIPPING_PREREG.md (Rule 8 prereg).
# Measurement being shipped: docs/VERIFICATION_JUDGE_RESULTS.md (0.9286 / 1.0000)
"""The verification axis as a report section: opt-in, one call, three outcomes.

`verification_judge.py` is the judgement. This is the surface: it decides
whether to ask at all, asks at most once, and returns something a report can
render without deciding anything else.

Three outcomes, and the third is the reason this module exists (prereg §3):

    checked          the session verified its work      -> no finding
    not checked      it did not                         -> a finding
    not judged       we could not tell                  -> neither

"Not judged" covers no API key, a failed call, an unparsable response, and a
session with no editing to judge. **None of them may render as "not checked".**
An axis that reports absence of evidence as evidence of absence earns the fate
of the rule it replaced, which scored 0.3250 by assuming a check it could not
see had not happened.

Nothing here enters a cost figure, a waste rate, `waste_span_count`, or any
stored column.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from clew.detect.llm_judge.semantic_duplicate import DEFAULT_JUDGE_MODEL
from clew.detect.llm_judge.verification_judge import (
    _EDIT_TOOLS,
    CheckedVerdict,
    VerificationJudge,
    render_trace_for_judge,
)
from clew.model import Trace

# Prereg §4. One call per analysed trace, and the axis reads a rendered view
# rather than iterating: there is nothing here that could make a second call.
CALLS_PER_TRACE = 1

ENV_FLAG = "CLEW_ENABLE_VERIFICATION"


@dataclass
class VerificationAxisResult:
    """What the report renders. `finding` is true only when the judge said so.

    `not_judged_reason` is set exactly when no judgement was reached, and it is
    the text the report shows. Both cannot be true at once and a test asserts
    it: the whole point of the type is that "no finding" and "could not tell"
    stay distinguishable all the way to the page.
    """

    enabled: bool = False
    finding: bool = False
    evidence: str = ""
    confidence: float = 0.0
    not_judged_reason: str | None = None
    calls: int = 0
    cost_usd: float = 0.0

    @property
    def judged(self) -> bool:
        return self.enabled and self.not_judged_reason is None


def _resolve_enabled(enabled: bool | None) -> bool:
    """Prereg §2: off unless the flag or the env var says otherwise."""
    if enabled is True:
        return True
    if enabled is False:
        return False
    return os.environ.get(ENV_FLAG) == "1"


def _edits_anything(trace: Trace) -> bool:
    """Whether the session changed a file at all.

    A session that edited nothing has no verification to omit, so asking is
    both a wasted call and a question with no true answer. It is reported as
    not judged rather than as checked -- "there was nothing to check" is not
    the same claim as "it checked".
    """
    return any(
        span.span_kind == "tool" and span.agent_or_node_id in _EDIT_TOOLS
        for span in trace.spans
    )


def find_verification_failure(
    trace: Trace,
    *,
    enabled: bool | None = None,
    judge: VerificationJudge | None = None,
) -> VerificationAxisResult:
    """Ask once whether the session checked what it changed.

    `judge` is injectable for tests. When absent one is constructed lazily, so
    an analysis that never enables the axis never imports the client.
    """
    result = VerificationAxisResult()
    if not _resolve_enabled(enabled):
        return result

    result.enabled = True

    if not _edits_anything(trace):
        result.not_judged_reason = "the session changed no files"
        return result

    if judge is None:
        try:
            # The model is the frozen default the 0.9286 was measured on
            # (prereg §4). It is passed explicitly because the constructor
            # requires it -- the first version of this call omitted it and a
            # run on a real session reported "the judge could not start
            # (missing 1 required positional argument)" as the not-judged
            # reason, which is the right outcome for the wrong cause.
            judge = VerificationJudge(model=DEFAULT_JUDGE_MODEL)
        except Exception as exc:                                   # noqa: BLE001
            # No key, no package, no client. Reported, not raised: prereg §7 P4
            # makes a non-zero exit here a stop condition, because telling
            # someone with no key that they did not verify their work is the
            # failure this axis is built to avoid.
            result.not_judged_reason = f"the judge could not start ({exc})"
            return result

    view = render_trace_for_judge(trace)
    verdict: CheckedVerdict = judge.judge_checked(view)
    result.calls = CALLS_PER_TRACE
    result.cost_usd = verdict.cost_usd

    if verdict.parse_failed:
        # `judge_checked` returns `checked=True` on failure so an API outage
        # cannot manufacture findings. Here that non-finding is reported as
        # what it is rather than as a verdict.
        result.not_judged_reason = "the judge did not answer"
        return result

    result.finding = not verdict.checked
    result.evidence = verdict.evidence
    result.confidence = verdict.confidence
    return result
