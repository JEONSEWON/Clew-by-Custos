"""src/clew/report/_model.py - report-internal data model."""

from __future__ import annotations

from dataclasses import dataclass

from clew.model import Span


@dataclass
class WasteDetail:
    """A single waste span pair.

    origin   : first-occurrence span (a legitimate single run - not waste).
    candidate: re-occurrence span (waste - target of token_count/cost_rate aggregation).
    cosine   : cosine similarity between the two output_texts.

    Cost calculation rule: sum only on the candidate side. Origin is excluded as a legitimate first execution.
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
