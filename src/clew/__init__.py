"""Boxdawn — AI agent observability. Wasteful-cycle detection in multi-agent traces."""

from importlib import metadata as _metadata

try:
    __version__ = _metadata.version("boxdawn")
except _metadata.PackageNotFoundError:
    # Fresh clone without pip install — running only via the
    # tests/conftest.py sys.path shim, so there is no dist metadata
    # to read. Never occurs in a pip-installed package.
    # ★ Not a number: the project rule is to say "unknown" rather
    #   than invent a value (same rule as token_count).
    __version__ = "unknown"
