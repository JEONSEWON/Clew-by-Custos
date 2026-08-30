"""setup — the wall between "I made a key" and "submission runs".

The two things that make this command worth existing are the two things
tested hardest here: that a trace folder is named the way its owner would
recognise it, and that configuring a second project does not silently create
a duplicate of the first.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from clew import setup

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _session(path, last: datetime, cwd: str | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"type": "assistant",
           "timestamp": last.isoformat().replace("+00:00", "Z")}
    if cwd:
        row["cwd"] = cwd
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    return path


# ── naming ─────────────────────────────────────────────────────────────────


def test_a_folder_is_named_by_the_directory_it_ran_in(tmp_path):
    """Distinguishes: the folder is `C--Users-User-Desktop-My-App`, and showing
    that to a person is the wall this command exists to remove."""
    root = tmp_path / "projects"
    _session(root / "C--Users-User-Desktop-My-App" / "s.jsonl", NOW,
             cwd=r"C:\Users\User\Desktop\My App")
    found = setup.discover(root)
    assert len(found) == 1
    assert found[0].label == "My App"
    assert found[0].directory.name == "C--Users-User-Desktop-My-App"


def test_a_folder_without_cwd_falls_back_to_its_directory_name(tmp_path):
    """Older sessions predate the field. A missing name is not a crash and not
    a guess — it is the folder, which at least resolves to something real."""
    root = tmp_path / "projects"
    _session(root / "C--old-project" / "s.jsonl", NOW)
    found = setup.discover(root)
    assert found[0].label == "C--old-project"


def test_folders_come_back_most_recent_first(tmp_path):
    """The folder someone wants to configure is the one they just worked in."""
    root = tmp_path / "projects"
    _session(root / "aaa-stale" / "s.jsonl", NOW - timedelta(days=30), cwd="/x/stale")
    _session(root / "zzz-fresh" / "s.jsonl", NOW, cwd="/x/fresh")
    assert [d.label for d in setup.discover(root)] == ["fresh", "stale"]


def test_a_folder_with_no_sessions_is_not_offered(tmp_path):
    root = tmp_path / "projects"
    (root / "empty").mkdir(parents=True)
    _session(root / "real" / "s.jsonl", NOW, cwd="/x/real")
    assert [d.label for d in setup.discover(root)] == ["real"]


def test_a_missing_root_is_empty_not_an_error(tmp_path):
    assert setup.discover(tmp_path / "absent") == []


# ── key shape ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("key,fragment", [
    ("", "empty"),
    ("sk_live_abcdefghij", "does not start with"),
    ("bdk_short", "too short"),
    ("bdk_abcdefghij\nklmnop", "whitespace"),
])
def test_a_key_that_cannot_work_is_refused_with_the_reason(key, fragment):
    problem = setup.key_shape_problem(key)
    assert problem is not None and fragment in problem


def test_a_well_shaped_key_passes():
    assert setup.key_shape_problem("bdk_" + "a" * 24) is None


# ── writing ────────────────────────────────────────────────────────────────


def test_credentials_are_written_in_the_shape_submit_reads(tmp_path):
    path = setup.write_credentials("bdk_" + "a" * 24, tmp_path / "credentials.yaml")
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["api_key"] == "bdk_" + "a" * 24


def test_a_second_project_is_added_beside_the_first(tmp_path):
    cfg = tmp_path / "projects.yaml"
    setup.upsert_project("a", tmp_path / "ra", "bdk_" + "a" * 24, cfg)
    _, action = setup.upsert_project("b", tmp_path / "rb", "bdk_" + "b" * 24, cfg)
    entries = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert action == "added"
    assert [e["project"] for e in entries] == ["a", "b"]
    assert len({e["root"] for e in entries}) == 2


def test_reconfiguring_a_folder_replaces_it_rather_than_duplicating(tmp_path):
    """Distinguishes: two entries sharing a root make `load_targets` refuse the
    whole file, so a user rotating a key would break submission for every
    project at once."""
    cfg = tmp_path / "projects.yaml"
    setup.upsert_project("a", tmp_path / "ra", "bdk_" + "a" * 24, cfg)
    _, action = setup.upsert_project("a", tmp_path / "ra", "bdk_" + "z" * 24, cfg)
    entries = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert action == "updated"
    assert len(entries) == 1
    assert entries[0]["api_key"] == "bdk_" + "z" * 24


def test_a_rename_updates_the_entry_it_already_had(tmp_path):
    """Matched by root, not by name: matching by name would let a renamed
    project create a second entry for the same folder."""
    cfg = tmp_path / "projects.yaml"
    setup.upsert_project("old-name", tmp_path / "ra", "bdk_" + "a" * 24, cfg)
    setup.upsert_project("new-name", tmp_path / "ra", "bdk_" + "a" * 24, cfg)
    entries = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0]["project"] == "new-name"


def test_what_setup_writes_is_what_load_targets_reads(tmp_path):
    """The two modules must agree, and neither is allowed to be the only one
    that knows the shape."""
    from clew import submit

    cfg = tmp_path / "projects.yaml"
    setup.upsert_project("a", tmp_path / "ra", "bdk_" + "a" * 24, cfg)
    setup.upsert_project("b", tmp_path / "rb", "bdk_" + "b" * 24, cfg)
    targets = submit.load_targets(cfg, tmp_path / "unused")
    assert [(t.project, t.api_key) for t in targets] == [
        ("a", "bdk_" + "a" * 24), ("b", "bdk_" + "b" * 24)]


def test_a_folder_spelled_with_other_separators_is_the_same_folder(tmp_path):
    """Distinguishes: a config written by hand, or by an earlier version,
    spells the folder with forward slashes where discovery produces the native
    separator. Compared as strings the second write reports "added" and leaves
    two entries for one folder — and `load_targets` compares paths, so it then
    refuses the whole file, and one reconfiguration stops submission for every
    project at once.

    Found by running the command against a real config, not by a fixture.
    """
    cfg = tmp_path / "projects.yaml"
    root = tmp_path / "ra"
    forward = str(root).replace('\\', "/")
    cfg.write_text(
        yaml.safe_dump([{"project": "a", "root": forward,
                         "api_key": "bdk_" + "a" * 24}]),
        encoding="utf-8")

    _, action = setup.upsert_project("a", root, "bdk_" + "z" * 24, cfg)
    entries = yaml.safe_load(cfg.read_text(encoding="utf-8"))

    assert action == "updated"
    assert len(entries) == 1
    assert entries[0]["api_key"] == "bdk_" + "z" * 24
