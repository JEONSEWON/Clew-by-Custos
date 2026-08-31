"""Claims the project makes about itself, counted rather than trusted.

Every assertion here has the same shape: a sentence in a shipped artifact says
"all N of these", and nothing was checking that the N was still true. That is
the pattern `feedback_assert_on_shipped_artifact` names, and it showed up four
times in two days before this file existed.

The rule for adding to this file: the claim has to be *countable* and *shipped*.
"Four deterministic detectors" is both. "Fast" is neither.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
PRICING_SRC = (ROOT / "src" / "clew" / "cost" / "pricing.py").read_text(encoding="utf-8")


# ── "Four deterministic detectors" ─────────────────────────────────────────

def test_the_readme_counts_the_detectors_the_code_has():
    """The README says four and names them in five places. If a fifth ships or
    one is renamed, every one of those sentences becomes false at once."""
    from clew.metrics.waste_rate import DETECTOR_ORDER

    named = ("repeat", "context_resend", "redundant_read", "duplicate_creation")
    assert DETECTOR_ORDER == named, (
        f"README names {named} as the deterministic detectors; the code carries "
        f"{DETECTOR_ORDER}. Update both in the same commit."
    )
    assert "Four deterministic detectors" in README or \
           "four deterministic detectors" in README.lower(), (
        "the README's count of the detectors has moved; this guard tracks the "
        "sentence as well as the list"
    )
    for name in named:
        assert f"`{name}`" in README, f"README stopped naming the {name} detector"


def test_the_detector_count_in_prose_matches_the_list():
    """`Deterministic waste detectors (4)` is a number in a heading. A heading
    that disagrees with its own list is how a stale count survives review."""
    from clew.metrics.waste_rate import DETECTOR_ORDER

    stated = re.findall(r"[Dd]eterministic waste detectors \((\d+)\)", README)
    assert stated, "the README's detector-count heading is gone or reworded"
    for count in stated:
        assert int(count) == len(DETECTOR_ORDER), (
            f"README heading says {count} deterministic detectors, the code has "
            f"{len(DETECTOR_ORDER)}"
        )


# ── "Each pricing entry carries a source URL and ISO-8601 verification date" ──

def _entry_blocks() -> dict[str, str]:
    """Each PRICING entry's own text, plus the comment lines directly above it.

    Deliberately not the whole span since the previous entry: that would let an
    entry inherit its predecessor's provenance and the guard would pass on a
    table where only the first row was sourced.
    """
    lines = PRICING_SRC.splitlines()
    starts = [
        (i, m.group(1))
        for i, line in enumerate(lines)
        if (m := re.match(r'^    "([^"]+)": ModelPricing\($', line))
    ]
    blocks = {}
    for i, key in starts:
        top = i
        while top > 0 and lines[top - 1].strip().startswith("#"):
            top -= 1
        end = i
        while end < len(lines) and not re.match(r"^    \),?$", lines[end]):
            end += 1
        blocks[key] = "\n".join(lines[top:end + 1])
    return blocks


def test_every_pricing_entry_carries_its_source_and_date():
    """README §Cost attribution: "Each pricing entry carries a source URL and
    ISO-8601 verification date." Nothing counted that until this test."""
    from clew.cost.pricing import PRICING

    blocks = _entry_blocks()
    assert set(blocks) == set(PRICING), (
        f"the parser and the table disagree about which entries exist: "
        f"only in source {sorted(set(blocks) - set(PRICING))}, "
        f"only in PRICING {sorted(set(PRICING) - set(blocks))}"
    )

    missing_source = sorted(k for k, b in blocks.items() if "https://" not in b)
    missing_date = sorted(
        k for k, b in blocks.items()
        if not re.search(r"Verified:\s*\d{4}-\d{2}-\d{2}", b)
    )
    assert not missing_source, f"pricing entries with no source URL: {missing_source}"
    assert not missing_date, f"pricing entries with no ISO verification date: {missing_date}"


def test_the_readme_still_makes_that_claim():
    """If the sentence goes, the guard above is guarding nothing. This is the
    half that usually rots: the assertion outlives the claim it was written for
    and keeps passing about a promise nobody makes any more."""
    assert "source URL and ISO-8601 verification date" in README, (
        "the README's pricing-provenance sentence has changed; either restore "
        "it or delete the guard that enforces it"
    )


@pytest.mark.parametrize("model", [
    "sonnet-4.5", "sonnet-4.6", "opus-4.7", "haiku-4.5", "gpt-4o", "gpt-4o-mini",
    "gemini-1.5-pro", "gemini-1.5-flash",
])
def test_models_the_readme_claims_coverage_of_are_priced(model):
    """README §Cost attribution names the models the tables cover. A name in
    that sentence that is not a key is a coverage claim about nothing."""
    from clew.cost.pricing import PRICING

    assert model in PRICING, (
        f"README claims pricing coverage the table does not have: {model}"
    )
