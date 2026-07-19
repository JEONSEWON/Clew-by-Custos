"""src/clew/ingest/claude_code.py - Claude Code JSONL transcript -> Trace.

Mapping convention: docs/CC_TRANSCRIPT.md §22 (pre-registered, finalized after PR approval).

Input: `~/.claude/projects/<slug>/<uuid>.jsonl` (JSONL, one line = one JSON).
Output: Clew canonical Trace (synthetic CHAIN root + tool spans only).

v1 scope (§22.3):
  - Only `tool_use` <-> `tool_result` pairs are converted into spans.
  - thinking / assistant text / user text blocks do not produce spans.
"""
from __future__ import annotations

import json
import warnings
from datetime import datetime
from pathlib import Path

from clew.model import Span, Trace


def _load_jsonl(path: Path) -> list[dict]:
    """JSONL file -> list of dicts. Silent skip on parse failure is forbidden (§21.4)."""
    out: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            s = raw.strip()
            if not s:
                continue
            try:
                out.append(json.loads(s))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path}:{lineno}: JSONL 라인 파싱 실패 ({exc})"
                ) from exc
    if not out:
        raise ValueError(f"{path}: 빈 JSONL 파일")
    return out


def _parse_ts(ts: str) -> datetime:
    """ISO-8601 (Z suffix allowed) -> tz-aware datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _extract_result_text(content: object) -> str:
    """tool_result.content -> string (§22.5 convention).

    - str -> return as-is.
    - list -> render each block and join with '\n':
        * type=='text' -> block['text']
        * all other types -> json.dumps(block, sort_keys=True, ensure_ascii=False)
                            + warnings.warn (signal preservation, §21.4).
    - If empty after rendering, the Span validator raises (at the caller). Harmless here.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for i, block in enumerate(content):
            if not isinstance(block, dict):
                warnings.warn(
                    f"tool_result content[{i}]: dict 아님 ({type(block).__name__}) — "
                    f"json.dumps 로 직렬화 (§22.5)",
                    stacklevel=3,
                )
                parts.append(json.dumps(block, sort_keys=True, ensure_ascii=False))
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append(block.get("text", ""))
            else:
                warnings.warn(
                    f"tool_result content[{i}]: 비-text 블록 타입 {btype!r} — "
                    f"json.dumps 로 직렬화 (§22.5, 벤더 포맷 신호)",
                    stacklevel=3,
                )
                parts.append(json.dumps(block, sort_keys=True, ensure_ascii=False))
        return "\n".join(parts)
    raise ValueError(
        f"tool_result.content 지원 타입 아님: {type(content).__name__}"
    )


def _serialize_input(input_obj: object) -> str:
    """tool_use.input -> deterministic JSON string (§22.2 sort_keys)."""
    return json.dumps(input_obj, sort_keys=True, ensure_ascii=False)


def _collect_cc_usage_metadata(
    entries: list[dict],
) -> tuple[dict[str, int], dict[str, dict], int]:
    """Recon §21.2: per-tool_use turn index + prev/next assistant usage.

    Returns (cc_turn_index, cc_usage_pair, cc_total_turns).

    - cc_turn_index[span_id] = 1-based assistant turn number that issued the tool_use.
    - cc_usage_pair[span_id] = {"prev": host_assistant_usage_dict_or_None,
                                 "next": next_assistant_usage_dict_or_None}
    - cc_total_turns = total assistant entries (regardless of usage presence).

    Consumer contract: cost/amplification module reads these; adapter itself
    does not use them. Span construction unchanged.
    """
    assistant_positions: list[int] = [
        i for i, e in enumerate(entries) if e.get("type") == "assistant"
    ]
    total_turns = len(assistant_positions)

    cc_turn_index: dict[str, int] = {}
    cc_usage_pair: dict[str, dict] = {}

    for order, pos in enumerate(assistant_positions):
        turn_1based = order + 1
        entry = entries[pos]
        msg = entry.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue

        prev_usage = msg.get("usage")
        next_usage: dict | None = None
        if order + 1 < total_turns:
            nm = entries[assistant_positions[order + 1]].get("message")
            if isinstance(nm, dict):
                nu = nm.get("usage")
                if isinstance(nu, dict):
                    next_usage = nu

        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            tid = block.get("id")
            if not isinstance(tid, str) or not tid:
                continue
            cc_turn_index[tid] = turn_1based
            cc_usage_pair[tid] = {
                "prev": prev_usage if isinstance(prev_usage, dict) else None,
                "next": next_usage,
            }

    return cc_turn_index, cc_usage_pair, total_turns


def ingest_claude_code_jsonl(path: Path) -> Trace:
    """Claude Code JSONL transcript -> Trace (§22.1 mapping convention).

    Raises:
        ValueError: parse/join failure, empty output_text span, missing sessionId, etc.
    """
    entries = _load_jsonl(path)

    # Extract sessionId (assume all lines share the same sessionId)
    session_id: str | None = None
    for e in entries:
        sid = e.get("sessionId")
        if sid:
            session_id = sid
            break
    if session_id is None:
        raise ValueError(f"{path}: sessionId 필드가 없음 (Claude Code JSONL 아님?)")

    # Collect compact boundary timestamps (§22.11.2).
    # The two marker fields are exactly what classify_21_positives.py:_window_compact_flag actually looks at:
    #   - entry["compactMetadata"] is not None   (type=='system' line)
    #   - entry["isCompactSummary"] is True      (type=='user' line)
    # Both markers carry entry["timestamp"] (confirmed via 2026-07-18 real JSONL).
    compact_boundaries: list[datetime] = []
    for entry in entries:
        ts = entry.get("timestamp")
        if not ts:
            continue
        if entry.get("compactMetadata") is not None or entry.get("isCompactSummary") is True:
            compact_boundaries.append(_parse_ts(ts))

    # First pass: collect tool_use / tool_result
    tool_uses: dict[str, tuple[dict, str]] = {}
    tool_results: dict[str, tuple[dict, str]] = {}
    unknown_block_types: dict[str, int] = {}
    # §29.2 tool-error gate: Anthropic tool_result carries structural is_error=True
    # on tool crashes (e.g. "File has not been read yet"). Adapter collects tids only;
    # cascade/frozen path unchanged. Report/cost layers consume this list to skip
    # error-response spans from waste/amplification with explicit counts.
    error_span_ids: list[str] = []

    for entry in entries:
        etype = entry.get("type")
        msg = entry.get("message")
        ts = entry.get("timestamp")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        if not ts:
            continue

        if etype == "assistant":
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "tool_use":
                    tid = block.get("id")
                    if not tid:
                        raise ValueError(
                            f"tool_use 블록에 id 없음 (uuid={entry.get('uuid')})"
                        )
                    if tid in tool_uses:
                        raise ValueError(f"중복 tool_use.id: {tid!r}")
                    tool_uses[tid] = (block, ts)
                elif btype in ("thinking", "text"):
                    # §22.3: do not create a span
                    continue
                else:
                    unknown_block_types[str(btype)] = (
                        unknown_block_types.get(str(btype), 0) + 1
                    )

        elif etype == "user":
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "tool_result":
                    tid = block.get("tool_use_id")
                    if not tid:
                        raise ValueError(
                            f"tool_result 블록에 tool_use_id 없음 (uuid={entry.get('uuid')})"
                        )
                    if tid in tool_results:
                        raise ValueError(f"중복 tool_result for {tid!r}")
                    tool_results[tid] = (block, ts)
                    if block.get("is_error") is True:
                        error_span_ids.append(tid)
                elif btype == "text":
                    continue
                else:
                    unknown_block_types[str(btype)] = (
                        unknown_block_types.get(str(btype), 0) + 1
                    )

    if unknown_block_types:
        warnings.warn(
            f"{path.name}: 알 수 없는 assistant/user content 블록 타입 "
            f"{dict(unknown_block_types)} — 스팬 생성에서 제외",
            stacklevel=2,
        )

    # Join check (§22.4 abort condition 2 — amended by §29.1):
    #   orphan tool_result   → still raise (unknown-cause data corruption).
    #   orphan tool_use only → skip those tool_uses + warn (session-abort recovery).
    orphan_use = sorted(set(tool_uses) - set(tool_results))
    orphan_result = sorted(set(tool_results) - set(tool_uses))
    if orphan_result:
        raise ValueError(
            f"조인 실패 — orphan tool_use={len(orphan_use)}건 "
            f"(첫 5개: {orphan_use[:5]}), "
            f"orphan tool_result={len(orphan_result)}건 "
            f"(첫 5개: {orphan_result[:5]})"
        )
    if orphan_use:
        warnings.warn(
            f"{path.name}: orphan tool_use {len(orphan_use)}건 skip "
            f"(§29.1 session-abort recovery, 첫 5개: {orphan_use[:5]})",
            stacklevel=2,
        )
        for tid in orphan_use:
            tool_uses.pop(tid, None)

    # Create spans
    root_span_id = f"root-{session_id}"
    tool_spans: list[Span] = []
    for tid, (use_block, use_ts) in tool_uses.items():
        result_block, result_ts = tool_results[tid]
        input_text = _serialize_input(use_block.get("input", {}))
        output_text = _extract_result_text(result_block.get("content"))
        start = _parse_ts(use_ts)
        end = _parse_ts(result_ts)
        # Prevent end < start (clock inversion) - the Span validator catches this, but raises explicitly without clamping
        tool_spans.append(
            Span(
                trace_id=session_id,
                span_id=tid,
                parent_span_id=root_span_id,
                agent_or_node_id=use_block.get("name") or "anonymous",
                span_kind="tool",
                start_time=start,
                end_time=end,
                input_text=input_text,
                output_text=output_text,
                token_count=None,
                model=None,
                cost_rate=None,
            )
        )

    # Root timing: prefer tool_span range; else fall back to entry timestamps (§29.1 no-tool-use recovery).
    if tool_spans:
        root_start = min(s.start_time for s in tool_spans)
        root_end = max(s.end_time for s in tool_spans)
    else:
        warnings.warn(
            f"{path.name}: no tool spans (0 paired tool_use/tool_result) — "
            f"returning root-only Trace (§29.1 no-tool-use recovery)",
            stacklevel=2,
        )
        entry_ts = [_parse_ts(e["timestamp"]) for e in entries if e.get("timestamp")]
        if not entry_ts:
            raise ValueError(f"{path}: no timestamps found in entries")
        root_start = min(entry_ts)
        root_end = max(entry_ts)
    root_span = Span(
        trace_id=session_id,
        span_id=root_span_id,
        parent_span_id=None,
        agent_or_node_id="[claude-code-session-root]",
        span_kind="chain",
        start_time=root_start,
        end_time=root_end,
        input_text="",
        output_text="[claude-code session root]",
    )

    cc_turn_index, cc_usage_pair, cc_total_turns = _collect_cc_usage_metadata(entries)

    return Trace(
        trace_id=session_id,
        spans=[root_span] + tool_spans,
        metadata={
            "source": "claude_code_jsonl",
            "path": str(path.name),
            "compact_boundaries": compact_boundaries,
            "cc_turn_index": cc_turn_index,
            "cc_usage_pair": cc_usage_pair,
            "cc_total_turns": cc_total_turns,
            "error_span_ids": error_span_ids,
        },
    )
