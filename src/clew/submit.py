"""src/clew/submit.py — send finished agent sessions to the analyzer.

The rules here are not choices this module gets to make. They are frozen in
the session close rule preregistration, and the numbers below are the ones that
document fixed (see RULE_URL):

    R1  a session is finished when its last recorded event is CLOSE_AFTER
        minutes old (240, from §5 — 60 was measured and rejected at 29%)
    R2  a session is submitted once and never again, whatever the file does
        afterwards (a grown file has a different payload hash, so the database
        constraint would not catch the second copy)
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
from pathlib import Path

# docs/SESSION_CLOSE_RULE_PREREG.md §5. Changing this changes what the
# baseline is made of, so it changes there first.
CLOSE_AFTER = timedelta(minutes=240)

DEFAULT_ROOT = Path.home() / ".claude" / "projects"
DEFAULT_ENDPOINT = "https://jeonsewon--boxdawn-analyzer-web.modal.run/analyze"

# The ledger is R2. Losing it means resubmitting everything, so it lives next
# to the config rather than in a cache directory something might clean.
LEDGER_PATH = Path.home() / ".clew" / "submitted.json"

# Keys live here and nowhere else. Deliberately NOT clew.yaml: that file is
# discovered by walking up from the trace, which means it is a file people keep
# in a repository, and a repository is the one place a key must never be.
CREDENTIALS_PATH = Path.home() / ".clew" / "credentials.yaml"

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


def pending(root: Path, now: datetime, ledger: dict,
            close_after: timedelta = CLOSE_AFTER) -> list[Path]:
    """Files that are closed (R1) and not already sent (R2)."""
    return [p for p in discover(root)
            if _unsent(ledger.get(str(p))) and is_closed(p, now, close_after)]


# ── credentials ────────────────────────────────────────────────────────────

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
                return (f"{CREDENTIALS_PATH} did not parse as `key: value` — YAML "
                        f"needs a space after the colon, as in "
                        f"`api_key: {KEY_PREFIX}…`")
            return (f"{CREDENTIALS_PATH} has no `api_key:` line — the file needs "
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

    ingest = report.get("ingest") or {}
    return {
        "ok": True,
        "trace_id": report.get("trace_id"),
        "stored": bool(ingest.get("stored")),
        "reason": ingest.get("reason"),
    }


# ── the run ────────────────────────────────────────────────────────────────

def _summary(paths: list[Path]) -> str:
    total = sum(p.stat().st_size for p in paths)
    return f"{len(paths)} session(s), {total / 1024 / 1024:.1f} MB"


def run(root: Path = DEFAULT_ROOT,
        endpoint: str = DEFAULT_ENDPOINT,
        dry_run: bool = False,
        pace_seconds: float = 2.0,
        limit: int | None = None,
        now: datetime | None = None,
        ledger_path: Path = LEDGER_PATH,
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
    queued = pending(root, now, ledger)

    if limit is not None:
        queued = queued[:limit]

    if not queued:
        out(f"nothing to submit ({len(ledger)} already sent)")
        return 0

    if dry_run:
        out(f"would submit {_summary(queued)}")
        for path in queued:
            last = last_activity(path)
            age = (now - last).total_seconds() / 3600 if last else 0
            out(f"  {path.name}  {path.stat().st_size / 1024:.0f} KB  "
                f"idle {age:.1f}h")
        return 0

    key = read_key()
    if not key:
        out(f"no key: {key_problem()}")
        return 2
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
        # resend what it already sent (R2).
        ledger[str(path)] = {**result, "submitted_at": now.isoformat()}
        save_ledger(ledger, ledger_path)

        if result.get("stored"):
            stored += 1
            out(f"  {path.name}  stored")
        else:
            failed += 1
            out(f"  {path.name}  NOT stored — {result.get('reason')}")

    out(f"done: {stored} stored, {failed} not stored")
    return 0 if failed == 0 else 1
