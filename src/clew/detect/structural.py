"""구조 후보 탐지 (SPEC §8 2.1).

start_time 시간순 노드 시퀀스에서:
- 반복 노드: 같은 agent_or_node_id가 N회+ 등장 → (첫 등장, 재등장) 쌍.
  단 span_kind=="tool"인 노드(조회/도구류)는 재등장의 input_text가 원본(첫 등장)과
  정규화-동일일 때만 후보로 박는다 — 입력이 다른 lookup은 서로 다른 정당한 조회.
- 핑퐁:    A→B→A→B → 2회차 A·B 쌍 (입력 게이트 미적용 — kind=="llm").
- requery: 반복 tool 노드의 특수형 → 입력 게이트가 그대로 작동.

라벨 미참조. 평가 set·dev set 어느 디렉터리도 읽지 않는다.
"""

from __future__ import annotations

from clew.model import Span, Trace


def _normalize_input(s: str) -> str:
    """SPEC §8 2.1 normalized-equal: 공백·대소문자만 정규화. 그 이상은 데이터 근거 없음."""
    return s.strip().casefold()


def _spans_by_start_time(trace: Trace) -> list[Span]:
    return sorted(trace.spans, key=lambda s: s.start_time)


def find_repeat_candidates(trace: Trace, n: int) -> list[tuple[Span, Span]]:
    """같은 agent_or_node_id가 n회+ 등장 시 (첫 등장, 재등장 각각) 쌍 반환.

    tool kind: 재등장 input_text 가 원본(첫 등장)과 정규화 동일일 때만 후보.
    그 외 kind: 입력 게이트 미적용.
    """
    if n < 2:
        raise ValueError("n must be >= 2 (a single occurrence is not a repeat)")
    ordered = _spans_by_start_time(trace)
    groups: dict[str, list[Span]] = {}
    for s in ordered:
        groups.setdefault(s.agent_or_node_id, []).append(s)
    pairs: list[tuple[Span, Span]] = []
    for occurrences in groups.values():
        if len(occurrences) < n:
            continue
        origin = occurrences[0]
        is_tool = origin.span_kind == "tool"
        for cand in occurrences[1:]:
            if is_tool and _normalize_input(cand.input_text) != _normalize_input(origin.input_text):
                continue
            pairs.append((origin, cand))
    return pairs


def find_pingpong_candidates(trace: Trace) -> list[tuple[Span, Span]]:
    """A→B→A→B 교대 발견 시 2회차 (A, A_prev) + (B, B_prev) 쌍 반환.

    핑퐁 노드는 kind=="llm" 이므로 입력 게이트 대상 아님(SPEC §8 2.1).
    """
    ordered = _spans_by_start_time(trace)
    pairs: list[tuple[Span, Span]] = []
    for i in range(len(ordered) - 3):
        a1, b1, a2, b2 = ordered[i], ordered[i + 1], ordered[i + 2], ordered[i + 3]
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
