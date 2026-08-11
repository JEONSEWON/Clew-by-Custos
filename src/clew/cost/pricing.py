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
    # ── OpenAI GPT-5 family ───────────────────────────────────────────────
    # Source: https://openai.com/api/pricing/ (per 2026-08 aggregate published
    # rate; direct provider fetch returned 403 as with GPT-4o).
    # Verified: 2026-08-11 · Cost Table Toolathlon Expansion prereg §2.4
    "gpt-5": ModelPricing(
        name="gpt-5",
        base_input_per_mtok=1.25,
        cache_read_per_mtok=0.625,
        cache_write_5m_per_mtok=1.25,
        cache_write_1h_per_mtok=1.25,
        output_per_mtok=10.0,
    ),
    "gpt-5-mini": ModelPricing(
        # Source: https://openai.com/api/pricing/
        # Verified: 2026-08-11
        name="gpt-5-mini",
        base_input_per_mtok=0.25,
        cache_read_per_mtok=0.125,
        cache_write_5m_per_mtok=0.25,
        cache_write_1h_per_mtok=0.25,
        output_per_mtok=2.0,
    ),
    # ── OpenAI o-series reasoning models ──────────────────────────────────
    # NOTE: o-series bills internal reasoning tokens at output rate. The
    # per-token cost figure below is the CONTRACT rate; effective cost per
    # user-facing response is higher (3-10x typical) depending on reasoning
    # depth. WR_cost aggregates over reported tokens, not reasoning-inflated
    # effective tokens; documented for reader interpretation.
    # Source: https://openai.com/api/pricing/
    # Verified: 2026-08-11
    "o3": ModelPricing(
        name="o3",
        base_input_per_mtok=2.0,
        cache_read_per_mtok=1.0,
        cache_write_5m_per_mtok=2.0,
        cache_write_1h_per_mtok=2.0,
        output_per_mtok=8.0,
    ),
    "o4-mini": ModelPricing(
        # Source: https://openai.com/api/pricing/
        # Verified: 2026-08-11
        name="o4-mini",
        base_input_per_mtok=1.10,
        cache_read_per_mtok=0.55,
        cache_write_5m_per_mtok=1.10,
        cache_write_1h_per_mtok=1.10,
        output_per_mtok=4.40,
    ),
    # ── Google Gemini 2.5 / 3.x family ────────────────────────────────────
    # Source: https://ai.google.dev/pricing
    # Verified: 2026-08-11 · Cache read at 10% of base per Google policy.
    "gemini-2.5-pro": ModelPricing(
        name="gemini-2.5-pro",
        base_input_per_mtok=1.25,
        cache_read_per_mtok=0.125,
        cache_write_5m_per_mtok=1.25,
        cache_write_1h_per_mtok=1.25,
        output_per_mtok=10.0,
    ),
    "gemini-2.5-flash": ModelPricing(
        # Source: https://ai.google.dev/pricing
        # Verified: 2026-08-11
        name="gemini-2.5-flash",
        base_input_per_mtok=0.30,
        cache_read_per_mtok=0.030,
        cache_write_5m_per_mtok=0.30,
        cache_write_1h_per_mtok=0.30,
        output_per_mtok=2.50,
    ),
    "gemini-3-pro-preview": ModelPricing(
        # Source: https://ai.google.dev/pricing (preview tier; may change on
        # general availability, forecast in prereg §1.1)
        # Verified: 2026-08-11
        name="gemini-3-pro-preview",
        base_input_per_mtok=2.0,
        cache_read_per_mtok=0.20,
        cache_write_5m_per_mtok=2.0,
        cache_write_1h_per_mtok=2.0,
        output_per_mtok=12.0,
    ),
    # ── xAI Grok family ────────────────────────────────────────────────────
    # Source: https://x.ai/api (xAI console pricing)
    # Verified: 2026-08-11 · No 5m/1h split published by xAI.
    "grok-4": ModelPricing(
        name="grok-4",
        base_input_per_mtok=3.0,
        cache_read_per_mtok=0.75,
        cache_write_5m_per_mtok=3.0,
        cache_write_1h_per_mtok=3.0,
        output_per_mtok=15.0,
    ),
    "grok-4-fast": ModelPricing(
        # Source: https://x.ai/api (Fast-tier rate published alongside Grok 4.1)
        # Verified: 2026-08-11
        name="grok-4-fast",
        base_input_per_mtok=0.20,
        cache_read_per_mtok=0.05,
        cache_write_5m_per_mtok=0.20,
        cache_write_1h_per_mtok=0.20,
        output_per_mtok=0.50,
    ),
    "grok-code-fast-1": ModelPricing(
        # Source: https://x.ai/api (code-fast tier; priced same as Fast per
        # xAI console 2026-08).
        # Verified: 2026-08-11
        name="grok-code-fast-1",
        base_input_per_mtok=0.20,
        cache_read_per_mtok=0.05,
        cache_write_5m_per_mtok=0.20,
        cache_write_1h_per_mtok=0.20,
        output_per_mtok=1.50,
    ),
    # ── DeepSeek v3.x family ──────────────────────────────────────────────
    # Source: https://api-docs.deepseek.com/quick_start/pricing
    # Verified: 2026-08-11 · Cache hit at ~10% of base per DeepSeek docs.
    "deepseek-v3.2": ModelPricing(
        name="deepseek-v3.2",
        base_input_per_mtok=0.28,
        cache_read_per_mtok=0.028,
        cache_write_5m_per_mtok=0.28,
        cache_write_1h_per_mtok=0.28,
        output_per_mtok=0.42,
    ),
    # ── Zhipu GLM ─────────────────────────────────────────────────────────
    # Source: https://open.bigmodel.cn/pricing (best-effort; provider-neutral
    # aggregator confirmation used per prereg §2.4 fallback).
    # Verified: 2026-08-11
    "glm-4.6": ModelPricing(
        name="glm-4.6",
        base_input_per_mtok=0.60,
        cache_read_per_mtok=0.60,  # provider does not publish cache tier
        cache_write_5m_per_mtok=0.60,
        cache_write_1h_per_mtok=0.60,
        output_per_mtok=2.40,
    ),
    # ── Moonshot Kimi K2 ──────────────────────────────────────────────────
    # Source: https://platform.moonshot.cn/docs/pricing
    # Verified: 2026-08-11 · K2-0905 (Sep 5) family rate.
    "kimi-k2-0905": ModelPricing(
        name="kimi-k2-0905",
        base_input_per_mtok=0.50,
        cache_read_per_mtok=0.50,
        cache_write_5m_per_mtok=0.50,
        cache_write_1h_per_mtok=0.50,
        output_per_mtok=2.00,
    ),
    # ── MiniMax M2 ────────────────────────────────────────────────────────
    # Source: https://api.minimaxi.com/pricing
    # Verified: 2026-08-11 · Base M2 tier (context window ~200K).
    "minimax-m2": ModelPricing(
        name="minimax-m2",
        base_input_per_mtok=0.30,
        cache_read_per_mtok=0.30,
        cache_write_5m_per_mtok=0.30,
        cache_write_1h_per_mtok=0.30,
        output_per_mtok=1.20,
    ),
    # ── Alibaba Qwen 3 Coder ──────────────────────────────────────────────
    # Source: https://help.aliyun.com/zh/dashscope/pricing
    # Verified: 2026-08-11 · Coder-specific tier.
    "qwen-3-coder": ModelPricing(
        name="qwen-3-coder",
        base_input_per_mtok=0.22,
        cache_read_per_mtok=0.022,
        cache_write_5m_per_mtok=0.22,
        cache_write_1h_per_mtok=0.22,
        output_per_mtok=1.00,
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
    # ── Toolathlon Expansion (Cost Table Toolathlon Expansion prereg §1) ──
    # These aliases resolve the 22 `modelname_run` values (including the
    # `_1`/`_2`/`_3` run-index suffix Toolathlon appends) via startswith
    # prefix match. Order matters: more-specific prefixes must precede
    # less-specific ones (e.g. gpt-5-mini before gpt-5).
    # OpenAI GPT-5 / o-series family (longest first)
    ("gpt-5.1", "gpt-5"),        # minor variant, same base rate
    ("gpt-5-mini", "gpt-5-mini"),
    ("gpt-5-high", "gpt-5"),      # high-throughput variant, same base rate
    ("gpt-5", "gpt-5"),
    ("o4-mini", "o4-mini"),
    ("o3", "o3"),
    # Anthropic 4.x historical model IDs Toolathlon uses
    ("claude-4.5-sonnet-0929", "sonnet-4.5"),
    ("claude-4.5-opus", "opus-4.7"),  # nearest known Opus rate
    ("claude-4.5-haiku-1001", "haiku-4.5"),
    ("claude-4-sonnet-0514", "sonnet-4.5"),  # Sonnet 4.0 (2024-05); same $3/$15 tier
    # Google Gemini 2.5 / 3.x
    ("gemini-3-pro-preview", "gemini-3-pro-preview"),
    ("gemini-2.5-pro", "gemini-2.5-pro"),
    ("gemini-2.5-flash", "gemini-2.5-flash"),
    # xAI Grok (longest first)
    ("grok-code-fast-1", "grok-code-fast-1"),
    ("grok-4-fast", "grok-4-fast"),
    ("grok-4", "grok-4"),
    # DeepSeek (both variants share v3.2 rate per DeepSeek pricing page)
    ("deepseek-3.2-thinking", "deepseek-v3.2"),
    ("deepseek-v3.2-exp", "deepseek-v3.2"),
    ("deepseek-v3.2", "deepseek-v3.2"),
    # Others
    ("glm-4.6", "glm-4.6"),
    ("kimi-k2-0905", "kimi-k2-0905"),
    ("minimax-m2", "minimax-m2"),
    ("qwen-3-coder", "qwen-3-coder"),
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
