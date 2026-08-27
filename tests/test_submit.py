"""submit (SESSION_CLOSE_RULE_PREREG §5) — R1/R2/R3 and what never travels.

Tests cover:
  1. R1 — closed only after CLOSE_AFTER of silence, measured from in-file
     timestamps; a file with no timestamps is skipped rather than guessed at
  2. R2 — a path in the ledger is never queued again, and the ledger is
     written after each submission so an interrupted run does not resend
  3. R3 — discovery reaches sub-agent traces a directory deeper
  4. Credentials — environment beats the file, and clew.yaml is never read
  5. A first run is a backfill, so dry-run sends nothing and a wrong-looking
     key is refused before any upload
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from clew import submit

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def _session(path, last: datetime, lines: int = 3):
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(lines):
        when = last - timedelta(minutes=lines - 1 - i)
        rows.append(json.dumps({"type": "assistant",
                                "timestamp": when.isoformat().replace("+00:00", "Z")}))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


# ── R1: closed on inactivity ───────────────────────────────────────────────


def _http_error(code: int, body: dict):
    class _Exc:
        def __init__(self):
            self.code = code
            self._body = json.dumps(body).encode("utf-8")

        def read(self):
            return self._body

    return _Exc()

@pytest.mark.parametrize("idle_min, closed", [
    (239, False),
    (240, True),    # the boundary is inclusive: "at least N older"
    (241, True),
    (60, False),    # the rejected threshold — prereg §4, 29% of sessions
])

def test_close_boundary(tmp_path, idle_min, closed):
    f = _session(tmp_path / "s.jsonl", NOW - timedelta(minutes=idle_min))
    assert submit.is_closed(f, NOW) is closed


def test_a_file_without_timestamps_is_never_closed(tmp_path):
    f = tmp_path / "no-stamps.jsonl"
    f.write_text(json.dumps({"type": "system"}) + "\n", encoding="utf-8")

    # The rule is written against recorded events. With none, the rule cannot
    # be applied, and guessing from mtime would submit on a backup's schedule.
    assert submit.last_activity(f) is None
    assert submit.is_closed(f, NOW) is False


def test_last_activity_takes_the_newest_not_the_last_line(tmp_path):
    f = tmp_path / "unordered.jsonl"
    early = "2026-08-26T01:00:00Z"
    late = "2026-08-26T05:00:00Z"
    f.write_text("\n".join([
        json.dumps({"timestamp": late}),
        json.dumps({"timestamp": early}),      # out of order on purpose
        json.dumps({"type": "system"}),        # no timestamp at all
        "not json",                            # and a line that is not json
    ]) + "\n", encoding="utf-8")

    assert submit.last_activity(f) == datetime(2026, 8, 26, 5, 0, tzinfo=timezone.utc)


# ── R3: recursive discovery ────────────────────────────────────────────────

def test_discovery_reaches_subagent_traces(tmp_path):
    _session(tmp_path / "proj" / "top.jsonl", NOW)
    _session(tmp_path / "proj" / "sess" / "subagents" / "agent-1.jsonl", NOW)

    found = {p.name for p in submit.discover(tmp_path)}

    # 13 of 84 files on the measured corpus live at this depth, and sub-agents
    # are where waste concentrates.
    assert found == {"top.jsonl", "agent-1.jsonl"}


def test_discovery_of_a_missing_root_is_empty_not_an_error(tmp_path):
    assert submit.discover(tmp_path / "nope") == []


# ── R2: the ledger ─────────────────────────────────────────────────────────

def test_pending_skips_what_the_ledger_has(tmp_path):
    old = _session(tmp_path / "old.jsonl", NOW - timedelta(hours=9))
    other = _session(tmp_path / "other.jsonl", NOW - timedelta(hours=9))

    assert set(submit.pending(tmp_path, NOW, {})) == {old, other}
    assert submit.pending(tmp_path, NOW, {str(old): {"stored": True}}) == [other]


def test_a_failed_attempt_is_retried(tmp_path):
    f = _session(tmp_path / "failed.jsonl", NOW - timedelta(hours=9))

    # http_500 created no run row, so R2 has nothing to protect and the
    # session is lost forever if the ledger counts this as sent.
    ledger = {str(f): {"ok": False, "reason": "http_500"}}
    assert submit.pending(tmp_path, NOW, ledger) == [f]


def test_a_server_that_declined_to_store_is_not_retried(tmp_path):
    f = _session(tmp_path / "declined.jsonl", NOW - timedelta(hours=9))

    # The server received it, analyzed it, and decided. Re-running a paid
    # analysis does not change that decision.
    ledger = {str(f): {"ok": True, "stored": False, "reason": "ingest disabled"}}
    assert submit.pending(tmp_path, NOW, ledger) == []


def test_a_grown_file_is_still_not_resent(tmp_path):
    f = _session(tmp_path / "grown.jsonl", NOW - timedelta(hours=9))
    ledger = {str(f): {"stored": True}}

    # It grew and went quiet again. A different payload hash means the database
    # would not catch the second copy, so the client is what has to.
    _session(f, NOW - timedelta(hours=5), lines=9)
    assert submit.pending(tmp_path, NOW, ledger) == []


def test_ledger_round_trip(tmp_path):
    path = tmp_path / "nested" / "submitted.json"
    submit.save_ledger({"a": {"stored": True}}, path)
    assert submit.load_ledger(path) == {"a": {"stored": True}}


def test_unreadable_ledger_reads_as_empty(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{ not json", encoding="utf-8")
    assert submit.load_ledger(path) == {}


# ── credentials ────────────────────────────────────────────────────────────

def test_environment_beats_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv(submit.KEY_ENV, "  bdk_from_env  ")
    monkeypatch.setattr(submit, "CREDENTIALS_PATH", tmp_path / "credentials.yaml")
    (tmp_path / "credentials.yaml").write_text("api_key: bdk_from_file\n", encoding="utf-8")

    # CI and containers cannot be handed a file, and that is where unattended
    # submission belongs.
    assert submit.read_key() == "bdk_from_env"


def test_falls_back_to_the_credentials_file(tmp_path, monkeypatch):
    monkeypatch.delenv(submit.KEY_ENV, raising=False)
    monkeypatch.setattr(submit, "CREDENTIALS_PATH", tmp_path / "credentials.yaml")
    (tmp_path / "credentials.yaml").write_text("api_key: bdk_from_file\n", encoding="utf-8")

    assert submit.read_key() == "bdk_from_file"


def test_no_key_anywhere_is_none_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.delenv(submit.KEY_ENV, raising=False)
    monkeypatch.setattr(submit, "CREDENTIALS_PATH", tmp_path / "absent.yaml")
    assert submit.read_key() is None


def test_a_key_beside_a_trace_is_never_found(tmp_path, monkeypatch):
    # clew.yaml is discovered by walking up from the trace file, which makes it
    # a file people keep in a repository. Anything the key lookup can reach by
    # walking up is a way to commit a credential, so the lookup must not walk.
    monkeypatch.delenv(submit.KEY_ENV, raising=False)
    monkeypatch.setattr(submit, "CREDENTIALS_PATH", tmp_path / "home" / "credentials.yaml")

    project = tmp_path / "someones-repo"
    project.mkdir()
    (project / "clew.yaml").write_text("api_key: bdk_committed_by_mistake\n",
                                       encoding="utf-8")
    (project / "config.yaml").write_text("api_key: bdk_also_wrong\n", encoding="utf-8")
    monkeypatch.chdir(project)

    assert submit.read_key() is None


# ── the run ────────────────────────────────────────────────────────────────

def _no_network(monkeypatch):
    calls = []

    def fake(path, key, endpoint=submit.DEFAULT_ENDPOINT, timeout=600):
        calls.append((path, key, endpoint))
        return {"ok": True, "trace_id": path.stem, "stored": True, "reason": "ok"}

    monkeypatch.setattr(submit, "submit_file", fake)
    return calls


def test_dry_run_sends_nothing(tmp_path, monkeypatch):
    _session(tmp_path / "a.jsonl", NOW - timedelta(hours=9))
    calls = _no_network(monkeypatch)
    lines = []

    code = submit.run(root=tmp_path, dry_run=True, now=NOW,
                      ledger_path=tmp_path / "l.json", out=lines.append)

    assert code == 0
    assert calls == []
    assert not (tmp_path / "l.json").exists()
    assert "would submit 1 session" in lines[0]


def test_a_key_that_is_not_a_submission_key_is_refused_before_upload(tmp_path, monkeypatch):
    _session(tmp_path / "a.jsonl", NOW - timedelta(hours=9))
    calls = _no_network(monkeypatch)
    monkeypatch.setenv(submit.KEY_ENV, "eyJhbGciOiJIUzI1NiJ9.abc.sig")

    code = submit.run(root=tmp_path, now=NOW, pace_seconds=0,
                      ledger_path=tmp_path / "l.json", out=lambda _: None)

    # Sending a session token to a server that will reject it anyway is a way
    # to put a credential on the wire for nothing.
    assert code == 2
    assert calls == []


def test_a_run_records_each_submission_as_it_goes(tmp_path, monkeypatch):
    _session(tmp_path / "a.jsonl", NOW - timedelta(hours=9))
    _session(tmp_path / "b.jsonl", NOW - timedelta(hours=9))
    monkeypatch.setenv(submit.KEY_ENV, "bdk_test")
    ledger_path = tmp_path / "l.json"

    seen = []

    def fake(path, key, endpoint=submit.DEFAULT_ENDPOINT, timeout=600):
        # An interrupted run must not resend what it already sent, so the
        # ledger has to be on disk before the next upload starts.
        seen.append(set(submit.load_ledger(ledger_path)))
        return {"ok": True, "trace_id": path.stem, "stored": True, "reason": "ok"}

    monkeypatch.setattr(submit, "submit_file", fake)

    code = submit.run(root=tmp_path, now=NOW, pace_seconds=0,
                      ledger_path=ledger_path, out=lambda _: None)

    assert code == 0
    assert seen[0] == set()
    assert seen[1] == {str(tmp_path / "a.jsonl")}
    assert set(submit.load_ledger(ledger_path)) == {
        str(tmp_path / "a.jsonl"), str(tmp_path / "b.jsonl")}


def test_a_run_that_stores_nothing_exits_nonzero(tmp_path, monkeypatch):
    _session(tmp_path / "a.jsonl", NOW - timedelta(hours=9))
    monkeypatch.setenv(submit.KEY_ENV, "bdk_test")
    monkeypatch.setattr(submit, "submit_file",
                        lambda *a, **k: {"ok": False, "reason": "bad_key"})

    code = submit.run(root=tmp_path, now=NOW, pace_seconds=0,
                      ledger_path=tmp_path / "l.json", out=lambda _: None)

    assert code == 1
    # Recorded anyway: a refused key is a fact, and R2 is about not repeating
    # an upload, not about whether it succeeded.
    assert submit.load_ledger(tmp_path / "l.json")[str(tmp_path / "a.jsonl")] == {
        "ok": False, "reason": "bad_key", "submitted_at": NOW.isoformat()}


def test_limit_caps_a_backfill(tmp_path, monkeypatch):
    for name in "abc":
        _session(tmp_path / f"{name}.jsonl", NOW - timedelta(hours=9))
    calls = _no_network(monkeypatch)
    monkeypatch.setenv(submit.KEY_ENV, "bdk_test")

    submit.run(root=tmp_path, now=NOW, pace_seconds=0, limit=2,
               ledger_path=tmp_path / "l.json", out=lambda _: None)

    assert len(calls) == 2


def test_nothing_to_submit_is_success(tmp_path, monkeypatch):
    _session(tmp_path / "fresh.jsonl", NOW - timedelta(minutes=5))
    calls = _no_network(monkeypatch)
    lines = []

    code = submit.run(root=tmp_path, now=NOW, ledger_path=tmp_path / "l.json",
                      out=lines.append)

    assert code == 0
    assert calls == []
    assert "nothing to submit" in lines[0]


# ── what travels ───────────────────────────────────────────────────────────

def test_multipart_carries_the_bytes_and_names_the_field(tmp_path):
    f = _session(tmp_path / "trace.jsonl", NOW)
    boundary, body = submit._multipart(f)

    assert f'name="file"'.encode() in body
    assert b'filename="trace.jsonl"' in body
    assert f.read_bytes() in body
    assert body.startswith(f"--{boundary}".encode())
    assert body.endswith(f"--{boundary}--\r\n".encode())


def test_a_failure_records_the_servers_error_id(tmp_path):
    exc = _http_error(422, {"detail": {"error_id": "abc12345", "stderr": "secret trace text"}})
    assert submit._failure_detail(exc) == {"error_id": "abc12345"}


def test_a_failure_never_copies_the_analyzer_stderr(tmp_path):
    exc = _http_error(422, {"detail": {"error_id": "abc12345", "stderr": "secret trace text"}})
    assert "secret trace text" not in json.dumps(submit._failure_detail(exc))


def test_a_string_detail_is_kept_as_the_servers_own_sentence(tmp_path):
    exc = _http_error(500, {"detail": "analyzer did not produce a JSON report"})
    assert submit._failure_detail(exc) == {"detail": "analyzer did not produce a JSON report"}


def test_a_body_that_cannot_be_read_is_not_a_crash(tmp_path):
    class Unreadable:
        def read(self):
            raise OSError("connection reset")

    assert submit._failure_detail(Unreadable()) == {}
