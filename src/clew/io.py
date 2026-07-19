"""src/clew/io.py - Trace JSON serialization round-trip.

save_trace / load_trace: wrappers for pydantic v2 model_dump_json / model_validate_json.
"""

from __future__ import annotations

from pathlib import Path

from clew.model import Trace


def save_trace(trace: Trace, path: Path) -> None:
    """Save Trace to a JSON file (UTF-8, indent=2)."""
    path.write_text(trace.model_dump_json(indent=2), encoding="utf-8")


def load_trace(path: Path) -> Trace:
    """Load a Trace from a JSON file.

    Raises:
        FileNotFoundError: file not found.
        ValueError: JSON parse failure or schema mismatch.
    """
    try:
        return Trace.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"invalid trace file — {exc}") from exc
