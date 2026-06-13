"""src/clew/ingest/preprocess.py

인제스트 전처리 파이프라인 — otel_spans_to_trace() 후처리 단계.

세 가지 변환:
  1. extract_output_text  — JSON 상태딕 스캐폴드 제거
  2. mark_worker_span_ids — llm/tool 자손을 가진 span_id 집합 계산 (라우터 판별)
  3. collapse_llm_spans   — llm sub-span 제거 + token rollup + ReAct re-parent
  4. filter_router_spans  — 라우터 chain span 제거
"""

from __future__ import annotations

import json
from typing import Any

from clew.model import Span, Trace


# ── 1. JSON 추출 ────────────────────────────────────────────────────────────

def extract_output_text(raw: str) -> str:
    """JSON dict/list를 재귀 순회해 모든 문자열 leaf 중 가장 긴 것 반환.

    규칙:
    - json.loads 성공 → dict/list를 재귀 탐색 → str leaf 수집
      → 가장 긴 non-empty 문자열 반환 (동률이면 순회 첫 번째)
    - json.loads 실패 또는 str leaf 없으면 raw 원문 반환

    키 순서에 의존하지 않아 status 같은 짧은 필드를 오선택하지 않음.
    """
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw

    leaves: list[str] = []
    _collect_str_leaves(obj, leaves)
    non_empty = [s for s in leaves if s.strip()]
    if not non_empty:
        return raw
    return max(non_empty, key=len)


def _collect_str_leaves(obj: Any, out: list[str]) -> None:
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_str_leaves(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_str_leaves(item, out)


# ── 2. Worker span 집합 계산 ────────────────────────────────────────────────

def mark_worker_span_ids(spans: list[Span]) -> set[str]:
    """llm/tool 자손(transitive)을 가진 span_id 집합 반환.

    직계 자식이 아닌 자손 기준 — llm/tool 호출이 손자 깊이에 있는 chain 노드를
    라우터로 오인해 제거하는 것을 방지한다.
    """
    children_map: dict[str, list[str]] = {s.span_id: [] for s in spans}
    kinds: dict[str, str] = {s.span_id: s.span_kind for s in spans}
    for s in spans:
        if s.parent_span_id is not None and s.parent_span_id in children_map:
            children_map[s.parent_span_id].append(s.span_id)

    result: set[str] = set()
    for s in spans:
        if _has_llm_or_tool_descendant(s.span_id, children_map, kinds):
            result.add(s.span_id)
    return result


def _has_llm_or_tool_descendant(
    span_id: str,
    children_map: dict[str, list[str]],
    kinds: dict[str, str],
) -> bool:
    """span_id의 모든 자손 중 llm/tool이 하나라도 있으면 True (BFS)."""
    queue = list(children_map.get(span_id, []))
    while queue:
        child_id = queue.pop()
        if kinds.get(child_id) in ("llm", "tool"):
            return True
        queue.extend(children_map.get(child_id, []))
    return False


# ── 3. LLM span collapse + ReAct re-parent ──────────────────────────────────

def collapse_llm_spans(
    spans: list[Span],
    worker_ids: set[str],
) -> tuple[list[Span], int]:
    """llm sub-span 제거 + token_count/cost_rate를 부모 chain으로 rollup.

    ReAct 고아 처리:
        제거되는 llm span의 자식(tool 등)은 해당 llm의 parent_span_id로 re-parent.
        이렇게 하면 tool span이 worker chain 바로 아래로 올라와 댕글링이 없다.

    token_count rollup:
        제거된 llm span의 token_count를 부모 chain에 누적.
        부모에 이미 token_count가 있으면 합산, 없으면 설정.
    """
    llm_ids = {s.span_id for s in spans if s.span_kind == "llm"}

    # llm span별 (token_count, parent_span_id) 수집
    llm_info: dict[str, tuple[int | None, str | None]] = {
        s.span_id: (s.token_count, s.parent_span_id)
        for s in spans if s.span_kind == "llm"
    }

    # 부모별 token_count 누적
    parent_token_delta: dict[str, int] = {}
    for llm_id, (tc, parent_id) in llm_info.items():
        if parent_id is not None and tc is not None:
            parent_token_delta[parent_id] = parent_token_delta.get(parent_id, 0) + tc

    kept: list[Span] = []
    for s in spans:
        if s.span_kind == "llm":
            continue  # 제거

        # ReAct re-parent: 부모가 llm span이면 llm의 부모로 올림
        new_parent = s.parent_span_id
        if new_parent in llm_ids:
            new_parent = llm_info[new_parent][1]  # llm의 parent_span_id

        # token_count rollup
        new_token_count = s.token_count
        if s.span_id in parent_token_delta:
            base = s.token_count or 0
            new_token_count = base + parent_token_delta[s.span_id]

        if new_parent != s.parent_span_id or new_token_count != s.token_count:
            s = s.model_copy(update={
                "parent_span_id": new_parent,
                "token_count": new_token_count,
            })

        kept.append(s)

    return kept, len(llm_ids)


# ── 4. 라우터 span 필터 ─────────────────────────────────────────────────────

def filter_router_spans(spans: list[Span], worker_ids: set[str]) -> list[Span]:
    """worker_ids에 없는 non-root chain/agent span 제거.

    조건: span_kind in (chain, agent) AND parent_span_id is not None AND
          span_id not in worker_ids
    root span(parent_span_id=None)은 항상 보존.
    """
    return [
        s for s in spans
        if not (
            s.span_kind in ("chain", "agent")
            and s.parent_span_id is not None
            and s.span_id not in worker_ids
        )
    ]


# ── 파이프라인 진입점 ────────────────────────────────────────────────────────

def preprocess_trace(trace: Trace) -> Trace:
    """인제스트 전처리 4단계 파이프라인.

    ① extract_output_text  — 각 span의 output_text에서 JSON 스캐폴드 제거
    ② mark_worker_span_ids — collapse 전 원본 트리에서 worker 집합 계산
    ③ collapse_llm_spans   — llm 제거 + token rollup + ReAct re-parent
    ④ filter_router_spans  — 라우터 chain span 제거

    순서 보장: ②는 ③ 전(collapse 후 llm span 사라짐), ③은 ④ 전.
    """
    # ① JSON 추출 — Span.output_text 갱신
    spans: list[Span] = []
    for s in trace.spans:
        extracted = extract_output_text(s.output_text)
        if extracted != s.output_text:
            s = s.model_copy(update={"output_text": extracted})
        spans.append(s)

    # ② worker 집합 계산 (collapse 전 위상 기반)
    worker_ids = mark_worker_span_ids(spans)

    # ③ collapse
    spans, removed_count = collapse_llm_spans(spans, worker_ids)

    # ④ 라우터 필터
    spans = filter_router_spans(spans, worker_ids)

    new_meta = {
        **trace.metadata,
        "collapsed_llm_spans": removed_count,
        "filtered_router_spans": len(trace.spans) - removed_count - len(spans),
    }
    return Trace(trace_id=trace.trace_id, spans=spans, metadata=new_meta)
