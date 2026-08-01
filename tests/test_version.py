"""tests/test_version.py — lock `clew.__version__` to `pyproject.toml`.

Prevents the stale-`__version__` drift that hid across multiple releases
(discovered at v0.4.0: pyproject.toml had rolled to 0.3.2 while
`src/clew/__init__.py` still hard-coded `__version__ = "0.1.0"`). Since
v0.4.0 the version is derived automatically from package metadata via
`importlib.metadata`, so drift is now structurally impossible when the
package is installed (pip / editable). These tests lock that structure
in place and pin the fallback wording for the fresh-clone case.
"""
from __future__ import annotations

import importlib
import importlib.metadata as _metadata
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest


def test_version_matches_pyproject_toml():
    """`__version__` must equal the version field in `pyproject.toml`."""
    import clew

    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )
    expected = pyproject["project"]["version"]
    assert clew.__version__ == expected, (
        f"__version__ ({clew.__version__!r}) differs from pyproject.toml "
        f"({expected!r}). Since v0.4.0 the version is derived automatically "
        f"via importlib.metadata — if these values differ, either the "
        f"package metadata (egg-info / dist-info) is stale (re-run the "
        f"editable install) or pyproject.toml itself was edited but not "
        f"released."
    )


def test_version_falls_back_to_literal_unknown_when_metadata_missing():
    """When `importlib.metadata.version` raises `PackageNotFoundError`
    (fresh clone with no pip install, running only via the
    `tests/conftest.py` PYTHONPATH shim), `__version__` must fall back
    to the literal `"unknown"`. Not a fake version number like
    `"0.0.0+source"`: the project rule is to say we don't know rather
    than invent a plausibly-parseable value."""
    import clew

    with patch(
        "importlib.metadata.version",
        side_effect=_metadata.PackageNotFoundError("clew-custos"),
    ):
        importlib.reload(clew)
        assert clew.__version__ == "unknown"

    # Restore the real version for any downstream test that reads it.
    importlib.reload(clew)
    # Sanity: in this test environment the package IS installed, so
    # after reload the fallback must NOT be active.
    assert clew.__version__ != "unknown"
