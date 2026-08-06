# Spec: docs/LLM_JUDGE_SEMANTIC_DUPLICATE_PREREG.md §3, §8 (frozen).
"""Anthropic API client for the LLM judge — thin wrapper.

Prereg §3: temperature=0, no streaming, pinned model string.
Prereg §8: 30s per-call timeout, exponential backoff on 429.

The `anthropic` package is an OPTIONAL dependency (`clew-custos[judge]`).
Import happens lazily inside the client so the base package works
without it. Missing package → graceful degradation (returns no matches
with a warning, does not raise).
"""
from __future__ import annotations

import json
import logging
import os
import time
import warnings
from dataclasses import dataclass
from typing import Any

from clew.cost.pricing import get_pricing
from clew.detect.llm_judge.prompts import (
    SYSTEM_PROMPT,
    build_user_message,
)


logger = logging.getLogger(__name__)


PER_CALL_TIMEOUT_SECONDS = 30  # prereg §8 frozen
BACKOFF_INITIAL_SECONDS = 1
BACKOFF_MAX_SECONDS = 32


@dataclass
class JudgeVerdict:
    """Structured output of a single judge call.

    `parse_failed` = True when the model response could not be parsed as
    the expected JSON shape. In that case the pair counts as non-match
    (prereg §4).
    """
    equivalent: bool
    confidence: float
    reasoning: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    parse_failed: bool = False


class JudgeUnavailableError(RuntimeError):
    """Raised only by the caller when the client cannot be constructed
    (missing API key or missing package). The detector catches this
    and degrades to an empty result."""


class AnthropicJudge:
    """Anthropic API caller for the LLM judge.

    Constructor validates presence of the `anthropic` package and the
    API key. Judge calls are single-shot with retries; timeout and
    backoff parameters are prereg-frozen (see prereg §8).
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
    ) -> None:
        try:
            import anthropic  # noqa: PLC0415
        except ImportError as e:
            raise JudgeUnavailableError(
                "clew: LLM judge requires `anthropic` package. "
                "Install via `pip install clew-custos[judge]` or "
                "`pip install anthropic`."
            ) from e

        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise JudgeUnavailableError(
                "clew: LLM judge requires ANTHROPIC_API_KEY env var "
                "(or explicit api_key argument)."
            )

        self.model = model
        self.pricing = get_pricing(model)
        self._client = anthropic.Anthropic(
            api_key=resolved_key,
            timeout=PER_CALL_TIMEOUT_SECONDS,
        )

    def judge(self, chunk_a: str, chunk_b: str) -> JudgeVerdict:
        """Single judge call. Retries on 429 with exponential backoff.

        Any other error → returns a non-match verdict with parse_failed=True
        so the detector can continue (prereg §8: timeout / error → warn
        + count as non-match + continue).
        """
        user_msg = build_user_message(chunk_a, chunk_b)

        backoff = BACKOFF_INITIAL_SECONDS
        while True:
            try:
                response = self._client.messages.create(
                    model=self.model,
                    max_tokens=256,
                    temperature=0.0,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_msg}],
                )
                break
            except Exception as e:  # noqa: BLE001
                # anthropic exception types are optional-import; use
                # duck-typing on status_code for 429 handling.
                status = getattr(e, "status_code", None)
                if status == 429 and backoff <= BACKOFF_MAX_SECONDS:
                    logger.warning(
                        "clew judge: 429 rate-limited, backing off %ss", backoff,
                    )
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                warnings.warn(
                    f"clew judge: API call failed ({type(e).__name__}: {e}); "
                    "counting as non-match",
                    stacklevel=2,
                )
                return JudgeVerdict(
                    equivalent=False,
                    confidence=0.0,
                    reasoning="(judge call failed)",
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=0.0,
                    parse_failed=True,
                )

        return self._parse_response(response)

    def _parse_response(self, response: Any) -> JudgeVerdict:
        # Extract text content from Anthropic response shape.
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

        # Parse JSON body. Prereg §4: parse failure = non-match + warn.
        try:
            body = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            warnings.warn(
                f"clew judge: response was not valid JSON (first 200 chars: "
                f"{text[:200]!r}); counting as non-match",
                stacklevel=2,
            )
            return JudgeVerdict(
                equivalent=False,
                confidence=0.0,
                reasoning="(response not JSON)",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
                parse_failed=True,
            )

        equivalent = bool(body.get("equivalent", False))

        raw_conf = body.get("confidence", 0.0)
        try:
            confidence = float(raw_conf)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))  # clamp per prereg §4

        reasoning = body.get("reasoning") or ""
        if not isinstance(reasoning, str):
            reasoning = str(reasoning)

        # `equivalent` field missing entirely → treat as non-match (prereg §4).
        if "equivalent" not in body:
            equivalent = False
            confidence = 0.0

        return JudgeVerdict(
            equivalent=equivalent,
            confidence=confidence,
            reasoning=reasoning,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            parse_failed=False,
        )
