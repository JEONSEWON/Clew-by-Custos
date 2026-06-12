"""src/clew/report/_model.py — 리포트 내부 데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass

from clew.model import Span


@dataclass
class WasteDetail:
    """낭비 스팬 쌍 1건.

    origin   : 첫 등장 스팬 (정당한 1회 — 낭비 아님).
    candidate: 재등장 스팬 (낭비 — token_count/cost_rate 집계 대상).
    cosine   : 두 output_text 간 코사인 유사도.

    비용 계산 규칙: candidate 기준만 합산. origin은 정당한 첫 실행이므로 제외.
    """

    origin: Span
    candidate: Span
    cosine: float

    @property
    def waste_tokens(self) -> int | None:
        return self.candidate.token_count

    @property
    def waste_cost(self) -> float | None:
        tc = self.candidate.token_count
        cr = self.candidate.cost_rate
        if tc is None or cr is None:
            return None
        return tc * cr
