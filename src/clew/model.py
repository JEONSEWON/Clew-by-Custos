"""Canonical span tree model - Boxdawn Stage 1 canonical data model.

Enforces every field and validation convention originally set out in
SPEC.md §8 1.1, with the `output_text` non-empty rule scoped in v0.4+ to
tool spans only (R2 relaxation — see the ADAPTER_R2_RELAXATION prereg
in this repo's docs/ for the rationale).

- Span: a single OTel/OpenInference-aligned span.
- Trace: list of spans bound under one trace_id (exactly one root, no cycles, no orphans).
- SpanNode: parent->children tree (result of Trace.build_tree()).

`output_text` is required for every span; on tool spans it must be
non-empty after strip (structural invariant: a tool call with no output
is invalid data). Non-tool spans (chain / agent / llm) may carry an
empty `output_text` — the cascade layer skips empty output in the
non-tool branch as an explicit judgment decision (absence is not an
expression, so cosine on absence is a malformed question).
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
    # Original tool response before extract_output_text mutation.
    # Populated only when preprocess_trace's (1) stage rewrote output_text
    # on a tool span. Consumers that need the untouched payload
    # (e.g. id_bridge entity_id extraction) read `raw_output_text or output_text`.
    # See openinference_output_text_fix_PREREG.md §2.1.
    raw_output_text: str | None = None
    # True when the adapter recognised this span's output as its vendor's
    # representation of "the tool produced no output" rather than content.
    # Set only by adapters (vendor strings belong there, not in a detector);
    # cascade's tool branch skips such spans, mirroring the non-tool branch's
    # empty-output skip. See CASCADE_ABSENCE_SENTINEL_AMENDMENT_PREREG.md
    # §4.2 option A. The `output_text` invariant below is unchanged: the
    # placeholder text is still carried, it is just not treated as content.
    output_is_absent: bool = False


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

    @model_validator(mode="after")
    def _output_text_non_empty_on_tool(self) -> Span:
        # Structural invariant (R2 relaxation, `docs/ADAPTER_R2_RELAXATION_PREREG.md`
        # §2.4-2.5): a tool call with no output is invalid data — cascade
        # sha256 gate would match empty-vs-empty as waste. Non-tool spans
        # (chain / agent / llm) are allowed to be empty; the cascade layer
        # skips empty output in the non-tool branch as an explicit judgment
        # decision (see cascade.py :: non-tool empty skip).
        if self.span_kind == "tool" and not self.output_text.strip():
            raise ValueError(
                "tool span output_text must be non-empty after strip. "
                "Structural invariant: a tool call with no output is invalid data"
            )
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
