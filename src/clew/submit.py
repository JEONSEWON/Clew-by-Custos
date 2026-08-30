"""src/clew/submit.py — send finished agent sessions to the analyzer.

The rules here are not choices this module gets to make. They are frozen in
the session close rule preregistration, and the numbers below are the ones that
document fixed (see RULE_URL):

    R1  a session is finished when its last recorded event is CLOSE_AFTER
        minutes old (20, from the latency amendment; 240 originally)
    R2  a session is submitted again when it has recorded events past what was
        last sent, and the server replaces the row rather than adding one
        (latency amendment §2; before that a resubmission became a second row
        because a grown file has a different payload hash)
    R3  discovery is recursive, because sub-agent traces sit a directory
        deeper and are 13 of 84 files on the measured corpus

Analysis happens on the server. This module uploads bytes and records what
came back; it does not import a detector, and it must not grow one. Keeping it
thin is what lets every submission be measured by the same analyzer version,
which is the whole basis for comparing a project against its own past.

No third-party HTTP client: urllib is enough for one multipart POST, and a
submission client that drags in dependencies stops being cheap to install.
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from typing import NamedTuple
from pathlib import Path

# docs/SESSION_CLOSE_RULE_PREREG.md §5. Changing this changes what the
# baseline is made of, so it changes there first.
# Latency amendment §2. The original 240 was not a fact about sessions: it was
# how long you had to wait for "it will not grow again" to be true often enough,
# because a grown file used to become a second row. Migration 0018 made
# resubmission replace instead of add, so the wait has nothing left to do.
CLOSE_AFTER = timedelta(minutes=20)

DEFAULT_ROOT = Path.home() / ".claude" / "projects"
DEFAULT_ENDPOINT = "https://jeonsewon--boxdawn-analyzer-web.modal.run/analyze"

# The ledger is R2. Losing it means resubmitting everything, so it lives next
# to the config rather than in a cache directory something might clean.
LEDGER_PATH = Path.home() / ".clew" / "submitted.json"

# Keys live here and nowhere else. Deliberately NOT clew.yaml: that file is
# discovered by walking up from the trace, which means it is a file people keep
# in a repository, and a repository is the one place a key must never be.
CREDENTIALS_PATH = Path.home() / ".clew" / "credentials.yaml"

# One entry per codebase: {project, root, api_key}. Present only when the
# machine works on more than one, which is the case this file exists for.
PROJECTS_PATH = Path.home() / ".clew" / "projects.yaml"

# When unattended submission was switched on. Sessions that had already
# gone quiet by then are not swept up: see `Target.since`.
AUTO_STATE_PATH = Path.home() / ".clew" / "auto_submit.json"
AUTO_LOG_PATH = Path.home() / ".clew" / "auto_submit.log"

# Where the rule actually lives, in a form a pip-install user can open. A
# local docs/ path is only real inside a clone of the repository.
_GITHUB_BASE = "https://github.com/boxdawn/boxdawn/blob/main"
RULE_URL = f"{_GITHUB_BASE}/docs/SESSION_CLOSE_RULE_PREREG.md"

KEY_ENV = "BOXDAWN_API_KEY"
KEY_PREFIX = "bdk_"


# ── discovery and eligibility ──────────────────────────────────────────────

def discover(root: Path) -> list[Path]:
    """Every trace file under `root`, recursively (R3)."""
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*.jsonl") if p.is_file())


def last_activity(path: Path) -> datetime | None:
    """Most recent in-file timestamp, or None if the file carries none.

    The rule is written against recorded events, not file mtime, because mtime
    moves for reasons that have nothing to do with the session (a backup, a
    sync, an editor). A file with no timestamps cannot be judged by this rule
    and is skipped rather than guessed at.
    """
    latest = None
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    stamp = json.loads(line).get("timestamp")
                except (ValueError, AttributeError):
                    continue
                if not stamp:
                    continue
                try:
                    when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
                except ValueError:
                    continue
                if latest is None or when > latest:
                    latest = when
    except OSError:
        return None
    return latest


def is_closed(path: Path, now: datetime, close_after: timedelta = CLOSE_AFTER) -> bool:
    """R1 — quiet for long enough to call finished."""
    last = last_activity(path)
    return last is not None and (now - last) >= close_after


# ── ledger (R2) ────────────────────────────────────────────────────────────

def load_ledger(path: Path = LEDGER_PATH) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A missing or corrupt ledger must not silently mean "submit
        # everything again" without the operator seeing it. The caller decides;
        # here an unreadable ledger is simply empty.
        return {}


def save_ledger(ledger: dict, path: Path = LEDGER_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(ledger, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _unsent(entry: object) -> bool:
    """True when nothing of this file ever reached the server.

    R2 counts submissions, and what it is for is that one `trace_id` never
    becomes two `run` rows. An entry recording `ok: False` is a request that
    failed in transport or came back an HTTP error: no row was created, so
    sending it again cannot double count. Treating that as sent loses the
    session for good, because nothing ever revisits a file the ledger names.

    Anything else is left alone -- including `ok: True, stored: False`, where
    the server did receive and analyze the trace and then declined to store
    it. That was its decision, not a lost request, and re-running a paid
    analysis will not change it. Ledger entries written before `ok` existed
    are also left alone.
    """
    return entry is None or (isinstance(entry, dict) and entry.get("ok") is False)


def _has_new_content(path: Path, entry: object) -> bool:
    """True when the file has recorded events past what was last sent.

    Shortening the wait without this makes things worse rather than better: a
    session would be sent after 20 quiet minutes and then, because the ledger
    remembers the path, never sent again. The stored measurement would be an
    early fragment of a session that went on for hours.

    Compared on the last in-file timestamp, not file size or mtime, for the
    reason `last_activity` gives: mtime moves for a backup or a sync, and size
    is a proxy for the thing this can just read directly.

    An entry with no `sent_through` was written before this field existed.
    Those are left alone. Treating them as new would resend every session on
    the machine the first time an upgraded client runs.
    """
    if not isinstance(entry, dict):
        return False
    stamp = entry.get("sent_through")
    if not stamp:
        return False
    try:
        sent_through = datetime.fromisoformat(str(stamp))
    except ValueError:
        return False
    last = last_activity(path)
    return last is not None and last > sent_through


def pending(root: Path, now: datetime, ledger: dict,
            close_after: timedelta = CLOSE_AFTER,
            since: datetime | None = None) -> list[Path]:
    """Files that are closed (R1) and not already sent (R2).

    `since` drops sessions whose last write predates it. Unattended runs pass
    the moment submission was switched on, so turning it on does not sweep up
    the machine's whole history behind the operator. Backfilled sessions all
    land on the day they were analysed, so a hundred of them make one
    artificial mound -- and rule A compares a day against the previous one.
    """
    out = []
    for p in discover(root):
        entry = ledger.get(str(p))
        if not (_unsent(entry) or _has_new_content(p, entry)):
            continue
        if not is_closed(p, now, close_after):
            continue
        if since is not None:
            last = last_activity(p)
            if last is None or last < since:
                continue
        out.append(p)
    return out


# ── credentials ────────────────────────────────────────────────────────────

class Target(NamedTuple):
    """One codebase, its trace folder, and the key that names it downstream.

    `project` is carried for messages only; the server binds a trace to a
    project through the key, not through this name.
    """

    project: str
    root: Path
    api_key: str | None


def load_targets(
    projects_path: Path = PROJECTS_PATH,
    default_root: Path = DEFAULT_ROOT,
) -> list[Target]:
    """Where to submit from, and under which key.

    Without `projects.yaml` this is what it always was: the whole of
    `~/.claude/projects` under one key.

    With it, one target per codebase. That split is not a convenience. The
    alert rule compares a day against the previous day *within one baseline*,
    and a project is one baseline. Sending two codebases under one key makes
    the rate answer "which project did I work on today" instead of "how
    wasteful was the work", which is the noise the split exists to remove.
    Switching submission on without this would fill the baseline we are trying
    to open rule A against.

    A malformed file raises rather than quietly falling back to the single-root
    path: falling back would send every codebase under whichever key came
    first, which is the exact blending above, arrived at by accident.
    """
    try:
        raw = projects_path.read_text(encoding="utf-8")
    except OSError:
        return [Target("default", default_root, read_key())]

    import yaml

    entries = yaml.safe_load(raw) or []
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{projects_path}: expected a non-empty list of entries")

    targets: list[Target] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"{projects_path}: entry is not a mapping: {entry!r}")
        missing = [k for k in ("project", "root", "api_key") if not entry.get(k)]
        if missing:
            raise ValueError(
                f"{projects_path}: entry {entry.get('project', '?')!r} "
                f"is missing {missing}"
            )
        targets.append(Target(
            str(entry["project"]),
            Path(str(entry["root"])).expanduser(),
            str(entry["api_key"]).strip(),
        ))

    roots = [t.root for t in targets]
    if len(set(roots)) != len(roots):
        raise ValueError(
            f"{projects_path}: two entries share a root, so the same sessions "
            f"would be sent under two keys and counted twice"
        )
    return targets


# ── unattended state ───────────────────────────────────────────────────────

def read_auto_state(path: Path = AUTO_STATE_PATH) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_auto_state(state: dict, path: Path = AUTO_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def installed_at(path: Path = AUTO_STATE_PATH) -> datetime | None:
    """The watermark unattended runs submit after. None when never installed."""
    raw = read_auto_state(path).get("installed_at")
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def read_key() -> str | None:
    """Environment first, then the credentials file.

    Environment first because CI and containers cannot be handed a file, and
    that is exactly where unattended submission belongs.
    """
    from_env = (os.environ.get(KEY_ENV) or "").strip()
    if from_env:
        return from_env
    try:
        import yaml
        loaded = yaml.safe_load(CREDENTIALS_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, ImportError, ValueError):
        return None
    key = loaded.get("api_key") if isinstance(loaded, dict) else None
    return str(key).strip() if key else None


def key_problem() -> str:
    """Why there is no key, in the words of the thing that is actually wrong.

    `read_key` returns None for five different reasons and the old message named
    one of them, so a user whose file existed and whose key was in it was told
    to write the file they had already written. The case that produced this:
    `api_key:bdk_...` with no space after the colon. YAML requires the space, so
    the line parses as one plain string rather than a mapping, `read_key`'s
    isinstance guard turns that into None, and nothing anywhere says the word
    "space". Nobody suspects whitespace.
    """
    if CREDENTIALS_PATH.exists():
        try:
            raw = CREDENTIALS_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            return f"cannot read {CREDENTIALS_PATH} ({type(exc).__name__})"
        try:
            import yaml
        except ImportError:
            return f"{CREDENTIALS_PATH} exists but pyyaml is not installed"
        try:
            loaded = yaml.safe_load(raw)
        except Exception:  # noqa: BLE001 - any parse failure, same advice
            return f"{CREDENTIALS_PATH} is not valid YAML"
        if not isinstance(loaded, dict):
            # Two different mistakes land here and they deserve different
            # sentences: a diagnosis that names the wrong cause still costs the
            # reader a guess, even when the remedy shown happens to be right.
            import re
            if re.search(r"^\s*api_key:\S", raw, re.M):
                # The whitespace case, named as whitespace. Nobody suspects it.
                return (f"{CREDENTIALS_PATH} did not parse as `key: value`. YAML "
                        f"needs a space after the colon, as in "
                        f"`api_key: {KEY_PREFIX}…`")
            return (f"{CREDENTIALS_PATH} has no `api_key:` line. The file needs "
                    f"`api_key: {KEY_PREFIX}…`, not the key on its own")
        if "api_key" not in loaded:
            return f"{CREDENTIALS_PATH} has no `api_key` entry"
        if not str(loaded.get("api_key") or "").strip():
            return f"`api_key` in {CREDENTIALS_PATH} is empty"
        return f"`api_key` in {CREDENTIALS_PATH} could not be read"

    return f"set {KEY_ENV} or write `api_key: {KEY_PREFIX}…` to {CREDENTIALS_PATH}"


def key_source() -> str | None:
    """Which source a key would come from, when both could supply one.

    Only speaks up for the ambiguous case, because that is the one that costs an
    afternoon: the environment wins over the file (`read_key`), so a stale
    variable silently outranks a freshly written credential — and deleting the
    variable does not reach a process that is already running, which includes
    the shell the command is typed into. Both symptoms are a submission
    rejected with a key the user believes they replaced.
    """
    if not (os.environ.get(KEY_ENV) or "").strip():
        return None
    if not CREDENTIALS_PATH.exists():
        return None
    return (f"using {KEY_ENV} from the environment; {CREDENTIALS_PATH} also has "
            f"a key and is not being read. A variable removed after this shell "
            f"started is still set inside it")


# ── submission ─────────────────────────────────────────────────────────────

def _multipart(path: Path) -> tuple[str, bytes]:
    boundary = "----boxdawn" + uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return boundary, head + path.read_bytes() + tail


def _failure_detail(exc: urllib.error.HTTPError) -> dict:
    """What the server said about its own failure, and nothing more.

    The server puts an `error_id` in the body precisely so a user report can be
    matched to a line in its log; recording only `http_500` throws away the one
    thing that makes the failure diagnosable. A `detail` that is a plain string
    is the server's own sentence and is kept, truncated. A `detail` that is an
    object may carry the analyzer's stderr, so only its `error_id` is taken --
    a local ledger is not the place to keep a copy of trace contents.
    """
    try:
        body = json.loads(exc.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - a body we cannot read is not a crash
        return {}
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict) and detail.get("error_id"):
        return {"error_id": str(detail["error_id"])[:64]}
    if isinstance(detail, str):
        return {"detail": detail[:200]}
    # The background path refuses with a top-level reason rather than a detail
    # envelope, and that reason is the useful half: `bad_key` says what to fix
    # where `http_401` does not.
    if isinstance(body, dict) and isinstance(body.get("reason"), str):
        return {"detail": body["reason"][:200]}
    return {}


def submit_file(path: Path, key: str, endpoint: str = DEFAULT_ENDPOINT,
                timeout: int = 600) -> dict:
    """Upload one trace. Returns what the ledger should record about it.

    Never raises: one unreachable server must not stop the rest of the run,
    and a failed submission is a fact worth recording rather than a crash.
    """
    boundary, body = _multipart(path)
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout,
                                    context=ssl.create_default_context()) as response:
            report = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"ok": False, "reason": f"http_{exc.code}", **_failure_detail(exc)}
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        # The key is in the request headers. Record the kind of failure, never
        # the request.
        return {"ok": False, "reason": f"transport_{type(exc).__name__}"}

    # 202 means the server took the trace and will analyze it without holding
    # this connection open. That is the only path for an unattended client:
    # analysis time follows cumulative context, which has no natural cap, so a
    # ceiling that fits this machine's traces refuses somebody else's.
    if isinstance(report, dict) and report.get("call_id"):
        return {"ok": True, "pending": True, "call_id": report["call_id"]}

    ingest = report.get("ingest") or {}
    return {
        "ok": True,
        "trace_id": report.get("trace_id"),
        "stored": bool(ingest.get("stored")),
        "reason": ingest.get("reason"),
    }


def _status_url(endpoint: str, call_id: str) -> str:
    return f"{endpoint.rsplit('/', 1)[0]}/status/{call_id}"


def poll_status(call_id: str, endpoint: str = DEFAULT_ENDPOINT,
                interval: float = 5.0, sleep=None) -> dict:
    """Wait for a spawned analysis and return what the ledger should record.

    Each request is short. Nothing here bounds how long the analysis may take,
    which is the whole reason the work was spawned: the ceiling existed because
    a caller was holding a socket, not because some traces are unanalysable.

    Transport failures are retried rather than reported: losing a result to one
    dropped packet would leave a stored run the ledger calls a failure.
    """
    import time
    sleep = sleep or time.sleep

    url = _status_url(endpoint, call_id)
    consecutive_transport_errors = 0
    while True:
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=60,
                                        context=ssl.create_default_context()) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return {"ok": False, "reason": f"http_{exc.code}", "call_id": call_id,
                    **_failure_detail(exc)}
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            consecutive_transport_errors += 1
            if consecutive_transport_errors >= 5:
                return {"ok": True, "pending": True, "call_id": call_id,
                        "reason": f"transport_{type(exc).__name__}"}
            sleep(interval)
            continue
        consecutive_transport_errors = 0

        if not body.get("done"):
            sleep(interval)
            continue

        if not body.get("ok"):
            detail = body.get("detail")
            reason = (detail.get("error") if isinstance(detail, dict)
                      else None) or f"job_{body.get('status')}"
            out = {"ok": False, "reason": reason, "call_id": call_id}
            if isinstance(detail, dict) and detail.get("error_id"):
                out["error_id"] = str(detail["error_id"])[:64]
            return out

        ingest = body.get("ingest") or {}
        return {
            "ok": True,
            "call_id": call_id,
            "trace_id": body.get("trace_id"),
            "stored": bool(ingest.get("stored")),
            "reason": ingest.get("reason"),
        }


# ── the run ────────────────────────────────────────────────────────────────

def _summary(paths: list[Path]) -> str:
    total = sum(p.stat().st_size for p in paths)
    return f"{len(paths)} session(s), {total / 1024 / 1024:.1f} MB"


def resolve_pending(ledger: dict, endpoint: str = DEFAULT_ENDPOINT,
                    ledger_path: Path = LEDGER_PATH,
                    interval: float = 5.0, out=print) -> tuple[int, int]:
    """Finish calls a previous run accepted but never heard the answer for.

    An interrupted poll leaves a trace that the server has and the ledger does
    not describe. Resending it would be wrong twice: the analysis is already
    paid for, and if the file has grown since, the payload hash differs and the
    database's duplicate guard would not catch the second copy.
    """
    items = [(k, v) for k, v in ledger.items()
             if isinstance(v, dict) and v.get("pending") and v.get("call_id")]
    if not items:
        return 0, 0

    out(f"resolving {len(items)} accepted earlier")
    stored = failed = 0
    for key, entry in items:
        result = poll_status(entry["call_id"], endpoint, interval)
        ledger[key] = {**entry, **result}
        if not result.get("pending"):
            ledger[key].pop("pending", None)
        save_ledger(ledger, ledger_path)
        name = Path(key).name
        if result.get("stored"):
            stored += 1
            out(f"  {name}  stored")
        elif result.get("pending"):
            out(f"  {name}  still analyzing: {result.get('reason')}")
        else:
            failed += 1
            out(f"  {name}  NOT stored: {result.get('reason')}")
    return stored, failed


def run(root: Path = DEFAULT_ROOT,
        endpoint: str = DEFAULT_ENDPOINT,
        dry_run: bool = False,
        pace_seconds: float = 2.0,
        limit: int | None = None,
        now: datetime | None = None,
        ledger_path: Path = LEDGER_PATH,
        key: str | None = None,
        since: datetime | None = None,
        out=print) -> int:
    """Submit every closed, unsent session. Returns a process exit code.

    A first run is a backfill of the whole machine — 81 of 84 sessions on the
    corpus the rule was measured on (prereg §9). That is why `dry_run` exists
    and why submissions are paced: an operator has to be able to see the size
    of it first, and the analyzer should not be handed a hundred uploads in one
    breath.
    """
    import time

    now = now or datetime.now(timezone.utc)
    ledger = load_ledger(ledger_path)

    # Before looking for new work: anything a previous run accepted and never
    # got an answer for. Doing this first means one command is enough -- the
    # operator does not have to know that a poll was interrupted.
    resolved_stored = resolved_failed = 0
    if not dry_run:
        resolved_stored, resolved_failed = resolve_pending(
            ledger, endpoint, ledger_path, out=out,
        )

    queued = pending(root, now, ledger, since=since)

    if limit is not None:
        queued = queued[:limit]

    if not queued:
        out(f"nothing to submit ({len(ledger)} already sent)")
        return 0 if resolved_failed == 0 else 1

    if dry_run:
        out(f"would submit {_summary(queued)}")
        for path in queued:
            last = last_activity(path)
            age = (now - last).total_seconds() / 3600 if last else 0
            out(f"  {path.name}  {path.stat().st_size / 1024:.0f} KB  "
                f"idle {age:.1f}h")
        return 0

    explicit_key = key
    key = key or read_key()
    if not key:
        out(f"no key: {key_problem()}")
        return 2
    if explicit_key is None:
        ambiguity = key_source()
        if ambiguity:
            out(f"note: {ambiguity}")
    if not key.startswith(KEY_PREFIX):
        # Refuse early rather than sending someone's session token to a server
        # that will reject it anyway.
        out(f"key does not look like a submission key (expected {KEY_PREFIX}…)")
        return 2

    out(f"submitting {_summary(queued)}")
    stored = failed = 0
    for index, path in enumerate(queued):
        if index:
            time.sleep(pace_seconds)
        result = submit_file(path, key, endpoint)
        # Recorded before the next one goes out: an interrupted run must not
        # resend what it already sent (R2). For an accepted-but-unfinished call
        # that means recording the ticket now, ahead of the answer -- a poll
        # interrupted after this line is recoverable, one interrupted before it
        # would resend a trace the server already has.
        # `sent_through` is what makes a later resubmission possible: it
        # records how far into the session this upload reached.
        last_sent = last_activity(path)
        ledger[str(path)] = {
            **result,
            "submitted_at": now.isoformat(),
            "sent_through": last_sent.isoformat() if last_sent else None,
        }
        save_ledger(ledger, ledger_path)

        if result.get("pending"):
            out(f"  {path.name}  accepted, analyzing")
            result = poll_status(result["call_id"], endpoint)
            ledger[str(path)] = {**ledger[str(path)], **result}
            if not result.get("pending"):
                ledger[str(path)].pop("pending", None)
            save_ledger(ledger, ledger_path)

        if result.get("stored"):
            stored += 1
            out(f"  {path.name}  stored")
        elif result.get("pending"):
            out(f"  {path.name}  still analyzing: {result.get('reason')}")
        else:
            failed += 1
            out(f"  {path.name}  NOT stored: {result.get('reason')}")

    stored += resolved_stored
    failed += resolved_failed
    out(f"done: {stored} stored, {failed} not stored")
    return 0 if failed == 0 else 1


def run_all(targets: list[Target],
            endpoint: str = DEFAULT_ENDPOINT,
            dry_run: bool = False,
            pace_seconds: float = 2.0,
            limit: int | None = None,
            now: datetime | None = None,
            ledger_path: Path = LEDGER_PATH,
            since: datetime | None = None,
            out=print) -> int:
    """Run one sweep per codebase. Worst exit code wins.

    The ledger is shared and keyed by absolute path, so two targets cannot
    claim the same session -- and `load_targets` refuses a config where two
    entries name the same root, which is the only way that could happen.

    One target failing does not stop the others: a revoked key on one codebase
    should not cost the day's measurements on the rest.
    """
    worst = 0
    for target in targets:
        if len(targets) > 1:
            out(f"[{target.project}] {target.root}")
        code = run(
            root=target.root, endpoint=endpoint, dry_run=dry_run,
            pace_seconds=pace_seconds, limit=limit, now=now,
            ledger_path=ledger_path, key=target.api_key, since=since, out=out,
        )
        worst = max(worst, code)
    return worst
