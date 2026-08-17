"""src/clew/ingest/toolathlon.py - Toolathlon Trajectory JSONL -> Trace.

Mapping convention: docs/TOOLATHLON.md §23 (pre-registered, finalized after PR approval).

Input: `data/toolathlon/<model>_<run>.jsonl` (JSONL, one line = one trace).
Output: Boxdawn canonical Trace (synthetic CHAIN root + tool spans, plus
reconstructed `llm_calls` per WASTE_RATE_TOOLATHLON_ADAPTER_AMENDMENT_PREREG.md §1).

Main decisions (§23.2):
- All top-level field values are JSON strings, so re-deserialization is required.
- No per-message timestamp -> synthetic: base + (msg_idx*1000 + sub_idx) seconds.
- end_time = start_time (the detector uses start_time sort only).
- tool_calls[j].function.arguments is already a JSON string -> re-parse + sort_keys re-serialization.

LLM call reconstruction (amendment §1):
- One `llm_calls` entry per assistant message; `input_text` = JSON-serialized
  accumulated prior messages (matches CC adapter at claude_code.py:239).
- Trace-level `key_stats.input_tokens` apportioned length-weighted across calls;
  `output_tokens` split equally by `agent_llm_requests`; residual absorbed in last call.
- Cache tiers all uncached (Toolathlon `key_stats` does not distinguish).
- Cost rate looked up by `modelname_run` in the caller-provided table; missing model → None.

Contract:
- ingest_toolathlon_jsonl(path, *, input_cost_table, output_cost_table) -> Trace
- iter_toolathlon_traces(path, *, input_cost_table, output_cost_table) -> Iterator[Trace]
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


def _reconstruct_llm_calls(
    messages: list,
    key_stats: dict,
    modelname_run: str | None,
    input_cost_table: dict[str, float] | None,
    output_cost_table: dict[str, float] | None,
) -> list[dict[str, Any]]:
    """Amendment §1: reconstruct per-assistant LLM calls from Toolathlon trajectory.

    Returns [] when `key_stats` lacks `input_tokens` (>0) or
    `agent_llm_requests` (>0) - existing tests use empty key_stats and
    must continue to see no llm_calls populated.
    """
    try:
        t_in = int(key_stats.get("input_tokens", 0))
        t_out = int(key_stats.get("output_tokens", 0))
        n_req = int(key_stats.get("agent_llm_requests", 0))
    except (TypeError, ValueError):
        return []

    if t_in <= 0 or n_req <= 0:
        return []

    input_cost_rate: float | None = None
    output_cost_rate: float | None = None
    if input_cost_table and isinstance(modelname_run, str) and modelname_run in input_cost_table:
        input_cost_rate = float(input_cost_table[modelname_run])
    if output_cost_table and isinstance(modelname_run, str) and modelname_run in output_cost_table:
        output_cost_rate = float(output_cost_table[modelname_run])

    # Pass 1: iterate in trajectory order; snapshot accumulated context
    # BEFORE each assistant, then append the assistant to accumulated
    # (matches CC pattern at claude_code.py:239).
    accumulated: list[dict[str, Any]] = []
    call_snapshots: list[tuple[int, str]] = []  # (msg_idx, input_text_json)

    for msg_idx, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role == "assistant":
            input_text = json.dumps(accumulated, ensure_ascii=False, default=str)
            call_snapshots.append((msg_idx, input_text))
            asst_entry: dict[str, Any] = {"role": "assistant", "content": msg.get("content")}
            if "tool_calls" in msg:
                asst_entry["tool_calls"] = msg.get("tool_calls")
            accumulated.append(asst_entry)
        elif role == "user":
            accumulated.append({"role": "user", "content": msg.get("content")})
        elif role == "tool":
            tool_entry: dict[str, Any] = {"role": "tool", "content": msg.get("content")}
            if "tool_call_id" in msg:
                tool_entry["tool_call_id"] = msg.get("tool_call_id")
            accumulated.append(tool_entry)

    if not call_snapshots:
        return []

    # Pass 2: length-weighted apportionment (amendment §1.3).
    lengths = [len(it.encode("utf-8")) for (_, it) in call_snapshots]
    total_len = sum(lengths)
    n_calls = len(call_snapshots)

    if total_len > 0:
        raw_in = [t_in * L / total_len for L in lengths]
    else:
        raw_in = [t_in / n_calls] * n_calls

    input_tokens_list = [int(round(x)) for x in raw_in]
    input_tokens_list[-1] += t_in - sum(input_tokens_list)

    per_call_out = t_out // n_calls
    output_tokens_list = [per_call_out] * n_calls
    output_tokens_list[-1] += t_out - sum(output_tokens_list)

    llm_calls: list[dict[str, Any]] = []
    for k, ((msg_idx, input_text), it_i, ot_i) in enumerate(
        zip(call_snapshots, input_tokens_list, output_tokens_list, strict=True)
    ):
        llm_calls.append({
            "span_id": f"toolathlon-llm-{k:06d}",
            "input_text": input_text,
            "input_tokens": int(it_i),
            "output_tokens": int(ot_i),
            "input_tokens_uncached": int(it_i),
            "input_tokens_cache_read": 0,
            "input_tokens_cache_write": 0,
            "input_cost_rate": input_cost_rate,
            "output_cost_rate": output_cost_rate,
            "cost_rate_legacy": None,
            "model": modelname_run,
            "start_time": _synth_ts(msg_idx, 0).isoformat(),
        })
    return llm_calls


def _build_trace_from_entry(
    entry: dict,
    source_line: int,
    input_cost_table: dict[str, float] | None = None,
    output_cost_table: dict[str, float] | None = None,
) -> Trace:
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

    # Amendment §1: reconstruct llm_calls from assistant messages.
    try:
        key_stats_parsed = _load_str_field(entry, "key_stats", dict)
    except ValueError:
        key_stats_parsed = {}
    if not isinstance(key_stats_parsed, dict):
        key_stats_parsed = {}
    llm_calls = _reconstruct_llm_calls(
        messages,
        key_stats_parsed,
        modelname_run,
        input_cost_table,
        output_cost_table,
    )

    metadata: dict[str, Any] = {
        "source": "toolathlon_jsonl",
        "task_name": task_name,
        "task_status": task_status if isinstance(task_status, dict) else {},
        "modelname_run": modelname_run,
        "key_stats": key_stats_parsed,
        "llm_calls": llm_calls,
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


def ingest_toolathlon_jsonl(
    path: Path,
    *,
    input_cost_table: dict[str, float] | None = None,
    output_cost_table: dict[str, float] | None = None,
) -> Trace:
    """Return only the first trace (same contract as CC). Use iter_toolathlon_traces for full scan."""
    for lineno, entry in _iter_raw_lines(path):
        with warnings.catch_warnings():
            warnings.simplefilter("default")
            return _build_trace_from_entry(entry, lineno, input_cost_table, output_cost_table)
    raise ValueError(f"{path}: 빈 JSONL 파일")


def iter_toolathlon_traces(
    path: Path,
    *,
    input_cost_table: dict[str, float] | None = None,
    output_cost_table: dict[str, float] | None = None,
) -> Iterator[Trace]:
    """Yield every trace in the file.

    Individual trace parse failures raise rather than silently skip - the caller decides.
    """
    for lineno, entry in _iter_raw_lines(path):
        yield _build_trace_from_entry(entry, lineno, input_cost_table, output_cost_table)
