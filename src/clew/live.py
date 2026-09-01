"""src/clew/live.py — the fast path: watch a running session, record a finding.

The preregistration is at PREREG_URL below. The slow path uploads a session
and the server answers in 43 minutes, which is fine for a spending cap and no
use for a failure. This module is the other half: the detector already runs on
this machine, so a repeat can be found while the session is still open.

Three properties this module has to keep, all of them from the prereg:

    §2  nothing crosses the wire. There is no network call here, and §8 keeps
        it that way until P3 is measured. Shadow means recorded locally and
        nothing sent -- not "sent quietly".
    §4  the verdict is the batch verdict. Confirmation is
        `cascade.confirm_pair`, the same function the analyzer runs, with the
        same phi and the same N handed in by the caller.
    §3.2 one finding per session, ever, and at most three an hour per project.
        A machine running ten agents at once must not produce ten alerts.

The trace is re-read from the top on every poll rather than tailed. That is a
cost decision with a measurement behind it: a poll is 0.50 s at the median and
32 s on the largest session on this machine, so `sweep` reports how long it
took and `watch` sleeps a multiple of that, which bounds the watcher's share of
a core no matter how big the session gets.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from clew.detect.cascade import confirm_pair
from clew.detect.structural import find_candidates
from clew.model import Span, Trace
from clew.submit import _GITHUB_BASE, CLOSE_AFTER, discover, last_activity

if TYPE_CHECKING:
    from clew.config import ResolvedTools

# A pip-install user has no docs/ tree, so the prereg is named as a URL.
PREREG_URL = f"{_GITHUB_BASE}/docs/LIVE_FAILURE_ALERT_PREREG.md"

# FM-1.3, step repetition. One name, because the cap in §3.2 is per
# `(session, signal)` and a signal that is spelled two ways is two caps.
SIGNAL_REPEAT = "repeat"

FINDINGS_PATH = Path.home() / ".clew" / "live_findings.json"
WATCH_LOG_PATH = Path.home() / ".clew" / "watch.log"

# §3.2. Across sessions, per project, on a rolling hour.
PROJECT_HOURLY_CAP = 3

# Floor between polls, and the multiple of the last scan that overrides it. The
# floor is what P2 is spent on (median under 3 minutes from the second span);
# the multiple is what keeps a 32-second scan from running back-to-back.
POLL_SECONDS = 60
SCAN_BACKOFF = 4


@dataclass(frozen=True)
class Finding:
    """One recorded repeat. Shadow: `delivered` is False and nothing sends it."""

    project: str
    session: str
    signal: str
    origin_span_id: str
    candidate_span_id: str
    occurred_at: str      # candidate.start_time -- when the repeat happened
    recorded_at: str      # when this watcher noticed. P2 is the gap.
    candidates_seen: int
    # The tool the repeat was on. Recorded because the restriction to
    # idempotent tools makes it the thing a reader most wants to see, and
    # because it is what a mail can say without naming a file. Defaulted so a
    # ledger written before this field is still readable.
    tool: str = ""
    delivered: bool = False

    def latency_seconds(self) -> float:
        return (
            datetime.fromisoformat(self.recorded_at)
            - datetime.fromisoformat(self.occurred_at)
        ).total_seconds()


# ── detection ──────────────────────────────────────────────────────────────

def is_live(path: Path, now: datetime, close_after: timedelta = CLOSE_AFTER) -> bool:
    """Whether the session is still running, by the same clock `submit` uses.

    §3.2: a session that already ended is the slow path's job. The two paths
    partition on the one rule, so a session cannot fall between them.
    """
    last = last_activity(path)
    return last is not None and (now - last) < close_after


def alertable(candidate: Span, tools: "ResolvedTools | None" = None) -> bool:
    """Whether a confirmed pair on this tool may interrupt a person.

    IDEMPOTENT_TRIGGER_PREREG §2. Only calls that cannot change the world:
    for those, "same input, nothing wrote to the target, same output" leaves no
    room for the second call to have informed anything. For a shell command an
    identical output can be the command succeeding at what it does -- a
    `Stop-Process` guarded by `if ($c)` prints `stopped` whether or not
    anything was listening -- and the trace cannot tell that from waste.
    Measured: precision 1.0000 on 21 idempotent pairs, 0.0000 on 7 shell pairs.

    The category is not a list written for this. `clew.config` has classified
    tools into four categories since July and `idempotent` is one of them, so
    the boundary was already drawn and shipped before any of this was
    measured. `tools` carries the user's `clew.yaml`, so somebody who declares
    their own read tool gets alerts about it -- the correct consequence of the
    declaration they made.

    ★ This narrows what interrupts a person. It does not narrow what is
    measured: the batch path, every waste rate and every stored figure still
    see all tools (§3).
    """
    from clew.config import builtin_tools                        # noqa: PLC0415

    snapshot = tools if tools is not None else builtin_tools()
    return candidate.agent_or_node_id in snapshot.idempotent


def first_confirmed(
    trace: Trace, embedder: object, n: int, phi: float,
    tools: "ResolvedTools | None" = None,
) -> tuple[Span, Span] | None:
    """The earliest confirmed, alertable repeat in the trace, or None.

    Earliest by the candidate's start_time, not by the order
    `find_candidates` happens to group in: §3.2 fires on "the first confirmed
    pair", and the finding's own timestamp is what P2 measures against.

    Non-alertable candidates are skipped before confirmation rather than after,
    so a session full of repeated shell calls costs nothing to look at.
    Confirmation still stops at the first hit.
    """
    boundaries = list(trace.metadata.get("compact_boundaries", []) or [])
    pairs = sorted(find_candidates(trace, n), key=lambda pair: pair[1].start_time)
    for origin, candidate in pairs:
        if not alertable(candidate, tools):
            continue
        if confirm_pair(origin, candidate, embedder, phi, boundaries):
            return origin, candidate
    return None


def scan(
    path: Path,
    project: str,
    embedder: object,
    n: int,
    phi: float,
    now: datetime,
    tools: "ResolvedTools | None" = None,
) -> Finding | None:
    """Read one session file and return a finding, or None.

    Ingest only -- no `preprocess_trace`, which is not run on Claude Code
    traces anywhere else either.
    """
    from clew.ingest.claude_code import ingest_claude_code_jsonl

    trace = ingest_claude_code_jsonl(path)
    candidates = find_candidates(trace, n)
    hit = first_confirmed(trace, embedder, n, phi, tools)
    if hit is None:
        return None
    origin, candidate = hit
    return Finding(
        project=project,
        session=str(path),
        signal=SIGNAL_REPEAT,
        origin_span_id=origin.span_id,
        candidate_span_id=candidate.span_id,
        occurred_at=candidate.start_time.isoformat(),
        recorded_at=now.isoformat(),
        candidates_seen=len(candidates),
        tool=candidate.agent_or_node_id,
    )


# ── the shadow ledger, and the two caps it exists to enforce ───────────────

def load_findings(path: Path = FINDINGS_PATH) -> list[Finding]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for row in raw.get("findings", []):
        try:
            out.append(Finding(**row))
        except TypeError:
            # A row this version does not understand is kept out of the caps
            # rather than crashing the watcher. It stays in the file.
            continue
    return out


def save_findings(findings: list[Finding], path: Path = FINDINGS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"findings": [asdict(f) for f in findings]}, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


def already_found(findings: list[Finding], session: str, signal: str) -> bool:
    """§3.2 -- one per `(session, signal)`, ever."""
    return any(f.session == session and f.signal == signal for f in findings)


def hourly_room(
    findings: list[Finding],
    project: str,
    now: datetime,
    cap: int = PROJECT_HOURLY_CAP,
) -> bool:
    """§3.2 -- at most `cap` per project on the hour behind `now`."""
    since = now - timedelta(hours=1)
    recent = [
        f for f in findings
        if f.project == project and datetime.fromisoformat(f.recorded_at) > since
    ]
    return len(recent) < cap


# ── one pass over everything that is running ───────────────────────────────

@dataclass
class SweepResult:
    scanned: int = 0
    recorded: int = 0
    suppressed_hourly: int = 0
    seconds: float = 0.0


def sweep(
    root: Path,
    project: str,
    embedder: object,
    n: int,
    phi: float,
    now: datetime,
    findings: list[Finding],
    close_after: timedelta = CLOSE_AFTER,
    on_finding=None,
    tools: "ResolvedTools | None" = None,
) -> SweepResult:
    """Scan every live session under `root` once, appending to `findings`.

    Sessions are visited in path order so that which three of ten get through
    the hourly cap is the same on a re-run rather than filesystem luck.
    """
    started = time.perf_counter()
    result = SweepResult()
    for path in discover(root):
        if already_found(findings, str(path), SIGNAL_REPEAT):
            continue
        if not is_live(path, now, close_after):
            continue
        result.scanned += 1
        try:
            finding = scan(path, project, embedder, n, phi, now, tools)
        except Exception:                                          # noqa: BLE001
            # One unreadable session must not stop the watcher on the others.
            # A session being written to right now is the ordinary case here.
            continue
        if finding is None:
            continue
        # Stamped when the scan finished, not when the pass began. P2 is the
        # gap between the repeat and this stamp, and a scan is 0.5 s at the
        # median but 32 s on the largest session here -- charging that to the
        # sweep's start time would report a latency nobody experienced.
        finding = replace(
            finding,
            recorded_at=(
                now + timedelta(seconds=time.perf_counter() - started)
            ).isoformat(),
        )
        if not hourly_room(findings, project, now):
            result.suppressed_hourly += 1
            continue
        findings.append(finding)
        result.recorded += 1
        if on_finding is not None:
            on_finding(finding)
    result.seconds = time.perf_counter() - started
    return result


def watch(
    targets: list[tuple[str, Path]],
    embedder: object,
    n: int,
    phi: float,
    findings_path: Path = FINDINGS_PATH,
    poll_seconds: int = POLL_SECONDS,
    once: bool = False,
    on_finding=None,
    on_sweep=None,
    on_cycle=None,
    tools: "ResolvedTools | None" = None,
) -> None:
    """Poll every project until interrupted. Records; sends nothing.

    One `(project, root)` per codebase, the same split `submit` uses, because
    the hourly cap is per project and a blended root would make one busy
    codebase spend another's allowance.

    `on_cycle` runs once per pass, after the ledger is written. It exists so
    that delivery is a step over the ledger rather than a branch off
    `on_finding`: the retry and the first attempt are then the same call, and a
    send that fails is simply still in the file next pass. This module still
    cannot send -- the callback is the caller's, and a test parses these
    imports to keep it that way.
    """
    while True:
        findings = load_findings(findings_path)
        before = len(findings)
        elapsed = 0.0
        for project, root in targets:
            result = sweep(
                root, project, embedder, n, phi,
                datetime.now(timezone.utc), findings, on_finding=on_finding,
                tools=tools,
            )
            elapsed += result.seconds
            if on_sweep is not None:
                on_sweep(project, result)
        if len(findings) != before:
            save_findings(findings, findings_path)
        if on_cycle is not None:
            # After the write, never before: whatever this pass recorded is on
            # disk, so a delivery step reads a complete ledger, and a crash
            # between the two loses nothing that is not offered again next
            # pass.
            on_cycle()
        if once:
            return
        time.sleep(max(poll_seconds, SCAN_BACKOFF * elapsed))
