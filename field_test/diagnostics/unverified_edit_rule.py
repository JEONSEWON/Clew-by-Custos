"""field_test/diagnostics/unverified_edit_rule.py — the killed FM-3.2 rule.

**This rule did not ship.** Pre-registered in
docs/VERIFICATION_FAILURE_DETECTOR_PREREG.md, measured in
docs/VERIFICATION_FAILURE_DETECTOR_RESULTS.md, and killed there by its own
precision gate: 0.3250 hand-labelled against a pre-registered 0.70.

It lives here rather than in `src/` for the same reason the re-read detector
does not live there: `docs/REREAD_DETECTOR_PREREG.md` §11 killed that one at
precision 0.000 to 0.033. A killed rule is kept where the numbers that killed
it can be reproduced, not where it would be imported.

Why it failed, in one line: the frozen verification list encoded "a check is a
test runner". On 1,017 sessions from elsewhere, a check is mostly "run the
thing you just wrote" -- 336 of 522 candidates ran the edited file directly.

Reproduce with `_unverified_edit_corpus_d.py` and `_unverified_edit_p1.py`.

`unverified_edit`, FM-3.2 of the public taxonomy ("no or incomplete
verification"). Pre-registered in docs/VERIFICATION_FAILURE_DETECTOR_PREREG.md;
the two frozen lists below are §3 of that document and are frozen as a pair.

This is the first thing here that is not a form of "was the same work done
twice". It answers a different question: was anything checked at all.

What it deliberately does not do:

  - it does not read `is_error`. The §29.2 tool-error gate excludes those spans
    from cost as infrastructure noise, and this rule leaves that alone. The
    companion rule that would have needed them, FM-3.3, is blocked for want of
    data: of 384 error results across 85 real sessions, six came from a
    verification command.
  - it contributes nothing to `waste_span_count`, `waste_cost` or either waste
    rate. `wasteful == (waste_span_count > 0)` stays an identity.
  - it reports per session, not per span. There is no single edit to point at.
"""
from __future__ import annotations

import json
import re
from posixpath import splitext as _posix_splitext

from pydantic import BaseModel, ConfigDict

from clew.model import Trace  # noqa: E402

# Tools that change a file. `agent_or_node_id` carries the tool name on a
# Claude Code tool span (see ingest/claude_code.py).
EDIT_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})
SHELL_TOOLS = frozenset({"Bash", "PowerShell"})

# ── the frozen pair (prereg §3) ────────────────────────────────────────────
#
# A file is checkable only if the verification list holds a tool that checks
# that language. The two move together or not at all: an extension may be added
# only alongside a tool that checks it, and a tool removed only alongside the
# extensions it was the only checker for. Otherwise either list could be
# widened on its own to move the count, which is what freezing them as a pair
# prevents.
#
# `.md`, `.json`, `.yml`, `.html`, `.css`, `.sql`, `.sh`, `.ps1` are absent on
# purpose: nothing in the verification list checks them, so calling their edits
# unverified would be a false positive by construction. Eight of the first
# seventeen candidates on the author's machine edited only `.md`.
CHECKABLE_SUFFIXES = frozenset({
    ".py",                                    # pytest, mypy, ruff
    ".ts", ".tsx", ".js", ".jsx", ".mjs",      # tsc, eslint, jest, vitest, npm
    ".go",                                    # go test
    ".rs",                                    # cargo test, cargo build
})

VERIFICATION_COMMANDS = (
    "pytest", "python -m pytest", "npm test", "npm run test", "npm run build",
    "yarn test", "yarn build", "tsc", "mypy", "ruff", "eslint", "go test",
    "cargo test", "cargo build", "make test", "make check", "vitest", "jest",
)
_VERIFICATION = re.compile(
    r"\b(" + "|".join(re.escape(c) for c in VERIFICATION_COMMANDS) + r")\b",
    re.IGNORECASE,
)

# Where each edit tool names its target. `NotebookEdit` uses a different key,
# and reading only `file_path` would silently count its edits as unlocatable.
_PATH_KEYS = ("file_path", "notebook_path")


class UnverifiedEditResult(BaseModel):
    """Per session. `flagged` is the finding; the counts are why."""

    model_config = ConfigDict(extra="forbid")

    flagged: bool
    checkable_edit_count: int
    verification_count: int
    edit_count: int
    checkable_paths: list[str]


def _target_path(input_text: str) -> str | None:
    """The path an edit span names, or None if it names none.

    `input_text` is the tool input as deterministic JSON (§22.2). A span whose
    input will not parse is not guessed at: an edit we cannot locate is not
    evidence about which language was touched.
    """
    try:
        payload = json.loads(input_text)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    for key in _PATH_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _is_checkable(path: str) -> bool:
    """Whether the verification list contains a tool that checks this file.

    `posixpath` rather than `os.path` so a Windows-recorded trace is read the
    same way on the Linux box that labels it. Separators are not normalised
    first, and a mutation proved that would be dead code: for the suffix to
    land in the set, the last dot must be inside the last path component, and
    then both readings agree. Where they disagree (`dir.pyile` reads as
    `.pyile` un-normalised) neither reading is in the set, so the verdict is
    the same. Case is folded because `.PY` is the same language.
    """
    return _posix_splitext(path)[1].casefold() in CHECKABLE_SUFFIXES


def find_unverified_edit(trace: Trace) -> UnverifiedEditResult:
    """A session that changed checkable code and ran no check (prereg §3).

    Reads tool spans only. LLM spans have no tool name to match, and the rule
    is about actions taken rather than about what was said.
    """
    edit_count = 0
    checkable: list[str] = []
    verification_count = 0

    for span in trace.spans:
        if span.span_kind != "tool":
            continue
        tool = span.agent_or_node_id
        if tool in EDIT_TOOLS:
            edit_count += 1
            path = _target_path(span.input_text)
            if path and _is_checkable(path):
                checkable.append(path)
        elif tool in SHELL_TOOLS and _VERIFICATION.search(span.input_text or ""):
            verification_count += 1

    return UnverifiedEditResult(
        flagged=bool(checkable) and verification_count == 0,
        checkable_edit_count=len(checkable),
        verification_count=verification_count,
        edit_count=edit_count,
        checkable_paths=sorted(set(checkable)),
    )
