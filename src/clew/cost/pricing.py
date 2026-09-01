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
    "opus-5": ModelPricing(
        # Source: https://platform.claude.com/docs/en/about-claude/pricing
        # Verified: 2026-08-27
        # Rates are identical to Opus 4.7 and 4.8; the entry is explicit anyway
        # because `claude-opus-5` does not match the `claude-opus-4` alias
        # prefix, so without it every Opus 5 trace priced as Sonnet 4.5 --
        # measured at 25 of 74 stored runs on 2026-08-27, each carrying an
        # `accuracy_flag` of "accurate" while the rate was a fallback.
        name="claude-opus-5",
        base_input_per_mtok=5.0,
        cache_read_per_mtok=0.50,
        cache_write_5m_per_mtok=6.25,
        cache_write_1h_per_mtok=10.0,
        output_per_mtok=25.0,
    ),
    "sonnet-5": ModelPricing(
        # Source: https://platform.claude.com/docs/en/about-claude/pricing
        # Verified: 2026-08-27
        # Cheaper than Sonnet 4.6, not equal to it: $2 base against $3. The
        # source page notes the $2/$10 launch pricing became the standard
        # price and the scheduled rise to $3/$15 will not happen, so this is
        # not an introductory rate with an expiry to track.
        name="claude-sonnet-5",
        base_input_per_mtok=2.0,
        cache_read_per_mtok=0.20,
        cache_write_5m_per_mtok=2.50,
        cache_write_1h_per_mtok=4.0,
        output_per_mtok=10.0,
    ),
    "fable-5": ModelPricing(
        # Source: https://platform.claude.com/docs/en/about-claude/pricing
        # Verified: 2026-08-27
        # The entry that matters most for a missing-model fallback: at $10
        # base against the $3 default, an unpriced Fable 5 trace would report
        # roughly a third of its real input cost.
        name="claude-fable-5",
        base_input_per_mtok=10.0,
        cache_read_per_mtok=1.0,
        cache_write_5m_per_mtok=12.50,
        cache_write_1h_per_mtok=20.0,
        output_per_mtok=50.0,
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
        # Source: https://ai.google.dev/pricing (historical archived rates)
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
    # ── OpenAI GPT-5.2 (Cost Table Exgentic Expansion prereg §1.2) ────────
    # Source: https://developers.openai.com/api/docs/pricing
    # Verified: 2026-08-13 · Standard tier; cache_write not separately
    # published, defaults to base_input per prereg §2.2.
    "gpt-5.2": ModelPricing(
        name="gpt-5.2",
        base_input_per_mtok=1.75,
        cache_read_per_mtok=0.175,
        cache_write_5m_per_mtok=1.75,
        cache_write_1h_per_mtok=1.75,
        output_per_mtok=14.0,
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
    # ── Moonshot Kimi K2.5 (Cost Table Exgentic Expansion prereg §1.1) ────
    # Source: https://openrouter.ai/moonshotai/kimi-k2.5
    # Verified: 2026-08-13 · Moonshot's own platform.kimi.ai no longer
    # lists K2.5 (superseded by K2.6 / K2.7 / K3); OpenRouter is used per
    # prereg §2.1 second-choice as a provider-facing aggregator.
    # Cache tier not published on the vendor rate — defaults to base_input
    # per prereg §2.2.
    "kimi-k2.5": ModelPricing(
        name="kimi-k2.5",
        base_input_per_mtok=0.375,
        cache_read_per_mtok=0.375,
        cache_write_5m_per_mtok=0.375,
        cache_write_1h_per_mtok=0.375,
        output_per_mtok=2.025,
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
    ("claude-opus-5", "opus-5"),
    ("claude-fable-5", "fable-5"),
    ("claude-sonnet-5", "sonnet-5"),
    # Opus 4.8 already resolved through the `claude-opus-4` prefix below, and
    # by luck to the right number -- 4.7 and 4.8 are priced identically. The
    # explicit alias removes the luck: if the two ever diverge, this line is
    # what has to change, rather than a fallback quietly staying plausible.
    ("claude-opus-4-8", "opus-4.7"),
    ("claude-opus-4.8", "opus-4.7"),
    ("claude-opus-4-7", "opus-4.7"),
    ("claude-opus-4.7", "opus-4.7"),
    # Exgentic canonical `claude-opus-4-5`: Opus 4.5 rate ($5/$25 per
    # Anthropic pricing 2026-08-13) matches opus-4.7 exactly; explicit
    # alias documents intent and locks against `claude-opus-4` drift.
    ("claude-opus-4-5", "opus-4.7"),
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
    # Cost Table Exgentic Expansion prereg §1.4: gpt-5.2 must precede
    # gpt-5.1 / gpt-5-mini / gpt-5-high / gpt-5 so the Exgentic canonical
    # `gpt-5.2-2025-12-11` resolves via startswith on `gpt-5.2`.
    ("gpt-5.2", "gpt-5.2"),
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
    # Cost Table Exgentic Expansion prereg §1.4: kimi-k2.5 must precede
    # kimi-k2-0905 (Moonshot K2.5 is a distinct rate tier from K2-0905).
    ("kimi-k2.5", "kimi-k2.5"),
    ("kimi-k2-0905", "kimi-k2-0905"),
    ("minimax-m2", "minimax-m2"),
    ("qwen-3-coder", "qwen-3-coder"),
)


def build_default_cost_tables() -> tuple[dict[str, float], dict[str, float]]:
    """Build ($/input-token, $/output-token) exact-match tables covering PRICING
    canonical keys + `.name` values + `_ALIASES` prefixes, each with the
    Toolathlon run-suffix variants (`_1`, `_2`, `_3`).

    Used by the CLI (`python -m clew`) to auto-populate cost tables so `WR_cost`
    fires on default runs. Diagnostic scripts (`field_test/diagnostics/`) build
    their own tables against the same source of truth. Only `base_input_per_mtok`
    and `output_per_mtok` are exposed — cache-tier splits stay opt-in via the
    detector-side APIs.
    """
    input_ct: dict[str, float] = {}
    output_ct: dict[str, float] = {}

    seed: list[tuple[str, ModelPricing]] = []
    for canonical_key, pricing in PRICING.items():
        seed.append((canonical_key, pricing))
        seed.append((pricing.name, pricing))
    for prefix, target_key in _ALIASES:
        seed.append((prefix, PRICING[target_key]))

    for key, pricing in seed:
        input_rate = pricing.base_input_per_mtok / _USD_PER_MTOK
        output_rate = pricing.output_per_mtok / _USD_PER_MTOK
        input_ct[key] = input_rate
        output_ct[key] = output_rate
        for suffix in ("_1", "_2", "_3"):
            input_ct[key + suffix] = input_rate
            output_ct[key + suffix] = output_rate

    return input_ct, output_ct


def get_pricing(model_key: str | None = None) -> ModelPricing:
    """Resolve a model identifier to a `ModelPricing` entry.

    Priority (per Cost Attribution Completion prereg §3):
      1. `None` → default (Sonnet 4.5)
      2. Exact key match against PRICING
      3. Longest-prefix alias match (case-insensitive, whitespace-stripped)
      4. Unknown → emit UserWarning, return default (soft-fail)

    Never raises. Callers get a best-effort pricing rather than a crash.
    """
    pricing, matched = resolve_pricing(model_key)
    if not matched and model_key is not None:
        warnings.warn(
            f"pricing: unknown model {model_key!r}; using default "
            f"{DEFAULT_MODEL_KEY!r} (Sonnet 4.5 rates)",
            stacklevel=2,
        )
    return pricing


def resolve_pricing(model_key: str | None) -> tuple[ModelPricing, bool]:
    """Same resolution as `get_pricing`, and whether it found anything.

    Two callers need different things from one lookup. A human at a terminal
    wants the warning; a report needs to record that a rate was substituted, in
    a field a downstream consumer can read -- the warning goes to stderr, where
    the storage layer and the dashboard never see it. Measured 2026-08-27: 25 of
    74 stored runs were priced at the default and labeled `accurate`, and
    nothing in the report said so.

    `matched` is False when the default was substituted, including when
    `model_key` is None -- an absent model is not a priced one.

    The default is Sonnet 4.5, which is *cheaper* than the Opus tier it most
    often stands in for, so a substituted rate understates cost rather than
    inflating it. Those 25 runs were priced at 60% of the correct rate.
    """
    if model_key is None:
        return PRICING[DEFAULT_MODEL_KEY], False

    normalized = model_key.strip().lower()

    if normalized in PRICING:
        return PRICING[normalized], True

    # Longest-prefix alias resolution: ordered tuple ensures gpt-4o-mini
    # matches before gpt-4o.
    for prefix, target_key in _ALIASES:
        if normalized.startswith(prefix):
            return PRICING[target_key], True

    return PRICING[DEFAULT_MODEL_KEY], False
