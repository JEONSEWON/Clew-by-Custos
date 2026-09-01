"""The fast path: what it records, and the two caps that stop it recording.

`docs/LIVE_FAILURE_ALERT_PREREG.md` §2, §3.2, §4. Every test here is about a
rule that document froze, so a failure means the code and the prereg disagree
and one of them has to be corrected on purpose.
"""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from clew import live
from clew.detect.cascade import cascade, confirm_pair
from clew.detect.structural import find_candidates
from clew.model import Span, Trace

T0 = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)


class _FixedEmbedder:
    """Deterministic stand-in: identical text embeds identically."""

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, text: str) -> list[float]:
        self.calls += 1
        return [1.0, 0.0] if "same" in text else [0.0, 1.0]


def _span(sid, kind, node, out, minute, inp="in", parent="root"):
    return Span(
        trace_id="t", span_id=sid, parent_span_id=parent, agent_or_node_id=node,
        span_kind=kind, start_time=T0 + timedelta(minutes=minute),
        end_time=T0 + timedelta(minutes=minute, seconds=1),
        input_text=inp, output_text=out, token_count=10, cost_rate=1e-6,
    )


def _trace(spans):
    """One agent root over the given spans -- Trace wants exactly one, and the
    parent-AGENT gate in `find_repeat_candidates` wants them to share it."""
    root = Span(
        trace_id="t", span_id="root", parent_span_id=None, agent_or_node_id="main",
        span_kind="agent", start_time=T0, end_time=T0 + timedelta(hours=1),
        input_text="", output_text="done",
    )
    return Trace(trace_id="t", spans=[root, *spans], metadata={})


def _repeat_trace():
    """Three tools; the second and third repeat the first, same output."""
    return _trace([
        _span("a", "tool", "Read", "file body", 0),
        _span("b", "tool", "Read", "file body", 5),
        _span("c", "tool", "Read", "file body", 9),
    ])


def _finding(session="s.jsonl", project="p", minute=0, recorded=None):
    return live.Finding(
        project=project, session=session, signal=live.SIGNAL_REPEAT,
        origin_span_id="a", candidate_span_id="b",
        occurred_at=(T0 + timedelta(minutes=minute)).isoformat(),
        recorded_at=(recorded or T0 + timedelta(minutes=minute)).isoformat(),
        candidates_seen=1,
    )


# ── §4: the live verdict is the batch verdict ──────────────────────────────

def test_confirm_pair_agrees_with_cascade_on_every_candidate():
    """§4. The refactor that gave the live path its own entry point must not
    have given it its own opinion: for every structural candidate, the pair
    function and the full cascade agree about that candidate."""
    trace = _trace([
        _span("a", "tool", "Read", "file body", 0),
        _span("b", "tool", "Read", "file body", 5),
        _span("c", "tool", "Grep", "hits: 3", 6),
        _span("d", "tool", "Grep", "hits: 9", 7),
        _span("e", "llm", "plan", "same plan", 8),
        _span("f", "llm", "plan", "same plan", 9),
    ])
    embedder = _FixedEmbedder()
    flagged = set(cascade(trace, embedder, n=2, phi=0.5).waste_span_ids)
    for origin, candidate in find_candidates(trace, 2):
        assert confirm_pair(origin, candidate, embedder, 0.5) == (
            candidate.span_id in flagged
        ), candidate.span_id


def test_first_confirmed_is_the_earliest_pair_not_the_first_grouped():
    """§3.2 fires on the *first* confirmed pair, and P2 is measured from that
    pair's second span. Grouping order is by signature, so a later-grouped tool
    can hold an earlier repeat."""
    trace = _trace([
        _span("a", "tool", "Grep", "hits", 0),
        _span("b", "tool", "Read", "body", 1),
        _span("c", "tool", "Read", "body", 2),      # earliest repeat
        _span("d", "tool", "Grep", "hits", 8),      # later repeat, grouped first
    ])
    origin, candidate = live.first_confirmed(trace, _FixedEmbedder(), n=2, phi=0.5)
    assert (origin.span_id, candidate.span_id) == ("b", "c")


def test_first_confirmed_returns_none_when_outputs_differ():
    trace = _trace([
        _span("a", "tool", "Read", "one body", 0),
        _span("b", "tool", "Read", "another body", 5),
    ])
    assert live.first_confirmed(trace, _FixedEmbedder(), n=2, phi=0.5) is None


def test_confirmation_stops_at_the_first_hit():
    """§3.1's cost claim: confirmation is per pair, so a session with many
    candidates does not pay for the ones after the hit.

    Two `Read` pairs, and only the first is confirmed. `Read` because the
    IDEMPOTENT_TRIGGER amendment skips non-idempotent candidates before
    confirmation -- an `llm` pair, which this test used to use, now costs zero
    embeddings and would make the assertion pass for the wrong reason.
    """
    trace = _trace([
        _span("a", "tool", "Read", "same body", 0, inp='{"f":1}'),
        _span("b", "tool", "Read", "same body", 1, inp='{"f":1}'),
        _span("c", "tool", "Read", "same other", 2, inp='{"f":2}'),
        _span("d", "tool", "Read", "same other", 3, inp='{"f":2}'),
    ])
    embedder = _FixedEmbedder()
    assert live.first_confirmed(trace, embedder, n=2, phi=0.5) is not None
    # A tool pair confirms by sha256, so the embedder is never asked at all.
    assert embedder.calls == 0


# ── §3.2: live only, and one per session ───────────────────────────────────

def test_is_live_splits_on_the_same_clock_submit_uses(tmp_path):
    """A session either belongs to the fast path or to the slow one, and the
    boundary is `CLOSE_AFTER`, so nothing falls between them."""
    path = tmp_path / "s.jsonl"
    path.write_text(json.dumps({"timestamp": T0.isoformat()}) + "\n", encoding="utf-8")
    assert live.is_live(path, T0 + timedelta(minutes=19))
    assert not live.is_live(path, T0 + live.CLOSE_AFTER)


def test_is_live_is_false_without_timestamps(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text(json.dumps({"type": "summary"}) + "\n", encoding="utf-8")
    assert not live.is_live(path, T0)


def test_already_found_is_per_session_and_signal():
    findings = [_finding(session="one.jsonl")]
    assert live.already_found(findings, "one.jsonl", live.SIGNAL_REPEAT)
    assert not live.already_found(findings, "two.jsonl", live.SIGNAL_REPEAT)
    assert not live.already_found(findings, "one.jsonl", "something-else")


def test_hourly_room_counts_the_rolling_hour_per_project():
    now = T0 + timedelta(hours=2)
    recent = [
        _finding(session=f"{i}.jsonl", recorded=now - timedelta(minutes=10 * i))
        for i in range(1, 4)
    ]
    assert not live.hourly_room(recent, "p", now)
    assert live.hourly_room(recent, "other-project", now)
    aged = [_finding(session="old.jsonl", recorded=now - timedelta(minutes=61))]
    assert live.hourly_room(aged + recent[:2], "p", now)


def test_hourly_room_is_a_cap_not_a_maximum_seen():
    assert live.hourly_room([], "p", T0, cap=1)
    assert not live.hourly_room([_finding(recorded=T0)], "p", T0, cap=1)


# ── the ledger ─────────────────────────────────────────────────────────────

def test_findings_round_trip(tmp_path):
    path = tmp_path / "live_findings.json"
    live.save_findings([_finding()], path)
    assert live.load_findings(path) == [_finding()]


def test_load_findings_survives_a_corrupt_file(tmp_path):
    path = tmp_path / "live_findings.json"
    path.write_text("{not json", encoding="utf-8")
    assert live.load_findings(path) == []


def test_an_unknown_row_is_skipped_rather_than_crashing(tmp_path):
    path = tmp_path / "live_findings.json"
    path.write_text(json.dumps({"findings": [{"from": "a later version"}]}),
                    encoding="utf-8")
    assert live.load_findings(path) == []


def test_latency_is_measured_from_the_repeat_not_from_the_scan():
    """P2's clock: the second span, not when the watcher got round to it."""
    f = live.Finding(
        project="p", session="s", signal=live.SIGNAL_REPEAT,
        origin_span_id="a", candidate_span_id="b",
        occurred_at=T0.isoformat(),
        recorded_at=(T0 + timedelta(seconds=90)).isoformat(),
        candidates_seen=2,
    )
    assert f.latency_seconds() == 90.0


# ── one pass ───────────────────────────────────────────────────────────────

@pytest.fixture
def sessions(tmp_path, monkeypatch):
    """Two live session files whose ingest yields a repeating trace."""
    root = tmp_path / "projects"
    root.mkdir()
    for name in ("one.jsonl", "two.jsonl"):
        (root / name).write_text(
            json.dumps({"timestamp": T0.isoformat()}) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        "clew.ingest.claude_code.ingest_claude_code_jsonl",
        lambda path, **kw: _repeat_trace(),
    )
    return root


def test_sweep_records_one_finding_per_session(sessions):
    findings = []
    result = live.sweep(sessions, "p", _FixedEmbedder(), 2, 0.5,
                        T0 + timedelta(minutes=10), findings)
    assert (result.scanned, result.recorded) == (2, 2)
    assert len(findings) == 2
    assert {f.candidate_span_id for f in findings} == {"b"}


def test_sweep_does_not_record_a_session_twice(sessions):
    findings = []
    now = T0 + timedelta(minutes=10)
    live.sweep(sessions, "p", _FixedEmbedder(), 2, 0.5, now, findings)
    again = live.sweep(sessions, "p", _FixedEmbedder(), 2, 0.5, now, findings)
    assert (again.scanned, again.recorded) == (0, 0)
    assert len(findings) == 2


def test_sweep_skips_a_session_that_already_ended(sessions):
    findings = []
    result = live.sweep(sessions, "p", _FixedEmbedder(), 2, 0.5,
                        T0 + live.CLOSE_AFTER, findings)
    assert (result.scanned, result.recorded) == (0, 0)
    assert findings == []


def test_sweep_holds_the_hourly_cap_across_sessions(sessions, monkeypatch):
    """P5's second half. Ten sessions in one project, three findings."""
    for i in range(8):
        (sessions / f"extra{i}.jsonl").write_text(
            json.dumps({"timestamp": T0.isoformat()}) + "\n", encoding="utf-8")
    findings = []
    result = live.sweep(sessions, "p", _FixedEmbedder(), 2, 0.5,
                        T0 + timedelta(minutes=10), findings)
    assert result.scanned == 10
    assert result.recorded == 3
    assert result.suppressed_hourly == 7
    assert len(findings) == 3


def test_a_session_that_will_not_ingest_does_not_stop_the_others(sessions, monkeypatch):
    def explode(path, **kw):
        if path.name == "one.jsonl":
            raise ValueError("half-written line")
        return _repeat_trace()

    monkeypatch.setattr("clew.ingest.claude_code.ingest_claude_code_jsonl", explode)
    findings = []
    result = live.sweep(sessions, "p", _FixedEmbedder(), 2, 0.5,
                        T0 + timedelta(minutes=10), findings)
    assert result.recorded == 1
    assert [f.session for f in findings] == [str(sessions / "two.jsonl")]


def test_the_fixture_clock_is_not_in_the_future():
    """A T0 ahead of now makes `is_live` true for every `now`.

    `is_live` has no lower bound -- it asks whether the last activity is
    *recent*, and a session stamped in the future is trivially that. So a
    future T0 makes any test that reads the real clock pass on a technicality,
    and keeps doing it until real time catches up.

    f61e4e5 shipped exactly that: T0 was twenty hours ahead when it was
    written, `test_watch_once_writes_the_ledger` passed, and CI went red at
    T0 + CLOSE_AFTER with nothing having changed.
    """
    assert T0 < datetime.now(timezone.utc), (
        "T0 is in the future, which makes is_live true regardless of now"
    )


def test_watch_once_writes_the_ledger(sessions, tmp_path):
    """`watch` reads its own clock, so T0 cannot reach it.

    Every other test here calls `sweep` and passes `now`. `watch` takes no
    `now` -- it calls `datetime.now(timezone.utc)` itself -- so the sessions
    have to be stamped from the same clock it uses, or they are stale before
    the sweep starts and it finds nothing.
    """
    stamped = datetime.now(timezone.utc)
    for name in ("one.jsonl", "two.jsonl"):
        (sessions / name).write_text(
            json.dumps({"timestamp": stamped.isoformat()}) + "\n",
            encoding="utf-8")

    path = tmp_path / "live_findings.json"
    live.watch([("p", sessions)], _FixedEmbedder(), 2, 0.5,
               findings_path=path, once=True)
    recorded = live.load_findings(path)
    assert len(recorded) == 2
    assert all(f.delivered is False for f in recorded)


def test_the_watcher_module_still_cannot_send(monkeypatch):
    """The detector cannot reach the network, and delivery lives elsewhere.

    This guard used to say "nothing in this project can send". That stopped
    being true when `live_send.py` landed, and the honest move is to narrow
    what it protects rather than delete it: `live.py` is the module that runs
    on every poll, and keeping it unable to open a socket means turning
    delivery on is a change to the CLI, never a change to the detector.

    Asserted on the file that ships rather than on a mocked call, because a
    watcher that never happens to send during a test is not the same as one
    that cannot. Monkeypatching `urlopen` proves nothing about a module that
    does not import it -- that version of this test passed while asserting
    nothing, which is the shape `feedback_assert_on_shipped_artifact` is about.
    """
    import ast

    source = pathlib.Path(live.__file__).read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
            if node.module.startswith("clew.submit"):
                imported.update(f"clew.submit.{a.name}" for a in node.names)

    forbidden = {"urllib", "http", "socket", "requests", "httpx", "ssl", "smtplib"}
    assert not (imported & forbidden), f"live.py imports {imported & forbidden}"
    assert "clew.submit.submit_file" not in imported
    assert "clew.submit.poll_status" not in imported


# ── the registration, which is the artifact Windows actually reads ─────────

def test_the_watch_task_registers_the_watch_command():
    """What ships to the scheduler is the XML, not the function that built it.

    The whole `Arguments` element, not a substring of it. The substring form
    (`"watch --once --auto" in xml`) passed unchanged when `--send` was added,
    which means it was not measuring the flag that decides whether this machine
    talks to a server every minute. A test that survives the change it exists
    to notice is the shape `feedback_assert_on_shipped_artifact` is about.
    """
    import re

    from clew import schedule

    xml = schedule._task_xml(1, task_args=schedule.WATCH_ARGS, time_limit="PT10M")
    args = re.search(r"<Arguments>([^<]*)</Arguments>", xml)
    assert args, "the registration has no Arguments element"
    assert args.group(1) == "-m clew watch --once --auto --send", args.group(1)
    assert "<Interval>PT1M</Interval>" in xml
    assert "<ExecutionTimeLimit>PT10M</ExecutionTimeLimit>" in xml
    assert "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>" in xml


def test_the_watch_task_keeps_the_power_settings_that_stopped_the_sweep():
    """A laptop on battery is exactly when someone is working, so a watcher
    that skips on battery watches nothing. Same three defaults, same reason as
    the sweep -- measured there as a two and a half hour hole with no error."""
    from clew import schedule

    xml = schedule._task_xml(1, task_args=schedule.WATCH_ARGS)
    assert "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>" in xml
    assert "<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>" in xml
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml


def test_the_sweep_registration_did_not_move():
    """The watcher was added by widening these functions. The submission task
    is what the alert chain runs on, so its definition has to come out
    unchanged from the same code."""
    from clew import schedule

    xml = schedule._task_xml(15)
    assert "submit --auto" in xml
    assert "watch" not in xml
    assert "<Interval>PT15M</Interval>" in xml
    assert "<ExecutionTimeLimit>PT1H</ExecutionTimeLimit>" in xml
    assert schedule.TASK_NAME != schedule.WATCH_TASK_NAME


def test_the_two_tasks_do_not_share_a_name_or_a_log():
    """Two registrations under one name would silently replace each other, and
    one log for both would make each run ambiguous about which task wrote it."""
    from clew import schedule, submit

    assert schedule.WATCH_TASK_NAME not in {schedule.TASK_NAME}
    assert live.WATCH_LOG_PATH != submit.AUTO_LOG_PATH


# ── IDEMPOTENT_TRIGGER_PREREG §2: only calls that cannot change the world ──

def test_a_repeated_shell_command_does_not_alert():
    """The seven pairs that scored 0.0000. `Stop-Process` guarded by `if ($c)`
    prints `stopped` whether or not anything was listening, and `make` re-run
    after thirty calls of editing is a check whose identical output is the
    information. The trace cannot tell either from waste."""
    for tool in ("Bash", "PowerShell"):
        trace = _trace([
            _span("a", "tool", tool, "stopped", 0, inp='{"command":"x"}'),
            _span("b", "tool", tool, "stopped", 5, inp='{"command":"x"}'),
        ])
        assert live.first_confirmed(trace, _FixedEmbedder(), n=2, phi=0.5) is None, tool


@pytest.mark.parametrize("tool", ["Read", "Glob", "Grep", "LS"])
def test_a_repeated_read_still_alerts(tool):
    """The twenty-one that scored 1.0000."""
    trace = _trace([
        _span("a", "tool", tool, "body", 0, inp='{"p":1}'),
        _span("b", "tool", tool, "body", 5, inp='{"p":1}'),
    ])
    assert live.first_confirmed(trace, _FixedEmbedder(), n=2, phi=0.5) is not None


def test_the_category_is_the_shipped_one_and_not_a_list_written_here():
    """§1: the boundary was drawn in July and this amendment found it. A list
    re-declared in `live.py` would drift from the one `analyze` uses, and the
    argument for the restriction is that it was not invented for the occasion."""
    import inspect

    from clew.config import builtin_tools

    source = inspect.getsource(live.alertable)
    assert "builtin_tools" in source
    for name in ("Read", "Glob", "Grep"):
        assert f'"{name}"' not in source, f"{name} hard-coded in live.py"
    for name in ("Bash", "PowerShell"):
        assert f'"{name}"' not in source, f"{name} hard-coded in live.py"

    snapshot = builtin_tools()
    assert {"Read", "Glob", "Grep", "LS"} <= set(snapshot.idempotent)
    assert not ({"Bash", "PowerShell", "Edit", "Write"} & set(snapshot.idempotent))


def test_a_shell_repeat_costs_no_confirmation_at_all():
    """Skipped before confirmation, not after: a session full of repeated shell
    calls must not pay embeddings to be told it has nothing to say."""
    trace = _trace([
        _span(f"s{i}", "tool", "Bash", "same", i, inp='{"command":"x"}')
        for i in range(8)
    ])
    embedder = _FixedEmbedder()
    assert live.first_confirmed(trace, embedder, n=2, phi=0.5) is None
    assert embedder.calls == 0


def test_a_user_who_declares_a_tool_idempotent_gets_alerts_about_it(monkeypatch):
    """§2: `clew.yaml` follows. Somebody who classifies their own read tool
    into the category gets alerted on it, which is the consequence of the
    declaration they made."""
    from clew.config import resolve_user_tools

    tools = resolve_user_tools({"my-fetch": "read_only"}, {})
    trace = _trace([
        _span("a", "tool", "my-fetch", "body", 0, inp='{"u":1}'),
        _span("b", "tool", "my-fetch", "body", 5, inp='{"u":1}'),
    ])
    assert live.first_confirmed(trace, _FixedEmbedder(), n=2, phi=0.5) is None
    assert live.first_confirmed(trace, _FixedEmbedder(), n=2, phi=0.5,
                                tools=tools) is not None


def test_the_batch_path_still_sees_every_tool():
    """§3. This narrows what interrupts a person, not what is measured. A
    repeated shell call is still waste to `cascade` and still enters the cost
    figures -- if this ever stops being true, a stored number moved."""
    trace = _trace([
        _span("a", "tool", "Bash", "stopped", 0, inp='{"command":"x"}'),
        _span("b", "tool", "Bash", "stopped", 5, inp='{"command":"x"}'),
    ])
    result = cascade(trace, _FixedEmbedder(), n=2, phi=0.5)
    assert result.wasteful is True
    assert result.waste_span_ids == ["b"]


# ── LIVE_ALERT_AUTHOR_ONLY_DELIVERY_PREREG: the one place that can send ────

def _sent_finding(**over):
    base = dict(project="p", session="/tmp/abc-123.jsonl", signal="repeat",
                origin_span_id="a", candidate_span_id="b",
                occurred_at=T0.isoformat(),
                recorded_at=(T0 + timedelta(seconds=32)).isoformat(),
                candidates_seen=3, tool="Read")
    base.update(over)
    return live.Finding(**base)


class _Recorder:
    """Stands in for `urlopen`, keeping what was actually sent."""

    def __init__(self, payload=None, raise_with=None):
        self.payload = payload if payload is not None else {
            "ok": True, "recorded": True, "delivery_mode": "email"}
        self.raise_with = raise_with
        self.calls = []

    def __call__(self, request, timeout=None):
        self.calls.append(request)
        if self.raise_with is not None:
            raise self.raise_with
        import io
        import json as _json

        class _Ctx(io.BytesIO):
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

        return _Ctx(_json.dumps(self.payload).encode())


def test_nothing_is_sent_unless_asked(monkeypatch):
    """§2. Off by default, and off is measured by nobody being called."""
    from clew import live_send

    monkeypatch.delenv(live_send.ENV_FLAG, raising=False)
    rec = _Recorder()
    result = live_send.send_finding(_sent_finding(), key="bdk_x", opener=rec)
    assert result.attempted is False and result.reason == "disabled"
    assert rec.calls == []


def test_no_key_means_no_request(monkeypatch):
    from clew import live_send

    rec = _Recorder()
    result = live_send.send_finding(_sent_finding(), flag=True, key="", opener=rec)
    assert result.attempted is False and result.reason == "no_key"
    assert rec.calls == []


def test_the_payload_is_counts_and_never_a_path(monkeypatch):
    """§5 bounds what crosses the wire to an enum with counts. A path names
    somebody's directory layout, and this is the one place anything leaves the
    machine."""
    import json as _json

    from clew import live_send

    rec = _Recorder()
    live_send.send_finding(
        _sent_finding(session=r"C:\Users\Someone\secret-project\abc-123.jsonl"),
        flag=True, key="bdk_x", opener=rec)

    assert len(rec.calls) == 1
    body = _json.loads(rec.calls[0].data.decode("utf-8"))
    assert set(body) == {"session_key", "tool", "occurrences", "latency_seconds"}
    assert body["tool"] == "Read"
    assert body["occurrences"] == 3
    assert body["latency_seconds"] == 32.0

    blob = _json.dumps(body)
    for leak in ("secret-project", "Users", "abc-123", ".jsonl", "\\", "/"):
        assert leak not in blob, f"{leak!r} reached the wire"


def test_the_session_key_is_stable_and_opaque():
    from clew import live_send

    a = live_send.session_key(pathlib.Path("/one/place/abc-123.jsonl"))
    b = live_send.session_key(pathlib.Path("/somewhere/else/abc-123.jsonl"))
    c = live_send.session_key(pathlib.Path("/one/place/def-456.jsonl"))
    assert a == b, "the same session under two paths must dedupe as one"
    assert a != c
    assert len(a) == 32 and all(ch in "0123456789abcdef" for ch in a)


def test_it_posts_to_the_live_route_and_not_to_analyze():
    """`/analyze` would start an analysis, which is the thing §6 P3 counts."""
    from clew import live_send

    rec = _Recorder()
    live_send.send_finding(_sent_finding(), flag=True, key="bdk_x", opener=rec)
    url = rec.calls[0].full_url
    assert url.endswith("/live-finding"), url
    assert "/analyze" not in url


def test_a_failed_send_is_reported_and_not_raised():
    """The finding is already recorded locally, and the local record is what
    the measurement is made of. Losing the mail beats losing the pass."""
    from clew import live_send

    rec = _Recorder(raise_with=OSError("no route to host"))
    result = live_send.send_finding(_sent_finding(), flag=True, key="bdk_x",
                                    opener=rec)
    assert result.attempted is True and result.ok is False
    assert result.reason == "OSError"


def test_the_watcher_does_not_import_the_sender():
    """The separation is the shadow guarantee in shipped form. If `live.py`
    ever imports `live_send`, a poll can send and the guard above stops
    meaning anything."""
    import ast

    source = pathlib.Path(live.__file__).read_text(encoding="utf-8")
    # Both halves of an import statement, because `from clew import live_send`
    # puts the module in `names` and only `clew` in `.module`. The first
    # version of this checked `.module` alone and passed under a mutation that
    # added exactly that line.
    seen = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            seen.add(node.module or "")
            seen.update(f"{node.module or ''}.{a.name}" for a in node.names)
            seen.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            seen.update(a.name for a in node.names)
    offenders = sorted(n for n in seen if "live_send" in n)
    assert not offenders, f"live.py imports the sender: {offenders}"


def test_the_banner_does_not_claim_silence_while_sending():
    """A screen that says "sending nothing" next to a `--send` flag is a
    screen that lies on one of its two paths. Asserted on the source of the
    command rather than on the flag, because the sentence is the artifact."""
    import pathlib as _p

    import clew.__main__ as cli

    source = _p.Path(cli.__file__).read_text(encoding="utf-8")
    watch_fn = source.split("def _watch(")[1].split("\ndef ")[0]
    assert "sending nothing" in watch_fn, "the shadow banner is gone entirely"
    # The claim must sit behind the branch that makes it true.
    before, _, after = watch_fn.partition("sending nothing")
    assert "if sending:" in before, (
        "the shadow banner is printed unconditionally while --send exists"
    )
    assert "--send" in source
