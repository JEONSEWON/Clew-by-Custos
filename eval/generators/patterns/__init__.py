"""4 낭비 패턴 등록자."""

from __future__ import annotations

from collections.abc import Callable

from .base import GeneratedTrace
from . import pingpong_aba, regen_handoff, repeat_node, requery_known

Generator = Callable[..., GeneratedTrace]

PATTERNS: dict[str, tuple[Generator, Generator]] = {
    "repeat_node": (repeat_node.make_positive, repeat_node.make_clean),
    "regen_handoff": (regen_handoff.make_positive, regen_handoff.make_clean),
    "pingpong_aba": (pingpong_aba.make_positive, pingpong_aba.make_clean),
    "requery_known": (requery_known.make_positive, requery_known.make_clean),
}

__all__ = ["PATTERNS", "GeneratedTrace"]
