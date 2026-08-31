"""One check on the suite itself: it must not quietly get smaller.

`836 passed` is a number the suite computes about itself, and most of these
tests come from `parametrize` lists. A list that silently empties takes its
checks with it, the run still reports `N/N passed`, and exit stays 0. Until this
file existed, the only thing catching that was somebody remembering what the
count used to be, which makes a person's memory the assertion.

Found by the web session on its own harness after a day in which the same shape
appeared five times across two sessions: a guard that passed while the thing it
guarded was gone. See `feedback_assert_on_shipped_artifact`.

When this fails after tests were deliberately removed, lower FLOOR in the same
commit that removes them, and say which ones in the message. That is the point:
shrinking the suite becomes a decision somebody writes down.
"""
from __future__ import annotations

import pytest

# Collected count on 2026-08-31 (837) less a small margin, so an intentional
# removal of one or two tests does not fail the build while a list quietly
# emptying does.
FLOOR = 830


def test_the_suite_did_not_quietly_shrink(request):
    """Distinguishes: a parametrize list that empties, or a module that stops
    being collected. Both leave every remaining test passing."""
    config = request.config
    if config.option.keyword or config.option.markexpr:
        pytest.skip("filtered run: -k or -m selects a subset by design")
    # A run scoped to files or node ids collects fewer by design. A full run
    # passes no arguments or a directory, and only those are enforced. Without
    # this, `pytest tests/test_suite_floor.py` fails on itself, which is how
    # this condition came to exist.
    if any(str(a).endswith(".py") or "::" in str(a) for a in config.args):
        pytest.skip("run scoped to files or node ids: a subset by design")

    collected = len(request.session.items)
    assert collected >= FLOOR, (
        f"the suite collected {collected} tests, below the floor of {FLOOR}. "
        "Either a parametrize list emptied or a module stopped being collected. "
        "If tests were removed on purpose, lower FLOOR in the same commit."
    )
