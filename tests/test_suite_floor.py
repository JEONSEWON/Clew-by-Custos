"""One check on the suite itself: it must not quietly get smaller.

`837 passed` is a number the suite computes about itself, and most of these
tests come from `parametrize` lists. A list that silently empties takes its
checks with it, the run still reports `N/N passed`, and exit stays 0. Until this
file existed, the only thing catching that was somebody remembering what the
count used to be, which makes a person's memory the assertion.

Found by the web session on its own harness after a day in which the same shape
appeared five times across two sessions: a guard that passed while the thing it
guarded was gone. See `feedback_assert_on_shipped_artifact`.

★ The collected count is not one number, and the first version of this file
failed CI by assuming it was. CI installs `.[detect,dev]`, which leaves
`opentelemetry` out (it lives in `[adapter]`), and two modules skip at import
without it. So CI collects 819 where a full local install collects 838. The
floor is per-environment for that reason, keyed on the one dependency that
changes collection rather than on a guess about which packages matter -- the
guess is what produced the broken first version.

When this fails after tests were deliberately removed, lower the floor in the
same commit that removes them, and say which ones in the message. That is the
point: shrinking the suite becomes a decision somebody writes down. Raising it
needs no ceremony.
"""
from __future__ import annotations

import pytest

# Measured 2026-08-31 with `--collect-only`, each less a small margin so
# removing one or two tests on purpose does not fail the build while a list
# quietly emptying does. Both verified by running the suite in both
# environments, and both verified to fail when raised above the real count.
#
# The floor is compared against `len(session.items)`, which sits a few above
# the `--collect-only` figure: pytest counts a module-level import skip as one
# skipped entry of its own while its tests are not collected at all. That makes
# these margins slightly more conservative than they look, which is the right
# direction for a floor.
FLOOR_WITHOUT_ADAPTER = 833        # 840 collected on a clean `.[detect,dev]`
FLOOR_WITH_ADAPTER = 852           # 859 collected with the adapter extra


def _adapter_stack_present() -> bool:
    """Whether the two import-skipping modules will be collected.

    `test_langgraph_adapter.py` and `test_report_cli.py` both
    `importorskip("opentelemetry.sdk.trace")` at module level, which drops
    their tests from collection entirely rather than reporting them as skipped
    tests. Those 19 are the whole difference between the two floors.
    """
    try:
        import opentelemetry.sdk.trace  # noqa: F401
    except ImportError:
        return False
    return True


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

    with_adapter = _adapter_stack_present()
    floor = FLOOR_WITH_ADAPTER if with_adapter else FLOOR_WITHOUT_ADAPTER
    collected = len(request.session.items)

    assert collected >= floor, (
        f"the suite collected {collected} tests, below the floor of {floor} "
        f"for this environment (adapter extra "
        f"{'installed' if with_adapter else 'absent'}). Either a parametrize "
        "list emptied or a module stopped being collected. If tests were "
        "removed on purpose, lower the floor in the same commit."
    )
