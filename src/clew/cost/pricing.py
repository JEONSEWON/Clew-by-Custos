# Pricing tables — sources pinned per entry (URL + verification date).
"""Provider pricing constants for cost attribution.

Cache tier semantics (Anthropic-native, other providers approximated):
- base_input      — uncached input tokens
- cache_read      — cache hit (10% of base for Anthropic; provider-specific)
- cache_write_5m  — cache creation, 5-minute TTL (125% of base for Anthropic)
- cache_write_1h  — cache creation, 1-hour TTL (200% of base for Anthropic)
- output          — output tokens

Non-Anthropic providers: 5m/1h collapse when a provider does not price cache
writes separately (in that case both write columns equal base_input).

Model resolution (`get_pricing`): exact key → alias table → soft-fail default
(warning + Sonnet 4.5). Never raises for unknown model — always returns a
best-effort pricing so cost figures degrade gracefully.
"""
from __future__ import annotations

import warnings
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

    def cache_write_5m_cost(self, tokens: int) -> float:
        return tokens * self.cache_write_5m_per_mtok / _USD_PER_MTOK

    def cache_write_1h_cost(self, tokens: int) -> float:
        return tokens * self.cache_write_1h_per_mtok / _USD_PER_MTOK

    def output_cost(self, tokens: int) -> float:
        return tokens * self.output_per_mtok / _USD_PER_MTOK


PRICING: dict[str, ModelPricing] = {
    # ── Anthropic ─────────────────────────────────────────────────────────
    # Source: https://platform.claude.com/docs/en/docs/about-claude/pricing
    # Verified: 2026-08-05
    "sonnet-4.5": ModelPricing(
        name="claude-sonnet-4-5",
        base_input_per_mtok=3.0,
        cache_read_per_mtok=0.30,
        cache_write_5m_per_mtok=3.75,
        cache_write_1h_per_mtok=6.00,
        output_per_mtok=15.0,
    ),
    "sonnet-4.6": ModelPricing(
        # Source: https://platform.claude.com/docs/en/docs/about-claude/pricing
        # Verified: 2026-08-05
        name="claude-sonnet-4-6",
        base_input_per_mtok=3.0,
        cache_read_per_mtok=0.30,
        cache_write_5m_per_mtok=3.75,
        cache_write_1h_per_mtok=6.00,
        output_per_mtok=15.0,
    ),
    "opus-4.7": ModelPricing(
        # Source: https://platform.claude.com/docs/en/docs/about-claude/pricing
        # Verified: 2026-08-05
        name="claude-opus-4-7",
        base_input_per_mtok=5.0,
        cache_read_per_mtok=0.50,
        cache_write_5m_per_mtok=6.25,
        cache_write_1h_per_mtok=10.0,
        output_per_mtok=25.0,
    ),
    "haiku-4.5": ModelPricing(
        # Source: https://platform.claude.com/docs/en/docs/about-claude/pricing
        # Verified: 2026-08-05
        name="claude-haiku-4-5",
        base_input_per_mtok=1.0,
        cache_read_per_mtok=0.10,
        cache_write_5m_per_mtok=1.25,
        cache_write_1h_per_mtok=2.0,
        output_per_mtok=5.0,
    ),
    # ── OpenAI ────────────────────────────────────────────────────────────
    # Source: https://openai.com/api/pricing/ (verified via 2026-08 secondary
    # sources; direct fetch returned 403). OpenAI cached input is 50% off base.
    # No separate 5m/1h split — both write columns equal base.
    # Verified: 2026-08-05
    "gpt-4o": ModelPricing(
        name="gpt-4o",
        base_input_per_mtok=2.50,
        cache_read_per_mtok=1.25,
        cache_write_5m_per_mtok=2.50,
        cache_write_1h_per_mtok=2.50,
        output_per_mtok=10.0,
    ),
    "gpt-4o-mini": ModelPricing(
        # Source: https://openai.com/api/pricing/ (verified via secondary 2026-08)
        # Verified: 2026-08-05
        name="gpt-4o-mini",
        base_input_per_mtok=0.15,
        cache_read_per_mtok=0.075,
        cache_write_5m_per_mtok=0.15,
        cache_write_1h_per_mtok=0.15,
        output_per_mtok=0.60,
    ),
    # ── Google Gemini ─────────────────────────────────────────────────────
    # NOTE: Gemini 1.5 family was deprecated by Google in June 2026 (returns
    # 404 on newer endpoints). Kept for historical trace analysis. Values
    # match last-published rates. Cache reads at 10% of base per Google docs.
    # Source: https://ai.google.dev/pricing (historical archived rates)
    # Verified: 2026-08-05 (deprecation note)
    "gemini-1.5-pro": ModelPricing(
        name="gemini-1.5-pro",
        base_input_per_mtok=1.25,
        cache_read_per_mtok=0.125,
        cache_write_5m_per_mtok=1.25,
        cache_write_1h_per_mtok=1.25,
        output_per_mtok=5.0,
    ),
    "gemini-1.5-flash": ModelPricing(
        # Source: historical archived rates
        # Verified: 2026-08-05 (deprecated in June 2026)
        name="gemini-1.5-flash",
        base_input_per_mtok=0.075,
        cache_read_per_mtok=0.0075,
        cache_write_5m_per_mtok=0.075,
        cache_write_1h_per_mtok=0.075,
        output_per_mtok=0.30,
    ),
}


DEFAULT_MODEL_KEY = "sonnet-4.5"


# Alias table: provider-emitted model strings → PRICING keys.
# Longest-match wins (so gpt-4o-mini-2024-07 does not incorrectly hit gpt-4o).
_ALIASES: tuple[tuple[str, str], ...] = (
    # OpenAI: gpt-4o-mini variants MUST match before gpt-4o (longest prefix)
    ("gpt-4o-mini", "gpt-4o-mini"),
    ("gpt-4o", "gpt-4o"),
    # Anthropic
    ("claude-sonnet-4-5", "sonnet-4.5"),
    ("claude-sonnet-4.5", "sonnet-4.5"),
    ("claude-3-5-sonnet", "sonnet-4.5"),
    ("claude-3.5-sonnet", "sonnet-4.5"),
    ("claude-sonnet-4-6", "sonnet-4.6"),
    ("claude-sonnet-4.6", "sonnet-4.6"),
    ("claude-opus-4-7", "opus-4.7"),
    ("claude-opus-4.7", "opus-4.7"),
    ("claude-opus-4", "opus-4.7"),  # falls to nearest known Opus
    ("claude-haiku-4-5", "haiku-4.5"),
    ("claude-haiku-4.5", "haiku-4.5"),
    # Google
    ("gemini-1.5-pro", "gemini-1.5-pro"),
    ("gemini-1.5-flash", "gemini-1.5-flash"),
)


def get_pricing(model_key: str | None = None) -> ModelPricing:
    """Resolve a model identifier to a `ModelPricing` entry.

    Priority (per Cost Attribution Completion prereg §3):
      1. `None` → default (Sonnet 4.5)
      2. Exact key match against PRICING
      3. Longest-prefix alias match (case-insensitive, whitespace-stripped)
      4. Unknown → emit UserWarning, return default (soft-fail)

    Never raises. Callers get a best-effort pricing rather than a crash.
    """
    if model_key is None:
        return PRICING[DEFAULT_MODEL_KEY]

    normalized = model_key.strip().lower()

    if normalized in PRICING:
        return PRICING[normalized]

    # Longest-prefix alias resolution: ordered tuple ensures gpt-4o-mini
    # matches before gpt-4o.
    for prefix, target_key in _ALIASES:
        if normalized.startswith(prefix):
            return PRICING[target_key]

    warnings.warn(
        f"pricing: unknown model {model_key!r}; using default "
        f"{DEFAULT_MODEL_KEY!r} (Sonnet 4.5 rates)",
        stacklevel=2,
    )
    return PRICING[DEFAULT_MODEL_KEY]
