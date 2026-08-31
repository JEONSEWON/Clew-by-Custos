"""tests/detect/test_llm_judge_anthropic_parser.py

Unit tests for `AnthropicJudge._parse_response`. Focuses on response-shape
tolerance: bare JSON, markdown-fenced JSON, and unparseable text.

Motivation: real Haiku 4.5 responses in the 2026-08-06 Go/No-go run wrapped
JSON in ```json ... ``` fences on 100% of calls, causing every verdict to
be discarded as parse_failed. The parser now strips fences before json.loads.
"""
from __future__ import annotations

from dataclasses import dataclass

from clew.detect.llm_judge.anthropic_client import AnthropicJudge


@dataclass
class _FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 20


@dataclass
class _FakeBlock:
    text: str


@dataclass
class _FakeResponse:
    content: list[_FakeBlock]
    usage: _FakeUsage


def _judge_no_client() -> AnthropicJudge:
    """Construct a judge instance without calling __init__ (skips API key
    validation). We only exercise the pure parser method."""
    judge = AnthropicJudge.__new__(AnthropicJudge)
    judge.model = "claude-haiku-4-5"
    from clew.cost.pricing import get_pricing
    judge.pricing = get_pricing("claude-haiku-4-5")
    return judge


def _resp(text: str) -> _FakeResponse:
    return _FakeResponse(
        content=[_FakeBlock(text=text)],
        usage=_FakeUsage(),
    )


def test_bare_json_parses():
    judge = _judge_no_client()
    verdict = judge._parse_response(_resp(
        '{"equivalent": true, "confidence": 0.95, "reasoning": "same"}'
    ))
    assert verdict.equivalent is True
    assert verdict.confidence == 0.95
    assert verdict.parse_failed is False


def test_markdown_fenced_json_parses():
    """Real Haiku 4.5 responses wrap JSON in ```json ... ```."""
    judge = _judge_no_client()
    fenced = (
        "```json\n"
        '{\n'
        '  "equivalent": true,\n'
        '  "confidence": 0.95,\n'
        '  "reasoning": "Both chunks contain identical Python code"\n'
        '}\n'
        "```"
    )
    verdict = judge._parse_response(_resp(fenced))
    assert verdict.equivalent is True
    assert verdict.confidence == 0.95
    assert verdict.parse_failed is False
    assert "identical Python code" in verdict.reasoning


def test_markdown_fenced_no_language_tag():
    """``` without `json` language tag also unwrapped."""
    judge = _judge_no_client()
    fenced = (
        "```\n"
        '{"equivalent": false, "confidence": 0.99, "reasoning": "diff"}\n'
        "```"
    )
    verdict = judge._parse_response(_resp(fenced))
    assert verdict.equivalent is False
    assert verdict.parse_failed is False


def test_fence_with_trailing_whitespace():
    judge = _judge_no_client()
    fenced = (
        "  ```json\n"
        '{"equivalent": true, "confidence": 0.9, "reasoning": "x"}\n'
        "```  \n"
    )
    verdict = judge._parse_response(_resp(fenced))
    assert verdict.equivalent is True
    assert verdict.parse_failed is False


def test_unparseable_text_still_flags_parse_failed():
    """Non-JSON, non-fenced text remains a parse failure."""
    judge = _judge_no_client()
    verdict = judge._parse_response(_resp("this is not json at all"))
    assert verdict.parse_failed is True
    assert verdict.equivalent is False


def test_fenced_but_body_still_invalid():
    """Fence stripped, but inner content still not valid JSON → parse_failed."""
    judge = _judge_no_client()
    fenced = "```json\nnot really json\n```"
    verdict = judge._parse_response(_resp(fenced))
    assert verdict.parse_failed is True
    assert verdict.equivalent is False
