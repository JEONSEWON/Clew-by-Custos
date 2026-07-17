"""구조 후보 탐지 (SPEC §8 2.1, §22.8).

start_time 시간순 노드 시퀀스에서:
- 반복 노드: 같은 agent_or_node_id 가 N회+ 등장 → 각 하위그룹 내 (첫 등장, 재등장) 쌍.
  span_kind=="tool" 인 노드는 `(agent_or_node_id, _normalize_input(input_text))` 로
  하위그룹핑 (§22.8.1: origin 고정 해제 — 동일 서명의 모든 재등장 페어링).
  그 외 kind 는 agent_or_node_id 만으로 그룹핑 (입력 게이트 미적용).
- 핑퐁: A→B→A→B → 2회차 A·B 쌍. 4-window 4개 스팬 전부 span_kind=="llm" 일 때만
  (§22.8.2: tool 호출 교대는 정상 작업이지 pingpong 이 아님).
- requery: 반복 tool 노드의 특수형 → 하위그룹핑이 그대로 작동.

라벨 미참조. 평가 set·dev set 어느 디렉터리도 읽지 않는다.
"""

from __future__ import annotations

from clew.model import Span, Trace


def _normalize_input(s: str) -> str:
    """SPEC §8 2.1 normalized-equal: 공백·대소문자만 정규화. 그 이상은 데이터 근거 없음."""
    return s.strip().casefold()


def _spans_by_start_time(trace: Trace) -> list[Span]:
    return sorted(trace.spans, key=lambda s: s.start_time)


def _nearest_agent_ancestor_id(
    start_id: str | None, spans_by_id: dict[str, Span]
) -> str | None:
    """parent_span_id 체인을 거슬러 span_kind=='agent'인 첫 조상의 span_id 반환.

    없으면 None (단일 에이전트/평면 트레이스). None==None → 게이트 미적용(기존 동작 보존).
    SPEC §16: 두 스팬의 반환값이 다르면 repeat 후보에서 제외.
    """
    current_id = start_id
    while current_id is not None:
        span = spans_by_id.get(current_id)
        if span is None:
            return None
        if span.span_kind == "agent":
            return span.span_id
        current_id = span.parent_span_id
    return None


def find_repeat_candidates(trace: Trace, n: int) -> list[tuple[Span, Span]]:
    """같은 agent_or_node_id 가 n회+ 등장 시 각 하위그룹 내 (첫 등장, 재등장) 쌍 반환.

    tool kind: `(agent_or_node_id, _normalize_input(input_text))` 로 하위그룹핑
        (§22.8.1: 같은 서명의 모든 재등장 페어링. dict 로 O(n)).
    그 외 kind: `agent_or_node_id` 만으로 그룹핑 (입력 게이트 미적용).
    SPEC §16 parent-AGENT gate: 두 스팬의 가장 가까운 조상 AGENT 가 다르면 후보 제외.
    """
    if n < 2:
        raise ValueError("n must be >= 2 (a single occurrence is not a repeat)")
    ordered = _spans_by_start_time(trace)
    spans_by_id = {s.span_id: s for s in trace.spans}
    groups: dict[tuple[str, str | None], list[Span]] = {}
    for s in ordered:
        if s.span_kind == "tool":
            key = (s.agent_or_node_id, _normalize_input(s.input_text))
        else:
            key = (s.agent_or_node_id, None)
        groups.setdefault(key, []).append(s)
    pairs: list[tuple[Span, Span]] = []
    for occurrences in groups.values():
        if len(occurrences) < n:
            continue
        origin = occurrences[0]
        origin_agent = _nearest_agent_ancestor_id(origin.parent_span_id, spans_by_id)
        for cand in occurrences[1:]:
            if _nearest_agent_ancestor_id(cand.parent_span_id, spans_by_id) != origin_agent:
                continue
            pairs.append((origin, cand))
    return pairs


def find_pingpong_candidates(trace: Trace) -> list[tuple[Span, Span]]:
    """A→B→A→B 교대 발견 시 2회차 (A, A_prev) + (B, B_prev) 쌍 반환.

    §22.8.2: 4-window 4개 스팬 전부 `span_kind == "llm"` 일 때만 후보.
    tool 호출 교대는 정상 작업이지 pingpong 이 아님.
    """
    ordered = _spans_by_start_time(trace)
    pairs: list[tuple[Span, Span]] = []
    for i in range(len(ordered) - 3):
        a1, b1, a2, b2 = ordered[i], ordered[i + 1], ordered[i + 2], ordered[i + 3]
        if not (
            a1.span_kind == "llm"
            and b1.span_kind == "llm"
            and a2.span_kind == "llm"
            and b2.span_kind == "llm"
        ):
            continue
        if (
            a1.agent_or_node_id == a2.agent_or_node_id
            and b1.agent_or_node_id == b2.agent_or_node_id
            and a1.agent_or_node_id != b1.agent_or_node_id
        ):
            pairs.append((a1, a2))
            pairs.append((b1, b2))
    return pairs


def find_candidates(trace: Trace, n: int) -> list[tuple[Span, Span]]:
    """반복 + 핑퐁 후보를 합쳐 (origin, candidate) 쌍 리스트 반환. 중복 제거."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[Span, Span]] = []
    for origin, cand in find_repeat_candidates(trace, n) + find_pingpong_candidates(trace):
        key = (origin.span_id, cand.span_id)
        if key in seen:
            continue
        seen.add(key)
        out.append((origin, cand))
    return out
