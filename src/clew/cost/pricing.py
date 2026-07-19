"""Anthropic pricing constants for cost/amplification estimation.

Source: https://docs.anthropic.com/en/docs/about-claude/pricing
        https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
Verified: 2026-07-19 via WebSearch.

Sonnet 4.5 pricing rule of thumb:
- Cache read  = 10% of base input.
- Cache write (5m TTL) = 125% of base input.
- Cache write (1h TTL) = 200% of base input.

CC transcripts carry no model field (sessionId only). Default = Sonnet 4.5.
Caller may pass an explicit model key to override.
"""
from __future__ import annotations

from dataclasses import dataclass

_USD_PER_MTOK = 1_000_000.0


@dataclass(frozen=True)
class ModelPricing:
    name: str
    base_input_per_mtok: float
    cache_read_per_mtok: float
    cache_write_5m_per_mtok: float
    cache_write_1h_per_mtok: float
    output_per_mtok: float

    def base_input_cost(self, tokens: int) -> float:
        return tokens * self.base_input_per_mtok / _USD_PER_MTOK

    def cache_read_cost(self, tokens: int) -> float:
        return tokens * self.cache_read_per_mtok / _USD_PER_MTOK


PRICING: dict[str, ModelPricing] = {
    "sonnet-4.5": ModelPricing(
        name="claude-sonnet-4-5",
        base_input_per_mtok=3.0,
        cache_read_per_mtok=0.30,
        cache_write_5m_per_mtok=3.75,
        cache_write_1h_per_mtok=6.00,
        output_per_mtok=15.0,
    ),
}

DEFAULT_MODEL_KEY = "sonnet-4.5"


def get_pricing(model_key: str | None = None) -> ModelPricing:
    key = model_key or DEFAULT_MODEL_KEY
    if key not in PRICING:
        raise KeyError(
            f"unknown model key {key!r}; known: {sorted(PRICING)}"
        )
    return PRICING[key]
