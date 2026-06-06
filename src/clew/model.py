"""Canonical span tree model — Clew 1단계 정규 데이터 모델.

SPEC.md §8 1.1 의 모든 필드 + 검증 규약을 강제한다.

- Span: 단일 OTel/OpenInference 정렬 스팬.
- Trace: trace_id 하나에 묶인 스팬 리스트(루트 정확히 1개, 사이클 없음, 고아 없음).
- SpanNode: parent->children 트리 (Trace.build_tree() 결과).

output_text는 필수 + non-empty (strip 후 길이>0). 2단계 의미 비교의 입력.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SpanKind = Literal["llm", "tool", "chain", "agent"]


class Span(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    span_id: str
    parent_span_id: str | None
    agent_or_node_id: str
    span_kind: SpanKind
    start_time: datetime
    end_time: datetime
    input_text: str
    output_text: str
    token_count: int | None = None
    model: str | None = None
    cost_rate: float | None = None

    @field_validator("output_text")
    @classmethod
    def _output_text_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("output_text must be non-empty after strip (★ SPEC §8 1.1)")
        return v

    @field_validator("start_time", "end_time")
    @classmethod
    def _tz_aware_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("datetime must be timezone-aware (use UTC)")
        return v

    @field_validator("token_count")
    @classmethod
    def _token_count_nonneg(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("token_count must be >= 0")
        return v

    @field_validator("cost_rate")
    @classmethod
    def _cost_rate_nonneg(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError("cost_rate must be >= 0")
        return v

    @model_validator(mode="after")
    def _end_after_start(self) -> Span:
        if self.end_time < self.start_time:
            raise ValueError("end_time must be >= start_time")
        return self


class SpanNode(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    span: Span
    children: list[SpanNode] = Field(default_factory=list)


SpanNode.model_rebuild()


class Trace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    spans: list[Span]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_tree(self) -> Trace:
        if not self.spans:
            raise ValueError("trace must contain at least one span (the root)")

        ids: set[str] = set()
        for s in self.spans:
            if s.trace_id != self.trace_id:
                raise ValueError(
                    f"span.trace_id={s.trace_id!r} does not match trace.trace_id={self.trace_id!r}"
                )
            if s.span_id in ids:
                raise ValueError(f"duplicate span_id: {s.span_id!r}")
            ids.add(s.span_id)

        roots = [s for s in self.spans if s.parent_span_id is None]
        if len(roots) != 1:
            raise ValueError(
                f"trace must have exactly one root span (parent_span_id=None); found {len(roots)}"
            )

        for s in self.spans:
            if s.parent_span_id is not None and s.parent_span_id not in ids:
                raise ValueError(
                    f"orphan span {s.span_id!r}: parent_span_id={s.parent_span_id!r} not found"
                )

        parent_of = {s.span_id: s.parent_span_id for s in self.spans}
        for start in ids:
            seen: set[str] = set()
            cur: str | None = start
            while cur is not None:
                if cur in seen:
                    raise ValueError(f"cycle detected in parent chain at span {cur!r}")
                seen.add(cur)
                cur = parent_of.get(cur)

        return self

    def build_tree(self) -> SpanNode:
        by_id = {s.span_id: s for s in self.spans}
        children_of: dict[str, list[Span]] = {sid: [] for sid in by_id}
        root: Span | None = None
        for s in self.spans:
            if s.parent_span_id is None:
                root = s
            else:
                children_of[s.parent_span_id].append(s)

        assert root is not None

        for sid in children_of:
            children_of[sid].sort(key=lambda x: x.start_time)

        def build(span: Span) -> SpanNode:
            return SpanNode(
                span=span,
                children=[build(c) for c in children_of[span.span_id]],
            )

        return build(root)
