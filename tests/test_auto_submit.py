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
from datetime import datetime, timedelta, timezone

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
    """The watermark narrows the rule, it does not replace it."""
    _session(tmp_path / "busy.jsonl", NOW - timedelta(minutes=30))
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
