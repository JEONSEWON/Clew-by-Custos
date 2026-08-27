"""tests/test_estimate_cli.py — `boxdawn estimate` reports, and does not judge.

The command exists because analysis time does not follow file size. Measured on
four Claude Code traces it follows cumulative context at 368-440 s/GB locally,
while a 5.24 MB trace finished in 40 s and a 3.39 MB one took 85 s. A caller
deciding where to send a trace needs the context figure; a byte cap would refuse
traces that work.

The values-only contract is the part worth pinning. How big is too big depends
on the ceiling of whoever is asking -- a browser upload with a person waiting
(240 s) or an unattended queue with nobody waiting (3480 s) -- and a verdict
computed here would hide which ceiling it was measured against.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from clew.__main__ import main


def _cc_session(path: Path, turns: int = 3) -> Path:
    """A minimal Claude Code JSONL: `sessionId` on the first line is the marker."""
    lines = [json.dumps({
        "type": "user",
        "sessionId": "s-estimate",
        "uuid": "u0",
        "parentUuid": None,
        "timestamp": "2026-08-27T00:00:00.000Z",
        "message": {"role": "user", "content": "hello"},
    })]
    for i in range(turns):
        lines.append(json.dumps({
            "type": "assistant",
            "sessionId": "s-estimate",
            "uuid": f"a{i}",
            "parentUuid": "u0" if i == 0 else f"a{i - 1}",
            "timestamp": f"2026-08-27T00:0{i + 1}:00.000Z",
            "message": {
                "role": "assistant",
                "model": "claude-opus-5",
                "usage": {"input_tokens": 100 * (i + 1), "output_tokens": 10},
                "content": [{"type": "text", "text": "x" * 500}],
            },
        }))
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _run(argv: list[str], monkeypatch) -> int:
    monkeypatch.setattr(sys, "argv", ["boxdawn", *argv])
    with pytest.raises(SystemExit) as exit_info:
        main()
    return exit_info.value.code


def test_it_reports_cumulative_context_not_only_size(tmp_path, monkeypatch, capsys):
    trace = _cc_session(tmp_path / "t.jsonl")

    code = _run(["estimate", str(trace), "--json"], monkeypatch)
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["cumulative_context_bytes"] > 0
    assert payload["llm_calls"] > 0
    # Both are reported, because the interesting fact about them is that they
    # disagree -- reporting only one invites the reader to use it as the other.
    assert payload["file_bytes"] == trace.stat().st_size


def test_it_does_not_judge(tmp_path, monkeypatch, capsys):
    """No verdict, no ceiling, no threshold.

    The caller owns the threshold because it differs per surface. A verdict here
    would carry one surface's ceiling into every consumer without saying which.
    """
    trace = _cc_session(tmp_path / "t.jsonl")
    _run(["estimate", str(trace), "--json"], monkeypatch)
    out = capsys.readouterr().out
    payload = json.loads(out)

    verdicts = ("too_heavy", "too_large", "exceeds", "limit", "limit_seconds",
                "ok", "fits", "will_fail", "verdict", "threshold",
                "projected_seconds", "estimated_seconds")
    assert [k for k in payload if k in verdicts] == []
    # Not in the prose either.
    lowered = out.lower()
    assert "too heavy" not in lowered and "too large" not in lowered


def test_the_summary_names_what_the_number_is_for(tmp_path, monkeypatch, capsys):
    """A reader who sees two byte figures needs to know which one predicts."""
    trace = _cc_session(tmp_path / "t.jsonl")

    _run(["estimate", str(trace)], monkeypatch)
    out = capsys.readouterr().out

    assert "cumulative ctx" in out
    assert "analysis time follows" in out


def test_a_missing_file_exits_nonzero(tmp_path, monkeypatch, capsys):
    code = _run(["estimate", str(tmp_path / "absent.jsonl")], monkeypatch)

    assert code == 1
    assert "error" in capsys.readouterr().err.lower()


def test_an_unreadable_format_exits_nonzero_rather_than_guessing(tmp_path, monkeypatch, capsys):
    """The same dispatcher `analyze` uses, so the same formats and no others.

    Reusing it is the point: a second copy of format detection is how the two
    would come to disagree about what a file is.
    """
    trace = tmp_path / "t.jsonl"
    trace.write_text(json.dumps({"type": "session", "id": "x"}), encoding="utf-8")

    code = _run(["estimate", str(trace)], monkeypatch)

    assert code == 1
