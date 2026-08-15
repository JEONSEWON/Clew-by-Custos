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
    build_default_cost_tables,
    get_pricing,
)
from clew.cost.pricing import _ALIASES


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


# ─── Cost Table Toolathlon Expansion prereg §5 ────────────────────────────


TOOLATHLON_MODEL_FAMILIES = [
    # Anthropic (4) — resolve to existing entries via alias
    ("claude-4-sonnet-0514", "sonnet-4.5"),
    ("claude-4.5-sonnet-0929", "sonnet-4.5"),
    ("claude-4.5-opus", "opus-4.7"),
    ("claude-4.5-haiku-1001", "haiku-4.5"),
    # OpenAI (6)
    ("gpt-5", "gpt-5"),
    ("gpt-5-high", "gpt-5"),
    ("gpt-5-mini", "gpt-5-mini"),
    ("gpt-5.1", "gpt-5"),
    ("o3", "o3"),
    ("o4-mini", "o4-mini"),
    # Google (3)
    ("gemini-2.5-flash", "gemini-2.5-flash"),
    ("gemini-2.5-pro", "gemini-2.5-pro"),
    ("gemini-3-pro-preview", "gemini-3-pro-preview"),
    # xAI (3)
    ("grok-4", "grok-4"),
    ("grok-4-fast", "grok-4-fast"),
    ("grok-code-fast-1", "grok-code-fast-1"),
    # DeepSeek (2) — both variants share v3.2 base
    ("deepseek-3.2-thinking", "deepseek-v3.2"),
    ("deepseek-v3.2-exp", "deepseek-v3.2"),
    # Others (4)
    ("glm-4.6", "glm-4.6"),
    ("kimi-k2-0905", "kimi-k2-0905"),
    ("minimax-m2", "minimax-m2"),
    ("qwen-3-coder", "qwen-3-coder"),
]


@pytest.mark.parametrize("family_name,expected_canonical", TOOLATHLON_MODEL_FAMILIES)
def test_toolathlon_model_family_resolves(family_name: str, expected_canonical: str):
    """Every §1 model family resolves without a warning to the expected canonical key."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # fail on UserWarning
        pricing = get_pricing(family_name)
    assert pricing is PRICING[expected_canonical], (
        f"{family_name} resolved to {pricing.name!r}, expected canonical {expected_canonical!r}"
    )


@pytest.mark.parametrize("family_name,expected_canonical", TOOLATHLON_MODEL_FAMILIES)
@pytest.mark.parametrize("suffix", ["_1", "_2", "_3"])
def test_toolathlon_run_suffix_resolves(
    family_name: str, expected_canonical: str, suffix: str,
):
    """§1.2: `_1`/`_2`/`_3` run-index suffix strips via existing prefix-match alias table."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        pricing = get_pricing(family_name + suffix)
    assert pricing is PRICING[expected_canonical], (
        f"{family_name}{suffix} resolved to {pricing.name!r}, expected {expected_canonical!r}"
    )


def test_expansion_did_not_disturb_existing_entries():
    """Prereg §3: existing 8 entries and their published values are unchanged."""
    expected = {
        "sonnet-4.5": (3.0, 15.0, 0.30),
        "sonnet-4.6": (3.0, 15.0, 0.30),
        "opus-4.7": (5.0, 25.0, 0.50),
        "haiku-4.5": (1.0, 5.0, 0.10),
        "gpt-4o": (2.50, 10.0, 1.25),
        "gpt-4o-mini": (0.15, 0.60, 0.075),
        "gemini-1.5-pro": (1.25, 5.0, 0.125),
        "gemini-1.5-flash": (0.075, 0.30, 0.0075),
    }
    for key, (bi, out, cr) in expected.items():
        p = PRICING[key]
        assert p.base_input_per_mtok == bi, f"{key} base_input changed"
        assert p.output_per_mtok == out, f"{key} output changed"
        assert p.cache_read_per_mtok == cr, f"{key} cache_read changed"


def test_expansion_new_entries_have_verification_date():
    """Every new §1 entry must carry the 2026-08-11 verification date somewhere."""
    path = Path(__file__).resolve().parents[2] / "src" / "clew" / "cost" / "pricing.py"
    text = path.read_text(encoding="utf-8")
    # Prereg was locked 2026-08-11; every new provider group references this date.
    # Providers added: OpenAI GPT-5 family, o-series, Google 2.5/3, xAI, DeepSeek,
    # Zhipu, Moonshot, MiniMax, Alibaba (>= 8 group blocks, each with the date).
    assert text.count("2026-08-11") >= 8, (
        f"expected at least 8 occurrences of 2026-08-11 (one per new provider group), "
        f"found {text.count('2026-08-11')}"
    )


def test_expansion_alias_ordering_avoids_shadow():
    """Longest / most-specific aliases win before generic ones (prereg §5.2)."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        # gpt-5-mini must NOT resolve to gpt-5
        assert get_pricing("gpt-5-mini") is PRICING["gpt-5-mini"]
        assert get_pricing("gpt-5-mini_2") is PRICING["gpt-5-mini"]
        # grok-4-fast must NOT resolve to grok-4
        assert get_pricing("grok-4-fast") is PRICING["grok-4-fast"]
        assert get_pricing("grok-4-fast_3") is PRICING["grok-4-fast"]
        # gpt-5.1 resolves to gpt-5 (minor version alias)
        assert get_pricing("gpt-5.1") is PRICING["gpt-5"]
        # grok-code-fast-1 has its own entry (not shadowed by grok-4-fast)
        assert get_pricing("grok-code-fast-1") is PRICING["grok-code-fast-1"]


def test_expansion_cache_tier_defaults_when_provider_uniform():
    """Providers without published cache-tier split default write columns to base_input."""
    # Zhipu / Moonshot / MiniMax do not publish separate cache tiers → all
    # cache columns equal base_input (documented in prereg §2.2).
    for key in ("glm-4.6", "kimi-k2-0905", "minimax-m2"):
        p = PRICING[key]
        assert p.cache_read_per_mtok == p.base_input_per_mtok, (
            f"{key}: expected cache_read == base_input, "
            f"got cache_read={p.cache_read_per_mtok}, base_input={p.base_input_per_mtok}"
        )
        assert p.cache_write_5m_per_mtok == p.base_input_per_mtok
        assert p.cache_write_1h_per_mtok == p.base_input_per_mtok


# ─── Cost Table Exgentic Expansion prereg §5 ──────────────────────────────


EXGENTIC_CANONICAL_MODELS = [
    # Prereg §1 · 5 Exgentic canonical model strings resolve as follows:
    ("DeepSeek-V3.2", "deepseek-v3.2"),          # unchanged — pre-existing exact match
    ("Kimi-K2.5", "kimi-k2.5"),                  # new entry (§1.1)
    ("claude-opus-4-5", "opus-4.7"),             # alias-only, rate same as Opus 4.7 (§1.3)
    ("gemini-3-pro-preview", "gemini-3-pro-preview"),  # unchanged — pre-existing exact match
    ("gpt-5.2-2025-12-11", "gpt-5.2"),           # new entry via startswith `gpt-5.2` (§1.2 + §1.4)
]


@pytest.mark.parametrize("exgentic_name,expected_canonical", EXGENTIC_CANONICAL_MODELS)
def test_exgentic_canonical_resolves_without_warning(
    exgentic_name: str, expected_canonical: str,
):
    """§4 P1: all 5 Exgentic canonical strings resolve to the correct canonical
    key with no `unknown model` UserWarning."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # fail on UserWarning
        pricing = get_pricing(exgentic_name)
    assert pricing is PRICING[expected_canonical], (
        f"{exgentic_name} resolved to {pricing.name!r}, expected {expected_canonical!r}"
    )


def test_exgentic_expansion_alias_ordering_avoids_shadow():
    """Prereg §1.4: new aliases must not be shadowed by more-general ones."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        # kimi-k2.5 must NOT fall through to kimi-k2-0905 (different rates)
        assert get_pricing("kimi-k2.5") is PRICING["kimi-k2.5"]
        assert PRICING["kimi-k2.5"] is not PRICING["kimi-k2-0905"]
        # gpt-5.2 must NOT resolve to gpt-5, gpt-5.1, gpt-5-mini, gpt-5-high
        assert get_pricing("gpt-5.2") is PRICING["gpt-5.2"]
        assert get_pricing("gpt-5.2-2025-12-11") is PRICING["gpt-5.2"]
        assert PRICING["gpt-5.2"] is not PRICING["gpt-5"]
        assert PRICING["gpt-5.2"] is not PRICING["gpt-5-mini"]
        # claude-opus-4-5 must resolve via its explicit alias, not fall to the
        # more-general claude-opus-4 alias (same target, but the explicit one
        # locks intent per prereg §1.3)
        assert get_pricing("claude-opus-4-5") is PRICING["opus-4.7"]


def test_exgentic_expansion_new_entries_have_verification_date():
    """§2.3: each new §1 entry carries the 2026-08-13 fetch date inline."""
    path = Path(__file__).resolve().parents[2] / "src" / "clew" / "cost" / "pricing.py"
    text = path.read_text(encoding="utf-8")
    # Two new provider groups added (Kimi K2.5 + GPT-5.2); each block plus the
    # explicit Opus 4.5 alias comment references 2026-08-13. Guard at >= 3.
    assert text.count("2026-08-13") >= 3, (
        f"expected at least 3 occurrences of 2026-08-13 (Kimi K2.5 block, "
        f"GPT-5.2 block, Opus 4.5 alias comment), found {text.count('2026-08-13')}"
    )


def test_exgentic_expansion_kimi_k25_rate_matches_openrouter():
    """§1.1: Kimi-K2.5 base_input $0.375 / output $2.025 per OpenRouter
    (verified 2026-08-13; guards against silent rate drift)."""
    p = PRICING["kimi-k2.5"]
    assert p.base_input_per_mtok == 0.375
    assert p.output_per_mtok == 2.025
    # Cache tier unpublished → base_input fallback (prereg §2.2)
    assert p.cache_read_per_mtok == p.base_input_per_mtok
    assert p.cache_write_5m_per_mtok == p.base_input_per_mtok
    assert p.cache_write_1h_per_mtok == p.base_input_per_mtok


def test_exgentic_expansion_gpt_52_rate_matches_openai_docs():
    """§1.2: GPT-5.2 base_input $1.75 / output $14.00 / cache_read $0.175
    per OpenAI developer pricing docs (verified 2026-08-13)."""
    p = PRICING["gpt-5.2"]
    assert p.base_input_per_mtok == 1.75
    assert p.output_per_mtok == 14.0
    assert p.cache_read_per_mtok == 0.175
    # Cache write not separately published → base_input fallback (§2.2)
    assert p.cache_write_5m_per_mtok == p.base_input_per_mtok
    assert p.cache_write_1h_per_mtok == p.base_input_per_mtok


def test_exgentic_expansion_opus_4_5_alias_matches_opus_4_7_rate():
    """§1.3: Anthropic Opus 4.5 rate ($5/$25) equals existing opus-4.7 entry;
    explicit alias resolves rather than falling through to `claude-opus-4`."""
    # Rate equality: no new PRICING entry needed
    opus_4_5 = get_pricing("claude-opus-4-5")
    opus_4_7 = PRICING["opus-4.7"]
    assert opus_4_5 is opus_4_7
    assert opus_4_5.base_input_per_mtok == 5.0
    assert opus_4_5.output_per_mtok == 25.0


# ── build_default_cost_tables (CLI auto-population) ────────────────────────

def test_build_default_cost_tables_sonnet_45_all_keys_route_to_same_rate():
    """Canonical key + `.name` + alias prefix all yield 3e-6 input / 15e-6 output."""
    input_ct, output_ct = build_default_cost_tables()
    for key in ("sonnet-4.5", "claude-sonnet-4-5", "claude-sonnet-4.5"):
        assert input_ct[key] == 3.0 / 1_000_000
        assert output_ct[key] == 15.0 / 1_000_000


def test_build_default_cost_tables_toolathlon_run_suffixes_present():
    """Every base key has `_1`/`_2`/`_3` variants at the same rate — matches
    Toolathlon `modelname_run` naming convention."""
    input_ct, _ = build_default_cost_tables()
    for base in ("gpt-5-mini", "claude-sonnet-4-5", "grok-4-fast"):
        assert base in input_ct
        for suffix in ("_1", "_2", "_3"):
            assert input_ct[base + suffix] == input_ct[base], (
                f"{base + suffix} should equal {base}"
            )


def test_build_default_cost_tables_covers_all_pricing_canonical_and_aliases():
    """Every PRICING key, `.name`, and `_ALIASES` prefix appears in the table."""
    input_ct, output_ct = build_default_cost_tables()
    for canonical_key, pricing in PRICING.items():
        assert canonical_key in input_ct
        assert pricing.name in input_ct
    for prefix, _target_key in _ALIASES:
        assert prefix in input_ct
        assert prefix in output_ct
