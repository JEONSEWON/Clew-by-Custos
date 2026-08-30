"""src/clew/setup.py — turn a fresh install into a configured one.

Before this, a new user had a wall between "I made a key on the website" and
"submission runs": two YAML files to hand-write, one of them holding absolute
paths into `~/.claude/projects`, whose directory names are the project path
with every separator replaced by a dash —

    C--Users-User-Desktop-Custos---clwe-project

Nobody should have to decode that. Each session file records the `cwd` it ran
in, so the readable name is already in the data and this module reads it back
out.

Per-project routing exists because the alert rule compares a day against the
previous day within one baseline, and a project is one baseline; two codebases
under one key make the rate answer "which project did I work on today". That
is worth a config file. It is not worth a config file the user writes by hand.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from clew.submit import (
    CREDENTIALS_PATH,
    DEFAULT_ROOT,
    KEY_PREFIX,
    PROJECTS_PATH,
    last_activity,
)


_SEPARATORS = ("/", chr(92))


@dataclass(frozen=True)
class Discovered:
    """One trace folder, named the way its owner would recognise it."""

    directory: Path          # the mangled folder under ~/.claude/projects
    workspace: str | None    # the `cwd` the sessions ran in, when recorded
    sessions: int
    last_seen: datetime | None

    @property
    def label(self) -> str:
        """What to show a person. Falls back to the folder when `cwd` is absent.

        The basename is taken without `Path`, because the path being named was
        recorded on whichever machine ran the agent and is being read on
        whichever machine is looking. `Path` only understands the separator of
        the host it runs on, so a Windows `cwd` read on Linux — which is the
        hosted analyzer's normal case — comes back whole, and the user is shown
        the full path where a folder name belongs.
        """
        if self.workspace:
            trimmed = self.workspace.rstrip("".join(_SEPARATORS))
            for sep in _SEPARATORS:
                trimmed = trimmed.rsplit(sep, 1)[-1]
            return trimmed or self.workspace
        return self.directory.name


def _workspace_of(directory: Path) -> str | None:
    """The `cwd` recorded in this folder's sessions.

    Reads the head of one file rather than all of them: `cwd` is written on
    every entry, so the first one that carries it answers the question. A
    folder whose sessions predate the field simply has no readable name, which
    the label property handles rather than guessing.
    """
    for path in sorted(directory.rglob("*.jsonl")):
        try:
            with path.open(encoding="utf-8", errors="replace") as fh:
                for _ in range(40):
                    line = fh.readline()
                    if not line:
                        break
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    cwd = entry.get("cwd")
                    if cwd:
                        return str(cwd)
        except OSError:
            continue
    return None


def discover(root: Path = DEFAULT_ROOT) -> list[Discovered]:
    """Trace folders on this machine, most recently used first.

    Sorted by recency because the folder someone wants to configure is almost
    always the one they were just working in.
    """
    found: list[Discovered] = []
    if not root.is_dir():
        return found
    for directory in sorted(root.iterdir()):
        if not directory.is_dir():
            continue
        files = list(directory.rglob("*.jsonl"))
        if not files:
            continue
        stamps = [t for t in (last_activity(f) for f in files) if t is not None]
        found.append(Discovered(
            directory=directory,
            workspace=_workspace_of(directory),
            sessions=len(files),
            last_seen=max(stamps) if stamps else None,
        ))
    found.sort(key=lambda d: (d.last_seen is not None, d.last_seen), reverse=True)
    return found


def key_shape_problem(key: str) -> str | None:
    """Why this string cannot be a submission key, or None.

    Shape only. Whether the key is live, unrevoked, and bound to a project is
    a question only the server can answer, and this deliberately does not
    pretend otherwise — see the caller's message.
    """
    key = key.strip()
    if not key:
        return "empty"
    if not key.startswith(KEY_PREFIX):
        return f"does not start with {KEY_PREFIX!r} — is this the key and not the project id?"
    if len(key) <= len(KEY_PREFIX) + 8:
        return "too short to be a key"
    if any(c.isspace() for c in key):
        return "contains whitespace — it may have been copied with a line break"
    return None


def _write_yaml(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_credentials(key: str, path: Path = CREDENTIALS_PATH) -> Path:
    """Single-key config: one key, the whole `~/.claude/projects` tree."""
    _write_yaml(path, f"api_key: {key.strip()}\n")
    return path


def _same_folder(raw: object, target: Path) -> bool:
    """Whether a config entry names the same folder as `target`."""
    if not raw:
        return False
    try:
        return Path(str(raw)).expanduser() == target
    except (OSError, ValueError):
        return False


def upsert_project(name: str, root: Path, key: str,
                   path: Path = PROJECTS_PATH) -> tuple[Path, str]:
    """Add or replace one entry in `projects.yaml`. Returns (path, action).

    Matched by `root`, not by `name`: the root is what decides which sessions
    are sent, and `load_targets` refuses a file where two entries share one.
    Matching by name would let a rename create a second entry for the same
    folder, which is exactly the duplicate that refusal exists to catch.
    """
    import yaml

    try:
        entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    except (OSError, ValueError):
        entries = []
    if not isinstance(entries, list):
        entries = []

    # Compared as paths, not as strings. A config written by hand (or by an
    # earlier version) may spell the same folder with forward slashes where
    # this module produces the native separator; string equality then reports
    # "added" and leaves two entries for one folder. `load_targets` compares
    # paths, so it would refuse the whole file on the next run, and one
    # reconfiguration would stop submission for every project at once.
    target = Path(root).expanduser()
    action = "added"
    for entry in entries:
        if isinstance(entry, dict) and _same_folder(entry.get("root"), target):
            entry["project"] = name
            entry["api_key"] = key.strip()
            action = "updated"
            break
    else:
        entries.append({"project": name, "root": str(target), "api_key": key.strip()})

    _write_yaml(path, yaml.safe_dump(entries, allow_unicode=True, sort_keys=False))
    return path, action
