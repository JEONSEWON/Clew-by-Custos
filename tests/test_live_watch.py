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
    candidates does not pay for the ones after the hit."""
    trace = _trace([
        _span("a", "llm", "plan", "same plan", 0),
        _span("b", "llm", "plan", "same plan", 1),
        _span("c", "llm", "other", "same other", 2),
        _span("d", "llm", "other", "same other", 3),
    ])
    embedder = _FixedEmbedder()
    live.first_confirmed(trace, embedder, n=2, phi=0.5)
    assert embedder.calls == 2


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


def test_watch_once_writes_the_ledger(sessions, tmp_path):
    path = tmp_path / "live_findings.json"
    live.watch([("p", sessions)], _FixedEmbedder(), 2, 0.5,
               findings_path=path, once=True)
    recorded = live.load_findings(path)
    assert len(recorded) == 2
    assert all(f.delivered is False for f in recorded)


def test_the_shipped_module_cannot_send(monkeypatch):
    """§2, §8 step 2: shadow means there is nothing here that could send.

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
