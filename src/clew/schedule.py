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
import tempfile
from datetime import datetime, timezone
from pathlib import Path

TASK_NAME = "BoxdawnSubmit"
# The fast path is a second registration rather than a resident process, for
# the reason at the top of this file: a watcher that loops forever is exactly
# the daemon that argument rejects. `watch --once` exits, so a run that did not
# happen leaves a gap in its log instead of looking like a quiet one.
WATCH_TASK_NAME = "BoxdawnWatch"
# One minute, because that is the interval P2 was measured at: 32.5 s median
# from the repeat to the record, of which 0.36 s is the scan and the rest is
# this wait. Widening it widens the latency by the same amount.
WATCH_EVERY_MINUTES = 1
SUBMIT_ARGS = ("submit", "--auto")
# `--send` is here rather than in a config file because the registered command
# line is the honest record of what the machine does every minute. `schtasks
# /query /xml` shows it; a flag read from somewhere else would not.
#
# Turning it off is `clew watch --uninstall` followed by `--install`, or one
# `delete from live_alert_allowlist` on the server -- either half closes the
# chain on its own, which is the redundancy `live_send.py` is built around.
WATCH_ARGS = ("watch", "--once", "--auto", "--send")
# Latency amendment: the sweep is the second largest term in the delay after
# the close rule itself, so it moves with it. 15 minutes against a 20-minute
# close rule means a finished session waits at most 35 for its upload.
DEFAULT_EVERY_MINUTES = 15

# The definition `install` registers. Kept whole rather than assembled, because
# the task schema validates element order and a reader has to be able to see it.
TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <TimeTrigger>
      <StartBoundary>{begin}</StartBoundary>
      <Repetition><Interval>PT{interval}M</Interval></Repetition>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Settings>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <WakeToRun>false</WakeToRun>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <ExecutionTimeLimit>{time_limit}</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
      <Arguments>{arguments}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def _runner(task_args: tuple[str, ...] = SUBMIT_ARGS) -> list[str]:
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
    return [str(exe), "-m", "clew", *task_args]


def command_line(task_args: tuple[str, ...] = SUBMIT_ARGS) -> str:
    """The runner as one shell-ready string."""
    return subprocess.list2cmdline(_runner(task_args))


def _task_xml(every_minutes: int = DEFAULT_EVERY_MINUTES,
              start: datetime | None = None,
              task_args: tuple[str, ...] = SUBMIT_ARGS,
              time_limit: str = "PT1H") -> str:
    """The full task definition, because the flags cannot express its settings.

    `/SC MINUTE /MO 15` takes the Windows defaults, and three of those defaults
    stop the sweep from running at all:

      DisallowStartIfOnBatteries  a laptop on battery never sweeps. Measured
        here: unplugged at 03:57Z, plugged back in at 05:58Z, and all nine
        triggers in between were skipped while sessions kept being written. The
        log showed a two and a half hour hole with no error in it, because a
        trigger Windows declines to launch is not a failure it reports.
      StopIfGoingOnBatteries  unplugging kills a sweep already in flight.
      StartWhenAvailable  a trigger missed while the machine was off or asleep
        is never made up, so the wait after a reboot is the close rule plus
        however long the machine was away.

    WakeToRun stays off. A sleeping machine is not writing sessions, so there is
    nothing to collect, and waking someone's laptop to upload is not a trade
    this feature makes on their behalf. StartWhenAvailable covers the wake.

    ExecutionTimeLimit is bounded because MultipleInstancesPolicy is IgnoreNew:
    one hung sweep holding the slot for the three-day default would silence
    every trigger behind it, which is the same silence this whole file exists to
    avoid. A killed run is recoverable -- `submit` writes the ledger entry
    before it waits for the answer, and the next run resolves it.

    Element order follows the task schema (Triggers, Settings, Actions); the
    order is validated, not just the contents.
    """
    runner = _runner(task_args)
    command = _xml_escape(runner[0])
    arguments = _xml_escape(subprocess.list2cmdline(runner[1:]))
    begin = (start or datetime.now()).replace(microsecond=0).isoformat()
    return TASK_XML.format(begin=begin, interval=every_minutes,
                           command=command, arguments=arguments,
                           time_limit=time_limit)


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def install(every_minutes: int = DEFAULT_EVERY_MINUTES,
            task_name: str = TASK_NAME,
            task_args: tuple[str, ...] = SUBMIT_ARGS,
            time_limit: str = "PT1H") -> tuple[bool, str]:
    """Register the sweep. Returns (registered, message).

    `registered` is False when this platform is only being told what to run,
    so a caller never reports a task that was not created.
    """
    if sys.platform == "win32":
        # Written out rather than piped: `schtasks /XML` takes a path, and it
        # reads UTF-16, which is what Windows itself exports.
        xml_path = Path(tempfile.gettempdir()) / f"{task_name}.xml"
        xml_path.write_text(
            _task_xml(every_minutes, task_args=task_args, time_limit=time_limit),
            encoding="utf-16")
        try:
            proc = subprocess.run(
                ["schtasks", "/Create", "/F", "/TN", task_name,
                 "/XML", str(xml_path)],
                capture_output=True, text=True,
            )
        finally:
            xml_path.unlink(missing_ok=True)
        if proc.returncode != 0:
            return False, (proc.stderr.strip() or proc.stdout.strip()
                           or f"schtasks exited {proc.returncode}")
        return True, f"registered task {task_name}, every {every_minutes} min"

    if sys.platform == "darwin":
        return False, _launchd_instructions(every_minutes, task_args)
    return False, _cron_instructions(every_minutes, task_args)


def uninstall(task_name: str = TASK_NAME) -> tuple[bool, str]:
    if sys.platform == "win32":
        proc = subprocess.run(
            ["schtasks", "/Delete", "/F", "/TN", task_name],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            return False, (proc.stderr.strip() or proc.stdout.strip()
                           or f"schtasks exited {proc.returncode}")
        return True, f"removed task {task_name}"
    if sys.platform == "darwin":
        return False, ("remove it with:\n"
                       "  launchctl unload ~/Library/LaunchAgents/com.boxdawn.submit.plist\n"
                       "  rm ~/Library/LaunchAgents/com.boxdawn.submit.plist")
    return False, "remove the boxdawn line from `crontab -e`"


def is_registered(task_name: str = TASK_NAME) -> bool | None:
    """True/False on Windows; None where this file does not register."""
    if sys.platform != "win32":
        return None
    proc = subprocess.run(
        ["schtasks", "/Query", "/TN", task_name],
        capture_output=True, text=True,
    )
    return proc.returncode == 0


def _cron_instructions(every_minutes: int,
                       task_args: tuple[str, ...] = SUBMIT_ARGS) -> str:
    return (
        "not registered. Add this to `crontab -e` yourself:\n"
        f"  */{every_minutes} * * * * {command_line(task_args)}\n"
        "(this platform is not registered automatically, because a "
        "registration that fails silently is worse than none)"
    )


def _launchd_instructions(every_minutes: int,
                          task_args: tuple[str, ...] = SUBMIT_ARGS) -> str:
    label = f"com.boxdawn.{task_args[0]}"
    return (
        "not registered. Save this as "
        f"~/Library/LaunchAgents/{label}.plist and run\n"
        f"  launchctl load ~/Library/LaunchAgents/{label}.plist\n\n"
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<plist version="1.0"><dict>\n'
        f"  <key>Label</key><string>{label}</string>\n"
        "  <key>ProgramArguments</key><array>\n"
        + "".join(f"    <string>{part}</string>\n" for part in _runner(task_args))
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
