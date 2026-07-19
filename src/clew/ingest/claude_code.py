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

    if not tool_uses:
        raise ValueError(f"{path}: tool_use 블록이 하나도 없음")

    # Join check (§22.4 abort condition 2)
    orphan_use = sorted(set(tool_uses) - set(tool_results))
    orphan_result = sorted(set(tool_results) - set(tool_uses))
    if orphan_use or orphan_result:
        raise ValueError(
            f"조인 실패 — orphan tool_use={len(orphan_use)}건 "
            f"(첫 5개: {orphan_use[:5]}), "
            f"orphan tool_result={len(orphan_result)}건 "
            f"(첫 5개: {orphan_result[:5]})"
        )

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

    # Synthetic CHAIN root (precedent at otel_json.py:278)
    root_start = min(s.start_time for s in tool_spans)
    root_end = max(s.end_time for s in tool_spans)
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

    return Trace(
        trace_id=session_id,
        spans=[root_span] + tool_spans,
        metadata={
            "source": "claude_code_jsonl",
            "path": str(path.name),
            "compact_boundaries": compact_boundaries,
        },
    )
