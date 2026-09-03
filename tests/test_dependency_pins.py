"""tests/test_dependency_pins.py — a dependency bound is a claim about our code.

The judge broke in production without a single line of our code changing. The
`[judge]` extra said `anthropic>=0.30` with no upper bound, a Modal image was
rebuilt, pip resolved 1.3.0, and `Messages.create()` in 1.x no longer accepts
`temperature`. Both judges pass `temperature=0.0`. Every judged trace came back
`not_judged: "the judge did not answer"` -- which on a dashboard reads exactly
like "there was nothing to judge".

Nothing in the suite could have caught it: the version that broke was chosen at
install time, not at commit time, and the developer machine had an older
`anthropic` already resolved. So the guard has to be about the *bound*, not
about the installed package.

The test is conditional on the reason rather than asserting the pin outright:
if the code stops passing `temperature`, migrating to 1.x is free and the
requirement is allowed to open up again. A guard that has to be edited in order
to do the right thing gets edited without being read.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JUDGE_SOURCES = (
    "src/clew/detect/llm_judge/verification_judge.py",
    "src/clew/detect/llm_judge/anthropic_client.py",
)


def _judge_requirements() -> list[str]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return pyproject["project"]["optional-dependencies"]["judge"]


def _anthropic_requirement() -> str:
    for req in _judge_requirements():
        if req.split("[")[0].split(">")[0].split("=")[0].strip() == "anthropic":
            return req
    raise AssertionError(
        "the [judge] extra no longer requires `anthropic`; if the judge moved "
        "to another provider this test should move with it"
    )


def _code_passes_temperature() -> list[str]:
    """Which judge modules still hand `temperature` to the SDK."""
    hits = []
    for rel in JUDGE_SOURCES:
        path = ROOT / rel
        if not path.exists():
            continue
        if re.search(r"^\s*temperature\s*=", path.read_text(encoding="utf-8"),
                     re.MULTILINE):
            hits.append(rel)
    return hits


def test_anthropic_is_capped_while_the_code_passes_temperature():
    """`temperature=0.0` is a 0.x-only kwarg, so 0.x has to be the ceiling."""
    passers = _code_passes_temperature()
    if not passers:
        return  # migrated; the bound is free to open again

    req = _anthropic_requirement()
    assert "<" in req, (
        "the [judge] extra requires " + repr(req) + " with no upper bound, "
        "while " + ", ".join(passers) + " still pass `temperature=` to "
        "`Messages.create()`. anthropic 1.x removed that keyword: a clean "
        "install then resolves 1.x and every judged trace returns "
        '`not_judged: "the judge did not answer"`, which is indistinguishable '
        "from having had nothing to judge. Measured live 2026-09-03 on "
        "anthropic 1.3.0. Either cap the requirement below 1, or stop passing "
        "`temperature` -- but note that `temperature=0` is stated in the "
        "shipped report text and frozen by the judge pre-registration, so "
        "removing it is an amendment."
    )


def test_the_installed_anthropic_satisfies_the_cap():
    """A developer environment that drifted past the cap measures nothing.

    Skipped when the extra is not installed, which is the normal case: the
    judge is opt-in and the base install carries no `anthropic`.
    """
    try:
        import anthropic
    except ImportError:
        return

    req = _anthropic_requirement()
    caps = re.findall(r"<\s*([0-9][0-9A-Za-z.\-]*)", req)
    if not caps:
        return  # the other test owns that failure

    installed = anthropic.__version__
    major_installed = int(installed.split(".")[0])
    major_cap = int(caps[0].split(".")[0])
    assert major_installed < major_cap, (
        "installed anthropic " + installed + " is outside the [judge] "
        "requirement " + repr(req) + ". The judge will fail at call time and "
        "report it as `not_judged`, so any measurement taken in this "
        "environment is measuring the failure path. Reinstall the extra: "
        "`pip install -e .[judge]`."
    )
