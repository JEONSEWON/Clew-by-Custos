"""src/clew/schedule.py — register the unattended submission sweep with the OS.

Why the OS scheduler and not a resident process: a daemon dies at reboot, and
a dead daemon looks exactly like a quiet one. That confusion cost us a day on
the alert cron, where a successful run and a run that never happened produced
the same empty log. A registered task survives reboot, holds no memory while
idle, and can be listed by name — three things a background process only gets
by reimplementing them.

Windows is registered for real here. macOS and Linux are handed the exact line
to install instead of having it written for them: this file cannot test those
two, and a registration that silently fails to take is the failure mode the
whole design is avoiding.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TASK_NAME = "BoxdawnSubmit"
# Latency amendment: the sweep is the second largest term in the delay after
# the close rule itself, so it moves with it. 15 minutes against a 20-minute
# close rule means a finished session waits at most 35 for its upload.
DEFAULT_EVERY_MINUTES = 15


def _runner() -> list[str]:
    """The command a scheduler should invoke.

    `sys.executable -m clew` rather than the `boxdawn` console script: the
    interpreter running this is by definition the one boxdawn is installed
    into, while a bare name depends on whatever PATH the scheduler happens to
    hand the task.

    On Windows `pythonw.exe` replaces `python.exe` when present. Same
    interpreter, no console window — an hourly black flash on someone's screen
    is how a background feature gets uninstalled.
    """
    exe = Path(sys.executable)
    if sys.platform == "win32":
        quiet = exe.with_name("pythonw.exe")
        if quiet.exists():
            exe = quiet
    return [str(exe), "-m", "clew", "submit", "--auto"]


def command_line() -> str:
    """The runner as one shell-ready string."""
    return subprocess.list2cmdline(_runner())


def install(every_minutes: int = DEFAULT_EVERY_MINUTES) -> tuple[bool, str]:
    """Register the sweep. Returns (registered, message).

    `registered` is False when this platform is only being told what to run,
    so a caller never reports a task that was not created.
    """
    if sys.platform == "win32":
        proc = subprocess.run(
            ["schtasks", "/Create", "/F", "/TN", TASK_NAME,
             "/SC", "MINUTE", "/MO", str(every_minutes),
             "/TR", command_line()],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            return False, (proc.stderr.strip() or proc.stdout.strip()
                           or f"schtasks exited {proc.returncode}")
        return True, f"registered task {TASK_NAME}, every {every_minutes} min"

    if sys.platform == "darwin":
        return False, _launchd_instructions(every_minutes)
    return False, _cron_instructions(every_minutes)


def uninstall() -> tuple[bool, str]:
    if sys.platform == "win32":
        proc = subprocess.run(
            ["schtasks", "/Delete", "/F", "/TN", TASK_NAME],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            return False, (proc.stderr.strip() or proc.stdout.strip()
                           or f"schtasks exited {proc.returncode}")
        return True, f"removed task {TASK_NAME}"
    if sys.platform == "darwin":
        return False, (f"remove it with:\n"
                       f"  launchctl unload ~/Library/LaunchAgents/com.boxdawn.submit.plist\n"
                       f"  rm ~/Library/LaunchAgents/com.boxdawn.submit.plist")
    return False, "remove the boxdawn line from `crontab -e`"


def is_registered() -> bool | None:
    """True/False on Windows; None where this file does not register."""
    if sys.platform != "win32":
        return None
    proc = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME],
        capture_output=True, text=True,
    )
    return proc.returncode == 0


def _cron_instructions(every_minutes: int) -> str:
    return (
        "not registered. Add this to `crontab -e` yourself:\n"
        f"  */{every_minutes} * * * * {command_line()}\n"
        "(this platform is not registered automatically, because a "
        "registration that fails silently is worse than none)"
    )


def _launchd_instructions(every_minutes: int) -> str:
    return (
        "not registered. Save this as "
        "~/Library/LaunchAgents/com.boxdawn.submit.plist and run\n"
        "  launchctl load ~/Library/LaunchAgents/com.boxdawn.submit.plist\n\n"
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<plist version="1.0"><dict>\n'
        "  <key>Label</key><string>com.boxdawn.submit</string>\n"
        "  <key>ProgramArguments</key><array>\n"
        + "".join(f"    <string>{part}</string>\n" for part in _runner())
        + "  </array>\n"
        f"  <key>StartInterval</key><integer>{every_minutes * 60}</integer>\n"
        "</dict></plist>"
    )


def log_run(message: str, path: Path) -> None:
    """Append one line per unattended run.

    Every run writes, including the ones with nothing to do. A sweep that found
    no work and a scheduler that never fired are the same silence otherwise,
    and telling those apart afterwards is not possible from the outside.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp} {message}\n")


def tail_log(path: Path, lines: int = 5) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()[-lines:]
    except OSError:
        return []
