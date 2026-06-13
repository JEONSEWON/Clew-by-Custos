"""src/clew/io.py — Trace JSON 직렬화 왕복.

save_trace / load_trace: pydantic v2 model_dump_json / model_validate_json 래퍼.
"""

from __future__ import annotations

from pathlib import Path

from clew.model import Trace


def save_trace(trace: Trace, path: Path) -> None:
    """Trace를 JSON 파일로 저장 (UTF-8, indent=2)."""
    path.write_text(trace.model_dump_json(indent=2), encoding="utf-8")


def load_trace(path: Path) -> Trace:
    """JSON 파일에서 Trace를 로드.

    Raises:
        FileNotFoundError: 파일 없음.
        ValueError: JSON 파싱 실패 또는 스키마 불일치.
    """
    try:
        return Trace.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"invalid trace file — {exc}") from exc
