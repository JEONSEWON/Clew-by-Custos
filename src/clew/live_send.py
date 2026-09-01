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
from dataclasses import dataclass, replace
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


# ── the drain: one path, tried until it lands ──────────────────────────────
#
# RETRY AMENDMENT §1. `on_finding` used to send, once, at the moment a finding
# was first recorded. A failed send was never offered again, and `delivered`
# existed on the dataclass without anything reading it. P5 wants twenty
# labelled findings in sixty days against an arrival rate of one per three
# days, so one lost send is five per cent of the sample P6 is computed on.
#
# So delivery is a step over the ledger instead: everything undelivered is
# offered, every pass. The first attempt and the retry are the same call, which
# is the point -- there is no first-try branch left that could behave
# differently from the retry. The retry interval is the schedule that already
# exists (the watcher runs every minute); nothing here sleeps or loops.


@dataclass
class DrainResult:
    """What one pass over the ledger did. For the log line."""

    attempted: int = 0
    delivered: int = 0
    pending: int = 0
    last_reason: str = ""


def project_keys(targets=None) -> dict[str, str]:
    """`project -> key`, from the file submission already routes by.

    §0.2 of the amendment. The watcher builds its targets as
    `(project, root)` and drops `Target.api_key`, so without this every
    finding is offered under `read_key()`'s global credential. That file was
    revoked on this machine on 2026-08-30, which makes every send `no_key`; and
    where such a file does exist it is worse than absent, because the server
    binds a finding to a project through the key -- three projects offered
    under one key all record against whichever project that key names, which is
    the blending `load_targets` exists to prevent.
    """
    from clew.submit import load_targets

    if targets is None:
        targets = load_targets()
    return {t.project: t.api_key for t in targets if t.api_key}


def drain(findings_path=None, *, flag: bool | None = None,
          keys: dict | None = None, endpoint: str = DEFAULT_ENDPOINT,
          timeout: float = 15.0, opener=None) -> DrainResult:
    """Offer every undelivered finding to the server, under its project's key.

    Delivered means `ok` is true, which includes `already_recorded`. That is
    the server's answer when it committed the row and the response was lost --
    exactly the case retry exists for -- so treating it as a failure would
    re-offer a finding the server already has, for ever. The unique index
    behind it is also why a retry cannot produce a second mail.

    There is no give-up counter. A finding that can never be delivered is
    offered once a minute for ever, and the run's log line carries `pending`
    and the last reason, so a permanent failure is loud once a minute rather
    than silent once. The alternative is a finding that goes quiet twice.
    """
    from clew import live

    path = live.FINDINGS_PATH if findings_path is None else findings_path
    findings = live.load_findings(path)
    undelivered = [f for f in findings if not f.delivered]
    if not undelivered:
        return DrainResult()

    if not enabled(flag):
        # Shadow means shadow. The backlog is counted so the log can say it,
        # and not one request goes out.
        return DrainResult(pending=len(undelivered), last_reason="disabled")

    if keys is None:
        try:
            keys = project_keys()
        except Exception as exc:                                  # noqa: BLE001
            # A malformed projects.yaml must not lose the pass. Nothing is
            # marked, so the same findings are offered again next minute.
            return DrainResult(pending=len(undelivered),
                               last_reason=f"projects_{type(exc).__name__}")

    result = DrainResult()
    out = []
    for finding in findings:
        if finding.delivered:
            out.append(finding)
            continue
        key = keys.get(finding.project)
        if not key:
            # Not attempted: sending under another project's key would record
            # the finding against the wrong project, which is a wrong row in
            # the baseline rule A is opened against and does not announce
            # itself.
            result.pending += 1
            result.last_reason = "no_project_key"
            out.append(finding)
            continue
        result.attempted += 1
        sent = send_finding(finding, flag=True, key=key, endpoint=endpoint,
                            timeout=timeout, opener=opener)
        if sent.ok:
            result.delivered += 1
            out.append(replace(finding, delivered=True))
        else:
            result.pending += 1
            result.last_reason = sent.reason or "unknown"
            out.append(finding)

    if result.delivered:
        live.save_findings(out, path)
    return result
