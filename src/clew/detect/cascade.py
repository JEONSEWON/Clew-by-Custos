"""캐스케이드 결합 + 낭비 비용 (SPEC §8 2.3).

낭비 판정 = 구조 후보 AND 의미 중복(cos ≥ φ).
낭비 스팬 = candidate 측 (origin은 첫 등장이므로 정상으로 본다).
비용 = sum(token_count × cost_rate) over candidate 스팬.

라벨 인자 없음. evaluate.py 만이 결과를 라벨과 비교한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from clew.detect.semantic import Embedder, cosine
from clew.detect.structural import find_candidates
from clew.model import Trace


@dataclass
class CascadeResult:
    trace_id: str
    wasteful: bool
    waste_span_ids: list[str] = field(default_factory=list)
    waste_tokens: int = 0
    waste_cost: float = 0.0


def cascade(trace: Trace, embedder: Embedder, n: int, phi: float) -> CascadeResult:
    spans_by_id = {s.span_id: s for s in trace.spans}
    waste_span_ids: list[str] = []
    seen_candidates: set[str] = set()

    for origin, candidate in find_candidates(trace, n):
        if candidate.span_id in seen_candidates:
            continue
        if cosine(embedder.embed(origin.output_text), embedder.embed(candidate.output_text)) >= phi:
            waste_span_ids.append(candidate.span_id)
            seen_candidates.add(candidate.span_id)

    waste_tokens = 0
    waste_cost = 0.0
    for sid in waste_span_ids:
        s = spans_by_id[sid]
        tc = s.token_count or 0
        cr = s.cost_rate or 0.0
        waste_tokens += tc
        waste_cost += tc * cr

    return CascadeResult(
        trace_id=trace.trace_id,
        wasteful=bool(waste_span_ids),
        waste_span_ids=waste_span_ids,
        waste_tokens=waste_tokens,
        waste_cost=waste_cost,
    )
