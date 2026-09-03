"""src/clew/schedule.py — register the unattended submission sweep with the OS.

Why the OS scheduler and not a resident process: a daemon dies at reboot, and
a dead daemon looks exactly like a quiet one. That confusion cost us a day on
the alert cron, where a successful run and a run that never happened produced
the same empty log. A registered task survives reboot, holds no memory while
idle, and can be listed by name — three things a background process only gets
by reimplementing them.

All three platforms are registered for real. The objection this file used to
record -- that it cannot test macOS and Linux, and that a registration which
silently fails to take is the failure mode the whole design is avoiding --
was right about the danger and wrong about the remedy.

The remedy is not refusing to register. It is that **every registration is
read back before it is reported**: cron through `crontab -l`, launchd through
`launchctl list`, Windows through `schtasks /Query`. `install` returns
`registered=True` only when the query confirms, and when it does not it returns
the same hand-installable instructions this file printed before, plus what was
attempted and what the query said. The worst case is therefore exactly the old
behaviour, and a silent success is not reachable.

Tested where it could be: the cron path end to end on real Linux
(WSL Ubuntu 24.04, cron 3.0pl1, Python 3.12.3) -- install, read back, preserve
a pre-existing crontab, uninstall. The launchd path has no macOS to run on
here, so its commands are exercised against recorded `launchctl` behaviour in
tests and its verification step is what protects a real user: if the command is
wrong for their macOS version, the read-back fails and they get instructions
rather than a task they believe exists.
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


def _cron_expression(every_minutes: int) -> str | None:
    """A cron schedule field cron will accept, or None if it will not.

    `*/N` is only valid in the minute field for N below 60; `*/90` is not "every
    90 minutes", it is a line cron rejects. The old code emitted `*/{N}`
    unconditionally, so `--every 90` printed an instruction that could not be
    installed. Whole hours get the hour field instead, and anything else is
    refused by name rather than written and left to fail.
    """
    if 1 <= every_minutes < 60:
        return f"*/{every_minutes} * * * *"
    if every_minutes % 60 == 0 and 1 <= every_minutes // 60 < 24:
        return f"0 */{every_minutes // 60} * * *"
    return None


def _cron_markers(task_name: str) -> tuple[str, str]:
    """The fenced block one task owns, so two tasks coexist and neither edits
    a line the user wrote themselves."""
    return f"# >>> boxdawn {task_name} >>>", f"# <<< boxdawn {task_name} <<<"


def _read_crontab() -> str:
    """The user's crontab, or "" when they have none.

    An empty crontab exits non-zero with "no crontab for <user>" on stderr,
    which is not an error condition -- it is the first install. Treating it as
    one is how a first install would fail.
    """
    proc = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return proc.stdout if proc.returncode == 0 else ""


def _strip_block(text: str, task_name: str) -> str:
    begin, end = _cron_markers(task_name)
    out, skipping = [], False
    for line in text.splitlines():
        if line.strip() == begin:
            skipping = True
            continue
        if line.strip() == end:
            skipping = False
            continue
        if not skipping:
            out.append(line)
    return "\n".join(out)


def _install_cron(every_minutes: int, task_name: str,
                  task_args: tuple[str, ...]) -> tuple[bool, str]:
    expr = _cron_expression(every_minutes)
    if expr is None:
        return False, (
            f"cannot schedule every {every_minutes} minutes with cron: the "
            "minute field takes an interval below 60, and above that only "
            "whole hours (60, 120, ... 1380). Nothing was installed."
        )
    begin, end = _cron_markers(task_name)
    line = f"{expr} {command_line(task_args)}"
    kept = _strip_block(_read_crontab(), task_name).rstrip("\n")
    body = f"{kept}\n" if kept else ""
    new = f"{body}{begin}\n{line}\n{end}\n"

    proc = subprocess.run(["crontab", "-"], input=new,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return False, (
            (proc.stderr.strip() or f"crontab exited {proc.returncode}")
            + "\n" + _cron_instructions(every_minutes, task_args)
        )
    # Read back. `crontab -` accepting the input is not the same as the line
    # being there afterwards, and this is the whole reason auto-registration is
    # allowed on this platform at all.
    if line not in _read_crontab():
        return False, (
            "crontab accepted the write but the line is not in `crontab -l` "
            "afterwards, so nothing is scheduled.\n"
            + _cron_instructions(every_minutes, task_args)
        )
    return True, f"registered cron job {task_name}, every {every_minutes} min"


def _uninstall_cron(task_name: str) -> tuple[bool, str]:
    current = _read_crontab()
    begin, _ = _cron_markers(task_name)
    if begin not in current:
        return True, f"no cron job {task_name} to remove"
    stripped = _strip_block(current, task_name).rstrip("\n")
    proc = subprocess.run(["crontab", "-"],
                          input=(f"{stripped}\n" if stripped else ""),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return False, (proc.stderr.strip() or f"crontab exited {proc.returncode}")
    if begin in _read_crontab():
        return False, ("crontab accepted the write but the block is still in "
                       "`crontab -l`; remove it with `crontab -e`")
    return True, f"removed cron job {task_name}"


def _launchd_label(task_args: tuple[str, ...]) -> str:
    return f"com.boxdawn.{task_args[0]}"


def _launchd_plist_path(task_args: tuple[str, ...]) -> Path:
    return (Path.home() / "Library" / "LaunchAgents"
            / f"{_launchd_label(task_args)}.plist")


def _launchd_plist(every_minutes: int, task_args: tuple[str, ...]) -> str:
    label = _launchd_label(task_args)
    program = "".join(f"    <string>{_xml_escape(part)}</string>\n"
                      for part in _runner(task_args))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        f"  <key>Label</key><string>{label}</string>\n"
        "  <key>ProgramArguments</key><array>\n"
        f"{program}"
        "  </array>\n"
        f"  <key>StartInterval</key><integer>{every_minutes * 60}</integer>\n"
        "  <key>RunAtLoad</key><false/>\n"
        "</dict></plist>\n"
    )


def _launchctl_loaded(label: str) -> bool:
    proc = subprocess.run(["launchctl", "list", label],
                          capture_output=True, text=True)
    return proc.returncode == 0


def _install_launchd(every_minutes: int,
                     task_args: tuple[str, ...]) -> tuple[bool, str]:
    label = _launchd_label(task_args)
    path = _launchd_plist_path(task_args)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_launchd_plist(every_minutes, task_args), encoding="utf-8")
    except OSError as e:
        return False, f"{e}\n" + _launchd_instructions(every_minutes, task_args)

    # An already-loaded agent makes `load` fail, so unload first and ignore
    # how that goes -- the read-back below is what decides.
    subprocess.run(["launchctl", "unload", str(path)],
                   capture_output=True, text=True)
    proc = subprocess.run(["launchctl", "load", "-w", str(path)],
                          capture_output=True, text=True)
    if not _launchctl_loaded(label):
        detail = (proc.stderr.strip() or proc.stdout.strip()
                  or f"launchctl exited {proc.returncode}")
        return False, (
            f"the plist was written to {path} but `launchctl list {label}` "
            f"does not show it, so nothing is scheduled ({detail}).\n"
            "Load it yourself with:\n"
            f"  launchctl load -w {path}"
        )
    return True, f"registered launchd agent {label}, every {every_minutes} min"


def _uninstall_launchd(task_args: tuple[str, ...]) -> tuple[bool, str]:
    label = _launchd_label(task_args)
    path = _launchd_plist_path(task_args)
    subprocess.run(["launchctl", "unload", "-w", str(path)],
                   capture_output=True, text=True)
    if _launchctl_loaded(label):
        return False, (f"`launchctl list {label}` still shows it. Remove it "
                       f"with:\n  launchctl unload -w {path}")
    try:
        path.unlink(missing_ok=True)
    except OSError as e:
        return False, f"unloaded, but {path} could not be removed: {e}"
    return True, f"removed launchd agent {label}"


def install(every_minutes: int = DEFAULT_EVERY_MINUTES,
            task_name: str = TASK_NAME,
            task_args: tuple[str, ...] = SUBMIT_ARGS,
            time_limit: str = "PT1H") -> tuple[bool, str]:
    """Register the sweep. Returns (registered, message).

    `registered` is True only when a query afterwards confirms the task is
    there. On a False the message carries the hand-installable instructions and
    what the query said, so the caller never reports a task that was not
    created and the user is never worse off than before this file registered
    anything.
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
        return _install_launchd(every_minutes, task_args)
    if sys.platform.startswith("linux"):
        return _install_cron(every_minutes, task_name, task_args)
    # Some other platform. Nothing is attempted, because attempting it is what
    # produces the silent half-registration this file exists to avoid.
    return False, _cron_instructions(every_minutes, task_args)


def uninstall(task_name: str = TASK_NAME,
              task_args: tuple[str, ...] = SUBMIT_ARGS) -> tuple[bool, str]:
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
        return _uninstall_launchd(task_args)
    if sys.platform.startswith("linux"):
        return _uninstall_cron(task_name)
    return False, "remove the boxdawn line from `crontab -e`"


def is_registered(task_name: str = TASK_NAME,
                  task_args: tuple[str, ...] = SUBMIT_ARGS) -> bool | None:
    """True/False on Windows, macOS and Linux; None on any other platform.

    None means "this file does not register here", which the CLI reads as "do
    not judge the exit code on it". It used to be returned for macOS and Linux
    too, and that is why `--install` there set the submission watermark and
    exited 0 while nothing had been scheduled.
    """
    if sys.platform == "win32":
        proc = subprocess.run(
            ["schtasks", "/Query", "/TN", task_name],
            capture_output=True, text=True,
        )
        return proc.returncode == 0
    if sys.platform == "darwin":
        return _launchctl_loaded(_launchd_label(task_args))
    if sys.platform.startswith("linux"):
        return _cron_markers(task_name)[0] in _read_crontab()
    return None


def _cron_instructions(every_minutes: int,
                       task_args: tuple[str, ...] = SUBMIT_ARGS) -> str:
    expr = _cron_expression(every_minutes)
    if expr is None:
        return (f"cannot schedule every {every_minutes} minutes with cron: "
                "below 60, or whole hours up to 1380.")
    return (
        "not registered. Add this to `crontab -e` yourself:\n"
        f"  {expr} {command_line(task_args)}"
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
