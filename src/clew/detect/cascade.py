"""캐스케이드 결합 + 낭비 비용 (SPEC §8 2.3, §22.10.2, §22.11.2).

낭비 판정:
- span_kind == "tool"   → 구조 후보 AND (창문 안 compact 경계 없음)
                          AND sha256(origin.output) == sha256(cand.output).
                          φ 를 호출하지 않는다. 도구 출력은 패러프레이즈 없음.
- span_kind != "tool"   → 구조 후보 AND cos(origin, cand) ≥ φ (기존 경로).

compact 창문 게이트 (§22.11.2):
- Trace.metadata["compact_boundaries"] 에 timestamp 리스트가 있으면
  origin.start_time < b < candidate.start_time 인 b 가 존재할 때 waste 에서 제외.
- 이 키가 없으면 (OTel/OpenInference 등 non-CC 로더) 게이트 no-op.

낭비 스팬 = candidate 측 (origin은 첫 등장이므로 정상으로 본다).
비용 = sum(token_count × cost_rate) over candidate 스팬.

라벨 인자 없음. evaluate.py 만이 결과를 라벨과 비교한다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime

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


def _sha256_bytes(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _has_compact_between(boundaries: list[datetime], o_start: datetime, c_start: datetime) -> bool:
    return any(o_start < b < c_start for b in boundaries)


def cascade(trace: Trace, embedder: Embedder, n: int, phi: float) -> CascadeResult:
    spans_by_id = {s.span_id: s for s in trace.spans}
    waste_span_ids: list[str] = []
    seen_candidates: set[str] = set()
    compact_boundaries: list[datetime] = list(
        trace.metadata.get("compact_boundaries", []) or []
    )

    for origin, candidate in find_candidates(trace, n):
        if candidate.span_id in seen_candidates:
            continue
        if candidate.span_kind == "tool":
            if _has_compact_between(compact_boundaries, origin.start_time, candidate.start_time):
                continue
            if _sha256_bytes(origin.output_text) == _sha256_bytes(candidate.output_text):
                waste_span_ids.append(candidate.span_id)
                seen_candidates.add(candidate.span_id)
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
