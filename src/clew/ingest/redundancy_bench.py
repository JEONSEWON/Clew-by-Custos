"""src/clew/ingest/redundancy_bench.py - RedundancyBench final_traces.json -> Trace.

Mapping convention: docs/REDUNDANCY_BENCH.md §24 (pre-registered, finalized after PR approval).

Input: `data/redundancy_bench/data/domain/<domain>/final_traces.json`
     Top-level dict `{"tasks": [...], "simulations": [...]}`  (JSON, not JSONL)
Output: each simulation as a single Clew canonical Trace.

Key decisions (§24.2):
- Spans come from `role=='assistant'` tool_calls only. `role=='user'` + tool_calls
  (telecom user simulation, requestor='user') are excluded from spans.
- Join key is `tool.id` (differs from Toolathlon's `tool_call_id` field name - RB is flat).
- `arguments` is already a dict (Toolathlon uses JSON strings; here it's a dict) -> only sort_keys re-serialization.
- Preserved via `Trace.metadata["rb_span_to_turn_pair"][span_id] = (call_idx, result_idx)`
  so §24.3 convention A (pair expansion) is executable.
- Confirmed no parallel tool_calls (recon Q3b). sub_idx not needed.

Contract:
- ingest_redundancy_bench_json(path) -> Trace (first simulation only; CLI-compatible)
- iter_redundancy_bench_traces(path) -> Iterator[Trace] (for full scans)
"""
from __future__ import annotations

import json
import warnings
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from clew.model import Span, Trace

_TS_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _parse_timestamp(raw: Any) -> datetime | None:
    """RB messages[i].timestamp - ISO datetime str. None on failure (fallback synthetic)."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        # ISO 8601 support (including Z suffix)
        s = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _synth_ts(turn_idx: int) -> datetime:
    """fallback synthetic timestamp - turn_idx based, monotonically increasing."""
    return _TS_BASE + timedelta(seconds=turn_idx)


def _normalize_arguments(raw: Any) -> str:
    """§24.2: RB arguments is a dict. sort_keys re-serialization stabilizes sha256.

    - dict/list -> re-serialize as-is.
    - str -> JSON parse then re-serialize (safety net; actually comes as dict).
    - None -> "{}" (empty args).
    """
    if isinstance(raw, (dict, list)):
        obj = raw
    elif isinstance(raw, str):
        if raw == "":
            obj = {}
        else:
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"RedundancyBench: tool_calls.arguments JSON 파싱 실패 "
                    f"(원문 앞 80자: {raw[:80]!r}) — {exc}"
                ) from exc
    elif raw is None:
        obj = {}
    else:
        raise ValueError(
            f"RedundancyBench: arguments 지원 타입 아님 ({type(raw).__name__})"
        )
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def _render_content(content: Any) -> str:
    """tool message content -> string. RB confirmed to be flat str."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for i, block in enumerate(content):
            if not isinstance(block, dict):
                warnings.warn(
                    f"RedundancyBench: tool.content[{i}]: dict 아님 ({type(block).__name__}) — json.dumps",
                    stacklevel=3,
                )
                parts.append(json.dumps(block, sort_keys=True, ensure_ascii=False))
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append(block.get("text", ""))
            else:
                warnings.warn(
                    f"RedundancyBench: tool.content[{i}]: 비-text 블록 {btype!r} — json.dumps",
                    stacklevel=3,
                )
                parts.append(json.dumps(block, sort_keys=True, ensure_ascii=False))
        return "\n".join(parts)
    raise ValueError(f"RedundancyBench: content 지원 타입 아님 ({type(content).__name__})")


def _build_trace_from_sim(sim: dict, domain: str | None) -> Trace:
    """Convert one simulation into a Trace. Exclude requestor='user' tools (§24.2)."""
    sim_id = sim.get("id")
    if not isinstance(sim_id, str) or not sim_id:
        raise ValueError(f"RedundancyBench: simulation.id 없음/비어있음 (task={sim.get('task_id')!r})")

    messages = sim.get("messages")
    if not isinstance(messages, list):
        raise ValueError(f"RedundancyBench sim={sim_id}: messages 리스트 아님")

    task_id = sim.get("task_id")

    # RB reuses tool_call.id within the same sim (when the same tool is re-invoked). Recon confirms:
    #   reuse occurs in airline 20/40, retail 22/48, telecom 45/112 sims.
    # -> match call<->result via per-tid FIFO. span_id = f"{tid}#{call_idx}" for uniqueness.
    #
    # Data structures:
    #   pending_calls_by_tid[tid] = deque([(tc_dict, call_turn_idx, occurrence_idx), ...])
    #     - assistant calls not yet matched (FIFO)
    #   matched_pairs = [(tc_dict, call_idx, result_idx, content, tid, occ), ...]
    #     - joined pairs (span creation material), ordered by call_idx
    from collections import deque
    pending_calls_by_tid: dict[str, deque] = {}
    tid_occurrence_counter: dict[str, int] = {}
    matched_pairs: list[tuple[dict, int, int, str, str, int]] = []
    user_tool_idx: list[int] = []
    unmatched_results: list[tuple[str, int]] = []  # (tid, turn_idx)

    for turn_idx, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role == "assistant":
            tcs = msg.get("tool_calls")
            if not isinstance(tcs, list):
                continue
            for tc in tcs:
                if not isinstance(tc, dict):
                    raise ValueError(
                        f"RedundancyBench sim={sim_id} msg[{turn_idx}].tool_calls: dict 아닌 항목"
                    )
                tid = tc.get("id")
                if not isinstance(tid, str) or not tid:
                    raise ValueError(
                        f"RedundancyBench sim={sim_id} msg[{turn_idx}].tool_calls: id 없음"
                    )
                occ = tid_occurrence_counter.get(tid, 0)
                tid_occurrence_counter[tid] = occ + 1
                pending_calls_by_tid.setdefault(tid, deque()).append((tc, turn_idx, occ))
        elif role == "tool":
            requestor = msg.get("requestor")
            tid = msg.get("id")
            if not isinstance(tid, str) or not tid:
                raise ValueError(
                    f"RedundancyBench sim={sim_id} msg[{turn_idx}]: role='tool' 인데 id 없음"
                )
            if requestor == "user":
                # §24.2 policy: user-issued tools are excluded from spans.
                user_tool_idx.append(turn_idx)
                continue
            queue = pending_calls_by_tid.get(tid)
            if not queue:
                unmatched_results.append((tid, turn_idx))
                continue
            tc, call_idx, occ = queue.popleft()
            content = _render_content(msg.get("content"))
            matched_pairs.append((tc, call_idx, turn_idx, content, tid, occ))

    if not matched_pairs:
        raise ValueError(
            f"RedundancyBench sim={sim_id}: assistant 발행 tool_calls 하나도 없음"
        )

    # Join check (§21.4). Verify not-yet-matched calls / results.
    orphan_calls = [
        (tid, ci, occ)
        for tid, q in pending_calls_by_tid.items()
        for (_tc, ci, occ) in q
    ]
    if orphan_calls or unmatched_results:
        raise ValueError(
            f"RedundancyBench sim={sim_id}: 조인 실패 — orphan tool_call {len(orphan_calls)}건 "
            f"(첫 5개: {orphan_calls[:5]}), orphan tool_result {len(unmatched_results)}건 "
            f"(첫 5개: {unmatched_results[:5]})"
        )

    # Create spans. Ordered by call_idx (temporal). span_id = f"{tid}#{call_idx}" (unique).
    root_span_id = f"root-{sim_id}"
    tool_spans: list[Span] = []
    span_to_turn_pair: dict[str, list[int]] = {}

    matched_pairs.sort(key=lambda x: x[1])  # by call_idx

    for tc, call_idx, result_idx, content, tid, occ in matched_pairs:
        name = tc.get("name") or "anonymous"
        args_normalized = _normalize_arguments(tc.get("arguments"))
        span_id = f"{tid}#{call_idx}"

        asst_msg = messages[call_idx]
        ts = _parse_timestamp(asst_msg.get("timestamp")) if isinstance(asst_msg, dict) else None
        if ts is None:
            ts = _synth_ts(call_idx)

        tool_spans.append(
            Span(
                trace_id=sim_id,
                span_id=span_id,
                parent_span_id=root_span_id,
                agent_or_node_id=name,
                span_kind="tool",
                start_time=ts,
                end_time=ts,
                input_text=args_normalized,
                output_text=content,
                token_count=None,
                model=None,
                cost_rate=None,
            )
        )
        span_to_turn_pair[span_id] = [call_idx, result_idx]

    root_start = min(s.start_time for s in tool_spans)
    root_end = max(s.end_time for s in tool_spans)
    root_span = Span(
        trace_id=sim_id,
        span_id=root_span_id,
        parent_span_id=None,
        agent_or_node_id="[redundancy-bench-sim-root]",
        span_kind="chain",
        start_time=root_start,
        end_time=root_end,
        input_text="",
        output_text=f"[redundancy_bench sim: domain={domain} task={task_id}]",
        model=None,
    )

    metadata: dict[str, Any] = {
        "source": "redundancy_bench_json",
        "domain": domain,
        "task_id": task_id,
        "sim_id": sim_id,
        "reward_info": sim.get("reward_info"),
        "rb_span_to_turn_pair": span_to_turn_pair,
        "rb_user_tool_idx": user_tool_idx,
    }

    return Trace(
        trace_id=sim_id,
        spans=[root_span] + tool_spans,
        metadata=metadata,
    )


def _load_top_level(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: JSON 파싱 실패 ({exc})") from exc
    if not isinstance(obj, dict):
        raise ValueError(f"{path}: 최상위가 dict 아님 ({type(obj).__name__})")
    if "simulations" not in obj or "tasks" not in obj:
        raise ValueError(
            f"{path}: RedundancyBench 마커 없음 — 'tasks' 와 'simulations' 필요, "
            f"최상위 키: {list(obj.keys())[:8]}"
        )
    return obj


def _infer_domain(path: Path) -> str | None:
    """Infer domain name from path. Convention: data/domain/<name>/final_traces.json."""
    parts = path.parts
    for name in ("airline", "retail", "telecom"):
        if name in parts:
            return name
    return None


def ingest_redundancy_bench_json(path: Path) -> Trace:
    """Return the first simulation only (same contract as CC/Toolathlon). Use iter_ for the whole set."""
    obj = _load_top_level(path)
    sims = obj["simulations"]
    if not isinstance(sims, list) or not sims:
        raise ValueError(f"{path}: simulations 리스트 비어있음")
    domain = _infer_domain(path)
    return _build_trace_from_sim(sims[0], domain)


def iter_redundancy_bench_traces(path: Path) -> Iterator[Trace]:
    """Yield every simulation in the file.

    Individual sim parse failures raise rather than silently skip - the caller (scan/eval) decides.
    """
    obj = _load_top_level(path)
    sims = obj["simulations"]
    if not isinstance(sims, list):
        raise ValueError(f"{path}: simulations 필드 리스트 아님")
    domain = _infer_domain(path)
    for sim in sims:
        yield _build_trace_from_sim(sim, domain)
