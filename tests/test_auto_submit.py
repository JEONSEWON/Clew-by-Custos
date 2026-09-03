"""Unattended submission — per-project routing, the install watermark, and
the line every run leaves behind.

The three things checked here are the three ways this feature could be worse
than not having it:

  1. sending two codebases under one key, which blends the baselines that
     rule A compares within
  2. sweeping the machine's history the moment it is switched on, which puts
     a mound of backfill on a single day
  3. running silently, so a scheduler that stopped firing looks exactly like
     a sweep with nothing to send
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from clew import schedule, submit

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _session(path, last: datetime):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"type": "assistant",
                    "timestamp": last.isoformat().replace("+00:00", "Z")}) + "\n",
        encoding="utf-8")
    return path


def _projects(tmp_path, entries) -> "object":
    cfg = tmp_path / "projects.yaml"
    cfg.write_text(yaml.safe_dump(entries), encoding="utf-8")
    return cfg


# ── routing: one codebase, one key ─────────────────────────────────────────


def test_each_codebase_keeps_its_own_key(tmp_path):
    cfg = _projects(tmp_path, [
        {"project": "a", "root": str(tmp_path / "ra"), "api_key": "bdk_a"},
        {"project": "b", "root": str(tmp_path / "rb"), "api_key": "bdk_b"},
    ])
    targets = submit.load_targets(cfg, tmp_path / "unused")
    assert [(t.project, t.api_key) for t in targets] == [("a", "bdk_a"), ("b", "bdk_b")]


def test_without_a_config_it_is_the_single_root_it_always_was(tmp_path, monkeypatch):
    monkeypatch.setenv(submit.KEY_ENV, "bdk_env")
    targets = submit.load_targets(tmp_path / "absent.yaml", tmp_path / "root")
    assert len(targets) == 1
    assert targets[0].root == tmp_path / "root"
    assert targets[0].api_key == "bdk_env"


def test_two_entries_may_not_share_a_root(tmp_path):
    """Distinguishes: the same sessions under two keys land as two rows in two
    projects, and the ledger cannot catch it because it is keyed by path and
    the first send marks it done -- so which project gets the data depends on
    entry order."""
    cfg = _projects(tmp_path, [
        {"project": "a", "root": str(tmp_path / "same"), "api_key": "bdk_a"},
        {"project": "b", "root": str(tmp_path / "same"), "api_key": "bdk_b"},
    ])
    with pytest.raises(ValueError, match="share a root"):
        submit.load_targets(cfg, tmp_path)


def test_a_broken_config_refuses_rather_than_falling_back(tmp_path):
    """Distinguishes: falling back to the single-root path would send every
    codebase under one key -- exactly the blending the config exists to stop,
    reached by accident instead of by choice."""
    cfg = _projects(tmp_path, [{"project": "a", "root": str(tmp_path / "ra")}])
    with pytest.raises(ValueError, match="api_key"):
        submit.load_targets(cfg, tmp_path)


def test_run_all_sends_each_target_under_its_own_key(tmp_path, monkeypatch):
    for name in ("ra", "rb"):
        _session(tmp_path / name / "s.jsonl", NOW - timedelta(hours=9))
    seen = []
    monkeypatch.setattr(submit, "submit_file",
                        lambda path, key, endpoint: seen.append((path.parent.name, key))
                        or {"ok": True, "stored": True})
    targets = [submit.Target("a", tmp_path / "ra", "bdk_a"),
               submit.Target("b", tmp_path / "rb", "bdk_b")]
    submit.run_all(targets, now=NOW, ledger_path=tmp_path / "l.json",
                   pace_seconds=0, out=lambda *a: None)
    assert sorted(seen) == [("ra", "bdk_a"), ("rb", "bdk_b")]


# ── the watermark: switching it on is not a backfill ───────────────────────


def test_sessions_that_ended_before_install_are_not_swept_up(tmp_path):
    """Distinguishes: without the watermark this returns both, and a first
    unattended run uploads the machine's whole history onto one day."""
    old = _session(tmp_path / "old.jsonl", NOW - timedelta(days=3))
    new = _session(tmp_path / "new.jsonl", NOW - timedelta(hours=9))
    installed = NOW - timedelta(days=1)

    assert set(submit.pending(tmp_path, NOW, {})) == {old, new}
    assert submit.pending(tmp_path, NOW, {}, since=installed) == [new]


def test_a_session_still_has_to_be_closed_even_if_it_is_recent(tmp_path):
    """The watermark narrows the rule, it does not replace it.

    Five minutes idle, against a close rule of twenty. This said thirty when
    the rule was 240; the number moved with the threshold, not the intent.
    """
    _session(tmp_path / "busy.jsonl", NOW - timedelta(minutes=5))
    assert submit.pending(tmp_path, NOW, {}, since=NOW - timedelta(days=1)) == []


def test_installing_twice_does_not_move_the_watermark(tmp_path):
    """Distinguishes: a watermark rewritten on every install would keep
    skipping forward, so sessions that ended between two installs would never
    be sent by anything."""
    state_path = tmp_path / "auto.json"
    first = "2026-08-01T00:00:00+00:00"
    submit.write_auto_state({"installed_at": first}, state_path)
    state = submit.read_auto_state(state_path)
    assert state["installed_at"] == first
    assert submit.installed_at(state_path) == datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_no_watermark_means_never_installed(tmp_path):
    assert submit.installed_at(tmp_path / "absent.json") is None


# ── evidence: every run leaves a line ──────────────────────────────────────


def test_a_run_with_nothing_to_do_still_writes_a_line(tmp_path):
    """Distinguishes: logging only when something was sent makes a stopped
    scheduler and a quiet week the same empty file -- the confusion that cost
    a day on the alert cron."""
    log = tmp_path / "auto.log"
    schedule.log_run("exit=0 targets=3 nothing to submit", log)
    lines = schedule.tail_log(log)
    assert len(lines) == 1
    assert "nothing to submit" in lines[0]
    assert lines[0].startswith("20")  # timestamped


def test_the_log_accumulates_rather_than_replacing(tmp_path):
    log = tmp_path / "auto.log"
    for i in range(3):
        schedule.log_run(f"run {i}", log)
    assert len(schedule.tail_log(log, lines=10)) == 3


def test_tail_of_a_missing_log_is_empty_not_an_error(tmp_path):
    assert schedule.tail_log(tmp_path / "absent.log") == []


# ── what the scheduler is told to run ──────────────────────────────────────


def test_the_scheduled_command_names_this_interpreter(tmp_path):
    """Distinguishes: a bare `boxdawn` depends on whatever PATH the scheduler
    hands the task, which is not the PATH the operator installed under."""
    line = schedule.command_line()
    assert "-m clew submit --auto" in line
    assert "python" in line.lower()


# ── the settings the scheduler is registered with ──────────────────────────
#
# A fourth way this feature could be worse than not having it, found by
# measuring the latency it was supposed to shorten: the task registers fine,
# reports Ready, counts zero missed runs, and does not fire. The default flags
# hand Windows three conditions under which it declines to launch, and a
# declined launch is not an error anywhere.


def test_the_sweep_runs_on_battery(tmp_path):
    """Distinguishes: `schtasks /SC MINUTE` takes DisallowStartIfOnBatteries
    true, so an unplugged laptop never sweeps. Measured on this machine before
    the fix: unplugged 03:57Z, back on AC 05:58Z, nine triggers skipped, one
    session's upload delayed 136 minutes against a 100-minute prediction. The
    log for those two and a half hours was empty, not failing.
    """
    xml = schedule._task_xml()
    assert "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>" in xml
    assert "<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>" in xml


def test_a_trigger_missed_while_the_machine_was_away_is_made_up(tmp_path):
    """Distinguishes: without StartWhenAvailable the wait after a reboot is the
    close rule plus however long the machine slept, which has no bound."""
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in schedule._task_xml()


def test_the_machine_is_not_woken_to_upload(tmp_path):
    """The other direction of the same setting. A sleeping machine writes no
    sessions, so there is nothing to collect and no reason to wake it."""
    assert "<WakeToRun>false</WakeToRun>" in schedule._task_xml()


def test_a_hung_sweep_cannot_silence_the_ones_behind_it(tmp_path):
    """Distinguishes: IgnoreNew plus the three-day default execution limit
    means one stuck run swallows every trigger for three days, and the log
    looks exactly like a machine that was switched off."""
    xml = schedule._task_xml()
    assert "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>" in xml
    assert "<ExecutionTimeLimit>PT1H</ExecutionTimeLimit>" in xml


def test_the_definition_carries_the_interval_and_the_runner(tmp_path):
    xml = schedule._task_xml(15)
    assert "<Interval>PT15M</Interval>" in xml
    assert "-m clew submit --auto" in xml


def test_the_definition_keeps_the_order_the_schema_validates(tmp_path):
    """Distinguishes: Windows rejects a task whose elements are out of order
    with the same unhelpful message it gives for malformed XML."""
    xml = schedule._task_xml()
    assert xml.index("<Triggers>") < xml.index("<Settings>") < xml.index("<Actions")


@pytest.mark.skipif(sys.platform != "win32", reason="registers a Windows task")
def test_registration_hands_schtasks_a_utf16_file(monkeypatch):
    """Distinguishes: `schtasks /XML` reads UTF-16 and rejects a UTF-8 file as
    malformed, which would leave the sweep unregistered while `install`
    reported the reason as an XML problem.
    """
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["head"] = Path(cmd[cmd.index("/XML") + 1]).read_bytes()[:2]

        class Done:
            returncode = 0
            stdout = stderr = ""
        return Done()

    monkeypatch.setattr(schedule.subprocess, "run", fake_run)
    registered, _ = schedule.install()
    assert registered
    assert "/XML" in seen["cmd"]
    assert seen["head"] == bytes([0xFF, 0xFE])   # UTF-16 LE byte order mark


def test_one_target_failing_does_not_stop_the_others(tmp_path, monkeypatch):
    """A revoked key on one codebase must not cost the day's measurements on
    the rest."""
    for name in ("ra", "rb"):
        _session(tmp_path / name / "s.jsonl", NOW - timedelta(hours=9))

    tried = []

    def fake(path, key, endpoint):
        tried.append(key)
        if key == "bdk_a":
            return {"ok": False, "stored": False, "reason": "revoked"}
        return {"ok": True, "stored": True}

    monkeypatch.setattr(submit, "submit_file", fake)
    code = submit.run_all(
        [submit.Target("a", tmp_path / "ra", "bdk_a"),
         submit.Target("b", tmp_path / "rb", "bdk_b")],
        now=NOW, ledger_path=tmp_path / "l.json", pace_seconds=0,
        out=lambda m: None,
    )
    # the failing target is first, so a run that stops on failure never
    # reaches the second key -- which is what this rules out. Asserting on the
    # printed lines does not: "NOT stored" contains "stored".
    assert tried == ["bdk_a", "bdk_b"]
    assert code == 1                                   # worst code wins


# ── the latency amendment ──────────────────────────────────────────────────
#
# Shortening the wait is only safe because migration 0018 made a resubmission
# replace the stored row. The client half of that is here: a session that grew
# has to be sent again, or the shorter wait stores an early fragment and never
# corrects it.


def test_the_close_rule_matches_the_amendment():
    """The threshold is frozen in a document, not chosen here."""
    assert submit.CLOSE_AFTER == timedelta(minutes=20)


def test_a_session_that_grew_is_sent_again(tmp_path):
    """Distinguishes: with the ledger keyed on the path alone, a session sent
    after twenty quiet minutes is never sent again, and what is stored is an
    early fragment of a session that ran for hours. That is worse than the
    four-hour wait it replaced.
    """
    path = _session(tmp_path / "s.jsonl", NOW - timedelta(hours=9))
    ledger = {str(path): {"ok": True, "stored": True,
                          "sent_through": (NOW - timedelta(hours=9)).isoformat()}}
    assert submit.pending(tmp_path, NOW, ledger) == []

    _session(path, NOW - timedelta(hours=1))          # the session continued
    assert submit.pending(tmp_path, NOW, ledger) == [path]


def test_a_session_that_did_not_grow_is_left_alone(tmp_path):
    path = _session(tmp_path / "s.jsonl", NOW - timedelta(hours=9))
    ledger = {str(path): {"ok": True, "stored": True,
                          "sent_through": (NOW - timedelta(hours=9)).isoformat()}}
    assert submit.pending(tmp_path, NOW, ledger) == []


def test_a_ledger_written_before_this_field_does_not_resend_everything(tmp_path):
    """Distinguishes: treating a missing `sent_through` as "new content" makes
    the first run of an upgraded client resubmit every session on the machine.
    On this laptop that is 72 of them.
    """
    path = _session(tmp_path / "s.jsonl", NOW - timedelta(hours=9))
    ledger = {str(path): {"ok": True, "stored": True,
                          "submitted_at": "2026-08-25T00:00:00+00:00"}}
    assert submit.pending(tmp_path, NOW, ledger) == []


def test_a_grown_session_still_has_to_be_quiet(tmp_path):
    """Growth reopens a session for sending; it does not skip the close rule."""
    path = _session(tmp_path / "s.jsonl", NOW - timedelta(minutes=5))
    ledger = {str(path): {"ok": True, "stored": True,
                          "sent_through": (NOW - timedelta(hours=9)).isoformat()}}
    assert submit.pending(tmp_path, NOW, ledger) == []


def test_a_send_records_how_far_it_reached(tmp_path, monkeypatch):
    """Without this the next sweep cannot tell whether the file moved."""
    last = NOW - timedelta(hours=9)
    _session(tmp_path / "s.jsonl", last)
    monkeypatch.setattr(submit, "submit_file",
                        lambda p, k, e: {"ok": True, "stored": True})
    led = tmp_path / "l.json"
    submit.run(root=tmp_path, ledger_path=led, now=NOW, key="bdk_" + "a" * 24,
               pace_seconds=0, out=lambda *a: None)
    entry = next(iter(json.loads(led.read_text(encoding="utf-8")).values()))
    assert entry["sent_through"] == last.isoformat()


# ── registering on macOS and Linux, and refusing to claim it worked ─────────
#
# These three platforms used to be two: Windows registered, and macOS/Linux
# were handed a line to paste. The reason recorded in `schedule.py` was that a
# registration which silently fails to take is worse than none -- right about
# the danger, wrong about the remedy. The remedy here is that every
# registration is read back, and `install` reports success only when the query
# afterwards confirms it.
#
# The cron path was verified end to end against the real `crontab` binary on
# WSL Ubuntu 24.04 (29/29, including preserving a line the user wrote). What
# these tests add is the half that machine cannot show: the failure paths, and
# macOS, where there is no hardware here to run `launchctl` on.


class _FakeRun:
    """Records argv and answers from a table, so a platform can be simulated."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((tuple(argv), kwargs.get("input")))
        for prefix, result in self.answers:
            if tuple(argv[:len(prefix)]) == tuple(prefix):
                return result
        raise AssertionError(f"unexpected command: {argv}")


def _proc(returncode=0, stdout="", stderr=""):
    import subprocess as _sp
    return _sp.CompletedProcess(args=[], returncode=returncode,
                                stdout=stdout, stderr=stderr)


def test_cron_install_that_does_not_take_reports_failure_not_success(monkeypatch):
    """The whole reason auto-registration is allowed here.

    `crontab -` exits 0 and the line is not in `crontab -l` afterwards. Before
    the read-back this returned success and the user believed a task existed.
    """
    monkeypatch.setattr(schedule.sys, "platform", "linux")
    fake = _FakeRun([
        (["crontab", "-l"], _proc(0, stdout="")),      # empty, before and after
        (["crontab", "-"], _proc(0)),                  # write "succeeds"
    ])
    monkeypatch.setattr(schedule.subprocess, "run", fake)

    ok, message = schedule.install(15)
    assert ok is False
    assert "not in `crontab -l`" in message
    # and the user is left where they were: with the line to paste
    assert "crontab -e" in message
    assert "*/15 * * * *" in message


def test_cron_refuses_an_interval_it_cannot_express(monkeypatch):
    """`*/90` is not "every 90 minutes", it is a line cron rejects. Writing it
    and letting cron fail is the silent failure in a different costume."""
    monkeypatch.setattr(schedule.sys, "platform", "linux")
    calls = _FakeRun([])
    monkeypatch.setattr(schedule.subprocess, "run", calls)

    ok, message = schedule.install(90)
    assert ok is False
    assert "90" in message and "Nothing was installed" in message
    assert calls.calls == [], "nothing may be written when the interval is refused"


def test_cron_expression_covers_minutes_and_whole_hours():
    assert schedule._cron_expression(1) == "*/1 * * * *"
    assert schedule._cron_expression(15) == "*/15 * * * *"
    assert schedule._cron_expression(59) == "*/59 * * * *"
    assert schedule._cron_expression(60) == "0 */1 * * *"
    assert schedule._cron_expression(120) == "0 */2 * * *"
    assert schedule._cron_expression(90) is None
    assert schedule._cron_expression(1440) is None      # a day is not */24
    assert schedule._cron_expression(0) is None


def test_one_task_block_does_not_eat_the_other_or_the_users_lines():
    """Two registrations coexist and neither touches a line somebody wrote."""
    mine = "0 3 * * * /usr/bin/backup"
    text = (
        f"{mine}\n"
        "# >>> boxdawn BoxdawnSubmit >>>\n"
        "*/15 * * * * python -m clew submit --auto\n"
        "# <<< boxdawn BoxdawnSubmit <<<\n"
        "# >>> boxdawn BoxdawnWatch >>>\n"
        "*/1 * * * * python -m clew watch --once --auto --send\n"
        "# <<< boxdawn BoxdawnWatch <<<\n"
    )
    left = schedule._strip_block(text, schedule.WATCH_TASK_NAME)
    assert mine in left
    assert "BoxdawnSubmit" in left
    assert "BoxdawnWatch" not in left
    assert "watch --once" not in left


def test_an_empty_crontab_is_a_first_install_not_an_error(monkeypatch):
    """`crontab -l` exits non-zero with "no crontab for <user>" when there is
    none. Reading that as an error is how a first install would fail."""
    monkeypatch.setattr(schedule.sys, "platform", "linux")
    monkeypatch.setattr(schedule.subprocess, "run", _FakeRun([
        (["crontab", "-l"], _proc(1, stderr="no crontab for jeon")),
    ]))
    assert schedule._read_crontab() == ""


def test_launchd_install_that_does_not_load_hands_back_the_command(monkeypatch, tmp_path):
    """No macOS here to run `launchctl` on, so the protection is the read-back:
    a wrong command for someone's macOS version leaves them with instructions,
    never with an agent they believe is loaded."""
    monkeypatch.setattr(schedule.sys, "platform", "darwin")
    monkeypatch.setattr(schedule.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(schedule.subprocess, "run", _FakeRun([
        (["launchctl", "unload"], _proc(1)),
        (["launchctl", "load"], _proc(0)),
        (["launchctl", "list"], _proc(1, stderr="Could not find service")),
    ]))

    ok, message = schedule.install(15)
    assert ok is False
    assert "launchctl list com.boxdawn.submit" in message
    assert "launchctl load -w" in message
    # the plist is still written, so pasting the load command is enough
    assert (tmp_path / "Library" / "LaunchAgents"
            / "com.boxdawn.submit.plist").exists()


def test_launchd_plist_names_this_interpreter_and_the_interval(monkeypatch, tmp_path):
    monkeypatch.setattr(schedule.Path, "home", staticmethod(lambda: tmp_path))
    plist = schedule._launchd_plist(15, schedule.SUBMIT_ARGS)
    assert "<key>Label</key><string>com.boxdawn.submit</string>" in plist
    assert "<key>StartInterval</key><integer>900</integer>" in plist
    assert f"<string>{sys.executable}</string>" in plist or "python" in plist
    assert "<string>submit</string>" in plist and "<string>--auto</string>" in plist
    # RunAtLoad off: loading the agent must not fire a backfill sweep at once
    assert "<key>RunAtLoad</key><false/>" in plist


def test_the_watch_agent_gets_its_own_label(monkeypatch, tmp_path):
    """Both registrations on one Mac, or the second overwrites the first."""
    assert schedule._launchd_label(schedule.SUBMIT_ARGS) == "com.boxdawn.submit"
    assert schedule._launchd_label(schedule.WATCH_ARGS) == "com.boxdawn.watch"


def test_is_registered_is_no_longer_unknown_on_mac_and_linux(monkeypatch):
    """It returned None for both, and the CLI reads None as "do not judge the
    exit code" -- which is why `--install` there set the submission watermark
    and exited 0 while nothing had been scheduled."""
    monkeypatch.setattr(schedule.sys, "platform", "linux")
    monkeypatch.setattr(schedule.subprocess, "run", _FakeRun([
        (["crontab", "-l"], _proc(0, stdout="# >>> boxdawn BoxdawnSubmit >>>\n")),
    ]))
    assert schedule.is_registered() is True

    monkeypatch.setattr(schedule.sys, "platform", "darwin")
    monkeypatch.setattr(schedule.subprocess, "run", _FakeRun([
        (["launchctl", "list"], _proc(0, stdout="{}")),
    ]))
    assert schedule.is_registered() is True

    monkeypatch.setattr(schedule.sys, "platform", "aix")
    assert schedule.is_registered() is None
