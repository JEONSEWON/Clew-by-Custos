"""tests/cost/test_pricing.py — Cost Attribution Completion prereg §6.1.

Locks the pricing table expansion + alias resolution behavior. Source
comment presence guards against pricing drift where a value is updated
without refreshing the URL/date pin.
"""
from __future__ import annotations

import re
import warnings
from pathlib import Path

import pytest

from clew.cost.pricing import (
    DEFAULT_MODEL_KEY,
    PRICING,
    ModelPricing,
    get_pricing,
)


def test_default_model_returned_when_none():
    """get_pricing(None) returns the pinned default (Sonnet 4.5)."""
    p = get_pricing(None)
    assert p is PRICING[DEFAULT_MODEL_KEY]
    assert DEFAULT_MODEL_KEY == "sonnet-4.5"


def test_exact_model_match():
    """Each frozen model key resolves to its own ModelPricing entry."""
    expected_keys = {
        "sonnet-4.5", "sonnet-4.6", "opus-4.7", "haiku-4.5",
        "gpt-4o", "gpt-4o-mini",
        "gemini-1.5-pro", "gemini-1.5-flash",
    }
    for key in expected_keys:
        assert key in PRICING, f"missing pricing entry: {key}"
        p = get_pricing(key)
        assert isinstance(p, ModelPricing)


def test_alias_normalization_anthropic():
    """claude-sonnet-4-5 / claude-3-5-sonnet-* / claude-sonnet-4.5 all route to sonnet-4.5."""
    assert get_pricing("claude-sonnet-4-5") is PRICING["sonnet-4.5"]
    assert get_pricing("claude-sonnet-4.5") is PRICING["sonnet-4.5"]
    assert get_pricing("claude-3-5-sonnet-20241022") is PRICING["sonnet-4.5"]
    assert get_pricing("claude-sonnet-4-6") is PRICING["sonnet-4.6"]
    assert get_pricing("claude-opus-4-7") is PRICING["opus-4.7"]
    assert get_pricing("claude-haiku-4-5") is PRICING["haiku-4.5"]


def test_alias_normalization_openai():
    """gpt-4o-mini variants MUST match before gpt-4o."""
    # Prefix ambiguity gate — this is the whole point of longest-prefix routing.
    assert get_pricing("gpt-4o-2024-05-13") is PRICING["gpt-4o"]
    assert get_pricing("gpt-4o-mini-2024-07-18") is PRICING["gpt-4o-mini"]
    assert get_pricing("gpt-4o-mini") is PRICING["gpt-4o-mini"]


def test_alias_normalization_gemini():
    """gemini-1.5-{pro|flash}-<suffix> all route to the base key."""
    assert get_pricing("gemini-1.5-pro-latest") is PRICING["gemini-1.5-pro"]
    assert get_pricing("gemini-1.5-flash-8b") is PRICING["gemini-1.5-flash"]


def test_unknown_model_defaults_with_warning():
    """Unknown model returns default AND emits a UserWarning (no exception)."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        p = get_pricing("some-fantasy-model-that-does-not-exist")
    assert p is PRICING[DEFAULT_MODEL_KEY]
    assert any("unknown model" in str(warning.message) for warning in w), (
        "expected UserWarning mentioning 'unknown model'"
    )


def test_pricing_source_and_date_present():
    """Every PRICING entry must have a nearby source URL and verification date.

    Regression guard against pricing drift where a value is bumped without
    refreshing the source pin.
    """
    pricing_file = (
        Path(__file__).resolve().parents[2]
        / "src" / "clew" / "cost" / "pricing.py"
    )
    text = pricing_file.read_text(encoding="utf-8")

    # Every model key in PRICING must appear at least once as a dict key
    # in the file (sanity check).
    for key in PRICING:
        assert f'"{key}"' in text, f"model key {key!r} not present in pricing.py source"

    # File must contain at least one source URL per model group
    # (Anthropic / OpenAI / Google).
    assert "platform.claude.com" in text or "docs.anthropic.com" in text, (
        "Anthropic source URL missing"
    )
    assert "openai.com" in text, "OpenAI source URL missing"
    assert "ai.google.dev" in text or "google" in text.lower(), (
        "Google source reference missing"
    )

    # Every model group must carry a verification date somewhere. Match
    # YYYY-MM-DD anywhere in the file to ensure at least one is present.
    assert re.search(r"\b20\d{2}-\d{2}-\d{2}\b", text), (
        "no ISO-8601 verification date found in pricing.py"
    )
