"""src/clew/ingest/toolathlon.py - Toolathlon Trajectory JSONL -> Trace.

Mapping convention: docs/TOOLATHLON.md §23 (pre-registered, finalized after PR approval).

Input: `data/toolathlon/<model>_<run>.jsonl` (JSONL, one line = one trace).
Output: Clew canonical Trace (synthetic CHAIN root + tool spans only).

Main decisions (§23.2):
- All top-level field values are JSON strings, so re-deserialization is required.
- No per-message timestamp -> synthetic: base + (msg_idx*1000 + sub_idx) seconds.
- end_time = start_time (the detector uses start_time sort only).
- tool_calls[j].function.arguments is already a JSON string -> re-parse + sort_keys re-serialization.

Contract:
- ingest_toolathlon_jsonl(path) -> Trace (first line only; same contract as CC)
- iter_toolathlon_traces(path) -> Iterator[Trace] (for full scans)
"""
from __future__ import annotations

import json
import warnings
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from clew.model import Span, Trace

# synthetic timestamp reference point. Absolute value is meaningless (the detector only uses sort order).
_TS_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _synth_ts(msg_idx: int, sub_idx: int) -> datetime:
    """§23.2: base + timedelta(seconds = msg_idx*1000 + sub_idx)."""
    return _TS_BASE + timedelta(seconds=msg_idx * 1000 + sub_idx)


def _load_str_field(entry: dict, key: str, expect_type: type) -> Any:
    """README states entry[key] is a JSON string -> loads. Explicit error on failure."""
    v = entry.get(key)
    if v is None:
        raise ValueError(f"Toolathlon: 필수 필드 {key!r} 없음")
    if not isinstance(v, str):
        raise ValueError(f"Toolathlon: {key!r} 는 JSON 문자열이어야 함 (실제 {type(v).__name__})")
    try:
        parsed = json.loads(v)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Toolathlon: {key!r} JSON 파싱 실패 — {exc}") from exc
    if not isinstance(parsed, expect_type):
        raise ValueError(
            f"Toolathlon: {key!r} 파싱 결과 타입 {type(parsed).__name__}, 기대 {expect_type.__name__}"
        )
    return parsed


def _normalize_arguments(raw: Any) -> str:
    """§23.1: re-parse arguments (JSON string) then re-serialize with sort_keys.

    Silent use of raw text on parse failure is forbidden - error.
    However, an empty string is "no args" by Toolathlon convention (recon Q2: 4 playwright next_span sessions).
    -> Normalize empty string to {} (not a hard error).
    """
    if isinstance(raw, str):
        if raw == "":
            obj = {}
        else:
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Toolathlon: tool_calls.function.arguments JSON 파싱 실패 (원문 앞 80자: {raw[:80]!r}) — {exc}"
                ) from exc
    elif isinstance(raw, (dict, list)):
        obj = raw
    elif raw is None:
        obj = {}
    else:
        raise ValueError(
            f"Toolathlon: arguments 지원 타입 아님 ({type(raw).__name__})"
        )
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def _render_content(content: Any) -> str:
    """tool message content -> string.

    Toolathlon recon Q2 confirms flat string, but if list-of-blocks appears reuse the §22.5 CC convention.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for i, block in enumerate(content):
            if not isinstance(block, dict):
                warnings.warn(
                    f"Toolathlon: tool.content[{i}]: dict 아님 ({type(block).__name__}) — json.dumps",
                    stacklevel=3,
                )
                parts.append(json.dumps(block, sort_keys=True, ensure_ascii=False))
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append(block.get("text", ""))
            else:
                warnings.warn(
                    f"Toolathlon: tool.content[{i}]: 비-text 블록 {btype!r} — json.dumps",
                    stacklevel=3,
                )
                parts.append(json.dumps(block, sort_keys=True, ensure_ascii=False))
        return "\n".join(parts)
    raise ValueError(f"Toolathlon: content 지원 타입 아님 ({type(content).__name__})")


def _build_trace_from_entry(entry: dict, source_line: int) -> Trace:
    """Convert one JSONL line (= one trace) into a Trace."""
    # Plain string fields
    request_id = entry.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise ValueError(f"line {source_line}: request_id 필드 없음/비어있음")
    modelname_run = entry.get("modelname_run") or None
    task_name = entry.get("task_name") or None

    # JSON string fields -> parse
    messages = _load_str_field(entry, "messages", list)
    # task_status is used only for metadata - not mandatory but always present per recon
    try:
        task_status = _load_str_field(entry, "task_status", dict)
    except ValueError:
        task_status = {}

    # First pass: collect tool_calls / tool_result
    tool_uses: dict[str, tuple[dict, int, int]] = {}  # id -> (fn_block, msg_idx, sub_idx)
    tool_results: dict[str, str] = {}  # tool_call_id -> content_string
    seen_call_order: list[str] = []  # preserve msg order (assumes span_id is not reused)

    for msg_idx, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role == "assistant":
            tcs = msg.get("tool_calls")
            if not isinstance(tcs, list):
                continue
            for sub_idx, tc in enumerate(tcs):
                if not isinstance(tc, dict):
                    raise ValueError(
                        f"line {source_line} msg[{msg_idx}].tool_calls[{sub_idx}]: dict 아님"
                    )
                tid = tc.get("id")
                if not isinstance(tid, str) or not tid:
                    raise ValueError(
                        f"line {source_line} msg[{msg_idx}].tool_calls[{sub_idx}]: id 없음"
                    )
                if tid in tool_uses:
                    raise ValueError(
                        f"line {source_line}: 중복 tool_call id {tid!r}"
                    )
                fn = tc.get("function")
                if not isinstance(fn, dict):
                    raise ValueError(
                        f"line {source_line} msg[{msg_idx}].tool_calls[{sub_idx}]: function 없음"
                    )
                tool_uses[tid] = (fn, msg_idx, sub_idx)
                seen_call_order.append(tid)
        elif role == "tool":
            tid = msg.get("tool_call_id")
            if not isinstance(tid, str) or not tid:
                raise ValueError(
                    f"line {source_line} msg[{msg_idx}]: role='tool' 인데 tool_call_id 없음"
                )
            if tid in tool_results:
                raise ValueError(
                    f"line {source_line}: 중복 tool_result for {tid!r}"
                )
            tool_results[tid] = _render_content(msg.get("content"))

    if not tool_uses:
        raise ValueError(f"line {source_line}: tool_calls 하나도 없음 (request_id={request_id})")

    # Join check (§22.4 precedent, §23.3)
    orphan_use = sorted(set(tool_uses) - set(tool_results))
    orphan_result = sorted(set(tool_results) - set(tool_uses))
    if orphan_use or orphan_result:
        raise ValueError(
            f"line {source_line}: 조인 실패 — orphan tool_call {len(orphan_use)}건 "
            f"(첫 5개: {orphan_use[:5]}), orphan tool_result {len(orphan_result)}건 "
            f"(첫 5개: {orphan_result[:5]})"
        )

    # Create spans
    root_span_id = f"root-{request_id}"
    tool_spans: list[Span] = []
    for tid in seen_call_order:
        fn, msg_idx, sub_idx = tool_uses[tid]
        name = fn.get("name") or "anonymous"
        args_normalized = _normalize_arguments(fn.get("arguments"))
        output_text = tool_results[tid]
        ts = _synth_ts(msg_idx, sub_idx)
        tool_spans.append(
            Span(
                trace_id=request_id,
                span_id=tid,
                parent_span_id=root_span_id,
                agent_or_node_id=name,
                span_kind="tool",
                start_time=ts,
                end_time=ts,
                input_text=args_normalized,
                output_text=output_text,
                token_count=None,
                model=modelname_run,
                cost_rate=None,
            )
        )

    root_start = min(s.start_time for s in tool_spans)
    root_end = max(s.end_time for s in tool_spans)
    root_span = Span(
        trace_id=request_id,
        span_id=root_span_id,
        parent_span_id=None,
        agent_or_node_id="[toolathlon-trajectory-root]",
        span_kind="chain",
        start_time=root_start,
        end_time=root_end,
        input_text="",
        output_text=f"[toolathlon trajectory: {task_name or 'unknown'}]",
        model=modelname_run,
    )

    metadata: dict[str, Any] = {
        "source": "toolathlon_jsonl",
        "task_name": task_name,
        "task_status": task_status if isinstance(task_status, dict) else {},
        "modelname_run": modelname_run,
    }

    return Trace(
        trace_id=request_id,
        spans=[root_span] + tool_spans,
        metadata=metadata,
    )


def _iter_raw_lines(path: Path) -> Iterator[tuple[int, dict]]:
    with path.open(encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            s = raw.strip()
            if not s:
                continue
            try:
                yield lineno, json.loads(s)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: JSONL 라인 파싱 실패 ({exc})") from exc


def ingest_toolathlon_jsonl(path: Path) -> Trace:
    """Return only the first trace (same contract as CC). Use iter_toolathlon_traces for full scan."""
    for lineno, entry in _iter_raw_lines(path):
        with warnings.catch_warnings():
            warnings.simplefilter("default")
            return _build_trace_from_entry(entry, lineno)
    raise ValueError(f"{path}: 빈 JSONL 파일")


def iter_toolathlon_traces(path: Path) -> Iterator[Trace]:
    """Yield every trace in the file.

    Individual trace parse failures raise rather than silently skip - the caller decides.
    """
    for lineno, entry in _iter_raw_lines(path):
        yield _build_trace_from_entry(entry, lineno)
