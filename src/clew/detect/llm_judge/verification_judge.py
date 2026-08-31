# Spec: docs/VERIFICATION_JUDGE_PREREG.md (Rule 8 prereg).
# Results of the killed first attempt: docs/VERIFICATION_FAILURE_DETECTOR_RESULTS.md
"""Verification axis of the LLM judge: did the agent check what it changed?

FM-3.2 of the public taxonomy, second attempt. The first attempt was a
structural rule that reached precision 0.3250 hand-labelled against a
pre-registered 0.70 and was killed; see the results document named in the
module header comment. That rule survives as a candidate generator under
`field_test/diagnostics/`, and this module is the confirmation stage, the same
shape the cascade already uses.

Paths to the repository's own documents stay in `#` comments, never in a
docstring: a pip-installed user has no `docs/` tree, and a guard in the test
suite enforces that for every string literal under `src/`.

Nothing here enters a cost figure, `waste_span_count`, either waste rate, or any
stored column. Prereg §4.
"""
from __future__ import annotations

import json
import logging
import time
import warnings
from dataclasses import dataclass
from typing import Any

from clew.detect.llm_judge.anthropic_client import (
    BACKOFF_INITIAL_SECONDS,
    BACKOFF_MAX_SECONDS,
    AnthropicJudge,
)
from clew.detect.llm_judge.verification_prompts import (
    SYSTEM_PROMPT,
    TOOL_OUTPUT_MAX_CHARS,
    build_verification_message,
)
from clew.model import Trace

logger = logging.getLogger(__name__)

# Tool names that change a file, and the shells. Same sets the killed
# structural rule used, imported by value rather than from diagnostics: `src/`
# does not import from `field_test/`, and the rule is not shipping.
_EDIT_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})
_SHELL_TOOLS = frozenset({"Bash", "PowerShell"})


@dataclass
class CheckedVerdict:
    """One judgement about one session.

    `checked=False` is the finding. `evidence` is required in both directions
    and exists so a wrong verdict can be read afterwards; prereg §6 P4 counts
    verdicts whose evidence is absent from the trace, and any such verdict is an
    immediate stop.
    """

    checked: bool
    evidence: str
    confidence: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    parse_failed: bool = False


def render_trace_for_judge(trace: Trace) -> str:
    """The session as the judge sees it (prereg §2).

    Tool calls in order as `tool name + input`, tool outputs truncated, and the
    assistant's own text blocks.

    ★ On Claude Code traces the assistant text is lossy and the
    pre-registration says so rather than fixing it here. The adapter keeps no
    assistant output text at all -- only `output_tokens` -- so what is available
    is what accumulated into later prompts in `metadata["llm_calls"]`, which
    measured at about one surviving text block per twenty tool calls. Touching
    the adapter would touch the layer every published measurement sits on, and
    that is not done for an axis whose precision is unknown.
    """
    lines: list[str] = []

    for text in _assistant_texts(trace):
        lines.append(f"AGENT SAID: {text}")

    for span in sorted(
        (s for s in trace.spans if s.span_kind == "tool"),
        key=lambda s: s.start_time,
    ):
        tool = span.agent_or_node_id
        marker = ""
        if tool in _EDIT_TOOLS:
            marker = "  <- changes a file"
        elif tool in _SHELL_TOOLS:
            marker = "  <- runs a command"
        lines.append(f"\nACTION {tool}{marker}\n  input: {span.input_text}")
        out = span.output_text or ""
        if len(out) > TOOL_OUTPUT_MAX_CHARS:
            out = out[:TOOL_OUTPUT_MAX_CHARS] + " …[output truncated]"
        lines.append(f"  output: {out}")

    return "\n".join(lines)


def _assistant_texts(trace: Trace) -> list[str]:
    """Assistant text blocks recovered from accumulated prompts, in order.

    Prompts accumulate, so the same block appears in every later call. Ordered
    by first appearance and deduplicated; a block seen twice is one thing the
    agent said, not two.
    """
    seen: dict[str, None] = {}
    for call in trace.metadata.get("llm_calls") or []:
        raw = call.get("input_text")
        if not isinstance(raw, str):
            continue
        try:
            messages = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(messages, list):
            continue
        for message in messages:
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            content = message.get("content")
            if isinstance(content, str):
                if content.strip():
                    seen.setdefault(content.strip(), None)
                continue
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = (block.get("text") or "").strip()
                    if text:
                        seen.setdefault(text, None)
    return list(seen)


class VerificationJudge(AnthropicJudge):
    """The verification axis, on the existing client.

    Subclassed rather than added to `AnthropicJudge.judge`, and its retry loop
    is repeated rather than extracted into a shared helper. Both choices are
    deliberate: the semantic-duplicate axis is a frozen rubric with published
    results, and refactoring the method that serves it to make room for a
    second axis puts those results at risk for no measurement gain. The
    constructor is reused, so the package check, key resolution, pricing table
    and timeout are shared.
    """

    def judge_checked(self, session_view: str) -> CheckedVerdict:
        """One call. Retries on 429; any other error is a parse failure.

        A failed call returns `checked=True` -- the non-finding. An axis whose
        errors produce findings would report the API's bad day as the agent's.
        """
        user_msg = build_verification_message(session_view)

        backoff = BACKOFF_INITIAL_SECONDS
        while True:
            try:
                response = self._client.messages.create(
                    model=self.model,
                    max_tokens=512,
                    temperature=0.0,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_msg}],
                )
                break
            except Exception as e:  # noqa: BLE001
                status = getattr(e, "status_code", None)
                if status == 429 and backoff <= BACKOFF_MAX_SECONDS:
                    logger.warning(
                        "boxdawn verification judge: 429, backing off %ss", backoff,
                    )
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                warnings.warn(
                    f"boxdawn verification judge: call failed "
                    f"({type(e).__name__}: {e}); counting as no finding",
                    stacklevel=2,
                )
                return CheckedVerdict(
                    checked=True, evidence="(judge call failed)", confidence=0.0,
                    input_tokens=0, output_tokens=0, cost_usd=0.0,
                    parse_failed=True,
                )

        return self._parse_checked(response)

    def _parse_checked(self, response: Any) -> CheckedVerdict:
        try:
            text = response.content[0].text
        except (AttributeError, IndexError, TypeError):
            text = ""

        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        cost = (
            input_tokens * self.pricing.base_input_per_mtok
            + output_tokens * self.pricing.output_per_mtok
        ) / 1_000_000.0

        cleaned = _strip_fence(text.strip())
        try:
            body = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            warnings.warn(
                "boxdawn verification judge: response was not JSON; "
                "counting as no finding",
                stacklevel=2,
            )
            return CheckedVerdict(
                checked=True, evidence="(unparseable response)", confidence=0.0,
                input_tokens=input_tokens, output_tokens=output_tokens,
                cost_usd=cost, parse_failed=True,
            )

        if not isinstance(body, dict) or "checked" not in body:
            warnings.warn(
                "boxdawn verification judge: response lacked `checked`; "
                "counting as no finding",
                stacklevel=2,
            )
            return CheckedVerdict(
                checked=True, evidence="(missing `checked`)", confidence=0.0,
                input_tokens=input_tokens, output_tokens=output_tokens,
                cost_usd=cost, parse_failed=True,
            )

        return CheckedVerdict(
            checked=bool(body.get("checked")),
            evidence=str(body.get("evidence") or ""),
            confidence=float(body.get("confidence") or 0.0),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )


def _strip_fence(text: str) -> str:
    """Remove a markdown code fence. Claude models add them despite the
    instruction, and the semantic-duplicate axis needed the same strip."""
    if not text.startswith("```"):
        return text
    lines = text.split("\n")
    if len(lines) < 2:
        return text
    lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)


def precision_recall(labels: list[bool], findings: list[bool]) -> dict[str, float]:
    """Precision and recall of the finding, against hand labels.

    `labels[i]` is True when the session really did not check. `findings[i]` is
    True when the judge said `checked: false`.

    Here rather than in a diagnostics script because prereg §5 names a specific
    way this axis could look successful while finding nothing: the labelled set
    is 13 true and 27 false, so a judge answering `checked: true` for everything
    scores 0.675 on accuracy. §8 requires that such a judge be *shown* failing,
    which needs the metric to be testable. Accuracy is not returned at all.
    """
    if len(labels) != len(findings):
        raise ValueError("labels and findings must be the same length")
    tp = sum(1 for lab, f in zip(labels, findings) if lab and f)
    fp = sum(1 for lab, f in zip(labels, findings) if not lab and f)
    positives = sum(1 for lab in labels if lab)
    return {
        "precision": tp / (tp + fp) if (tp + fp) else 0.0,
        "recall": tp / positives if positives else 0.0,
        "true_positives": float(tp),
        "false_positives": float(fp),
        "findings": float(tp + fp),
        "labelled_positives": float(positives),
    }
