"""Per-waste-pair enrichment (report-side; cascade/detect unchanged).

Extracts:
- file_path (or command) from candidate.input_text
- origin/candidate turn from trace.metadata["cc_turn_index"]
- pattern_label: "requery" when tool + input matches; else "repeat"
- modified_in_between: any Write/Edit-family span between origin and candidate
  targeting the same file_path (False when file_path unavailable — see uncertain flag)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from clew.model import Span, Trace
from clew.report._model import WasteDetail

_EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
_FILE_KEYS = ("file_path", "path", "filename", "notebook_path")


@dataclass
class EnrichedDetail:
    detail: WasteDetail
    file_path: str | None
    command: str | None
    origin_turn: int | None
    candidate_turn: int | None
    total_turns: int | None
    pattern_label: str
    modified_in_between: bool
    state_change_uncertain: bool  # True when file_path unavailable (e.g. Bash)
    input_summary: str  # fallback display when neither file_path nor command


@dataclass
class EnrichmentResult:
    """enrich(...) return: kept EnrichedDetails + count skipped due to tool-error gate."""
    enriched: list[EnrichedDetail]
    n_skipped_error: int


def _parse_input(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _file_path_of(obj: Any) -> str | None:
    if not isinstance(obj, dict):
        return None
    for k in _FILE_KEYS:
        v = obj.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def _command_of(obj: Any) -> str | None:
    if not isinstance(obj, dict):
        return None
    v = obj.get("command")
    return v if isinstance(v, str) and v else None


def _classify_pattern(origin: Span, cand: Span) -> str:
    if origin.span_kind == "tool" and cand.span_kind == "tool":
        if origin.input_text.strip().casefold() == cand.input_text.strip().casefold():
            return "requery"
    if origin.span_kind == "llm" and cand.span_kind == "llm":
        return "pingpong"
    return "repeat"


def _has_intervening_edit(trace: Trace, origin: Span, cand: Span, file_path: str) -> bool:
    for s in trace.spans:
        if s.span_kind != "tool":
            continue
        if s.agent_or_node_id not in _EDIT_TOOLS:
            continue
        if not (origin.start_time < s.start_time < cand.start_time):
            continue
        fp = _file_path_of(_parse_input(s.input_text))
        if fp == file_path:
            return True
    return False


def enrich(trace: Trace, details: list[WasteDetail]) -> EnrichmentResult:
    """Enrich WasteDetails; skip pairs whose origin or candidate is an error-response span.

    §29.2 tool-error gate: `trace.metadata["error_span_ids"]` (populated by the CC adapter
    from Anthropic `is_error: true` structural flag) marks tool_result spans that failed.
    Cosine similarity between two "File has not been read yet" outputs is not waste — it's
    tool infrastructure repeatedly emitting the same error. Skips are counted, not silent.
    """
    turn_index: dict[str, int] = trace.metadata.get("cc_turn_index") or {}
    total_turns: int | None = trace.metadata.get("cc_total_turns")
    error_ids: set[str] = set(trace.metadata.get("error_span_ids") or [])
    out: list[EnrichedDetail] = []
    n_skipped_error = 0
    for wd in details:
        o, c = wd.origin, wd.candidate
        if o.span_id in error_ids or c.span_id in error_ids:
            n_skipped_error += 1
            continue
        parsed = _parse_input(c.input_text)
        fp = _file_path_of(parsed)
        cmd = _command_of(parsed)
        pattern = _classify_pattern(o, c)
        modified = _has_intervening_edit(trace, o, c, fp) if fp else False
        uncertain = fp is None  # cannot verify state change without a file target
        summary = fp or cmd or (c.input_text[:60] + ("…" if len(c.input_text) > 60 else ""))
        out.append(EnrichedDetail(
            detail=wd,
            file_path=fp,
            command=cmd,
            origin_turn=turn_index.get(o.span_id),
            candidate_turn=turn_index.get(c.span_id),
            total_turns=total_turns if isinstance(total_turns, int) else None,
            pattern_label=pattern,
            modified_in_between=modified,
            state_change_uncertain=uncertain,
            input_summary=summary,
        ))
    return EnrichmentResult(enriched=out, n_skipped_error=n_skipped_error)
