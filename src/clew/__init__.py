"""Clew — wasteful-cycle detection in multi-agent traces (by Custos)."""

from importlib import metadata as _metadata

try:
    __version__ = _metadata.version("clew-custos")
except _metadata.PackageNotFoundError:
    # Fresh clone without pip install — running only via the
    # tests/conftest.py sys.path shim, so there is no dist metadata
    # to read. Never occurs in a pip-installed package.
    # ★ Not a number: the project rule is to say "unknown" rather
    #   than invent a value (same rule as token_count).
    __version__ = "unknown"
