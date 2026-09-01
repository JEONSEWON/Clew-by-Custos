# Spec: docs/LIVE_ALERT_AUTHOR_ONLY_DELIVERY_PREREG.md (Rule 8 prereg).
"""src/clew/live_send.py — the one place a finding can leave this machine.

`live.py` does the watching and does not import this. That separation is the
shipped form of the shadow guarantee: the watcher cannot send, a test asserts
it by parsing the module's imports, and turning delivery on means calling this
from the CLI rather than editing the detector.

What crosses the wire is a session key, a tool name and two counts. Never a
trace, never a path, never the content of anything. The endpoint's own tests
assert the same thing from the other side, and the reason is in §1 of the
pre-registration: a live alert that uploads is the slow path with extra steps.

**Off unless asked.** No flag, no send -- and the server refuses anyway for a
project that is not on its allow-list, so the two halves fail closed
independently. That redundancy is deliberate: a client bug and a server bug
have to coincide for a mail nobody chose.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from clew.submit import DEFAULT_ENDPOINT, read_key

ENV_FLAG = "CLEW_LIVE_ALERTS"

# The session key the server dedupes on. `(session, signal)` is capped for
# ever, so this has to be stable across polls and across restarts, and it must
# not be the path -- a path names a directory layout and this is the one place
# something leaves the machine.
_KEY_PREFIX_LEN = 32


@dataclass
class SendResult:
    """What happened, for the log. Never raises out of `send_finding`."""

    attempted: bool = False
    ok: bool = False
    reason: str = ""
    recorded: bool = False
    delivery_mode: str = ""


def enabled(flag: bool | None = None) -> bool:
    """Prereg §2 -- off unless the flag or the env var says otherwise."""
    if flag is True:
        return True
    if flag is False:
        return False
    return os.environ.get(ENV_FLAG) == "1"


def session_key(path: Path) -> str:
    """A stable, opaque name for one session file.

    sha256 of the file name, truncated. The name is already a uuid Claude Code
    assigned, so this hides nothing that matters -- what it does is keep the
    directory layout off the wire, and keep the key the same length whatever
    the local path looks like.
    """
    return sha256(path.name.encode("utf-8")).hexdigest()[:_KEY_PREFIX_LEN]


def _endpoint(analyze_endpoint: str) -> str:
    return analyze_endpoint.rsplit("/", 1)[0] + "/live-finding"


def send_finding(finding, *, flag: bool | None = None, key: str | None = None,
                 endpoint: str = DEFAULT_ENDPOINT, timeout: float = 15.0,
                 opener=None) -> SendResult:
    """Tell the server about one finding. Returns what happened; never raises.

    A failure here must not stop the watcher: the finding is already recorded
    locally, and the local record is what the measurement is made of. Losing
    the mail is worse than losing nothing and better than losing the pass.
    """
    if not enabled(flag):
        return SendResult(reason="disabled")

    api_key = key if key is not None else read_key()
    if not api_key:
        return SendResult(reason="no_key")

    body = json.dumps({
        "session_key": session_key(Path(finding.session)),
        "tool": getattr(finding, "tool", "") or "",
        "occurrences": int(getattr(finding, "candidates_seen", 0) or 0),
        "latency_seconds": round(finding.latency_seconds(), 3),
    }).encode("utf-8")

    request = urllib.request.Request(
        _endpoint(endpoint), data=body, method="POST",
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
    )
    send = opener or urllib.request.urlopen
    try:
        with send(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return SendResult(attempted=True, reason=f"http_{exc.code}")
    except Exception as exc:                                      # noqa: BLE001
        return SendResult(attempted=True, reason=type(exc).__name__)

    return SendResult(
        attempted=True,
        ok=bool(payload.get("ok")),
        reason=str(payload.get("reason") or ""),
        recorded=bool(payload.get("recorded")),
        delivery_mode=str(payload.get("delivery_mode") or ""),
    )
