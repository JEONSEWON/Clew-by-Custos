"""field_test/collapse.py — LLM sub-span 접기 변환.

DEPRECATED: 이 모듈은 src/clew/ingest/preprocess.py 로 이전됐습니다.
field_test/ 하위 스크립트 backward-compat 목적으로만 유지.
새 코드: from clew.ingest.preprocess import collapse_llm_spans, filter_router_spans

field_test/ 전용 후처리. src/clew 은 read-only import 만.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from clew.model import Trace


def collapse_to_logical_nodes(trace: Trace) -> Trace:
    """LLM sub-span 제거 → 논리 노드 단위 Trace 반환.

    - span_kind == "llm"  → 제거 (부모 chain이 노드 출력 보유)
    - span_kind == "tool" → 유지 (requery 게이트 대상, 절대 접지 않음)
    - span_kind in ("chain", "agent") → 유지
    """
    removed_ids = {s.span_id for s in trace.spans if s.span_kind == "llm"}
    kept = [s for s in trace.spans if s.span_id not in removed_ids]

    for s in kept:
        if s.parent_span_id in removed_ids:
            raise ValueError(
                f"span {s.span_id!r} (kind={s.span_kind}) has removed llm parent "
                f"{s.parent_span_id!r} — collapse logic needs extension"
            )

    return Trace(
        trace_id=trace.trace_id,
        spans=kept,
        metadata={**trace.metadata, "collapsed_llm_spans": len(removed_ids)},
    )
