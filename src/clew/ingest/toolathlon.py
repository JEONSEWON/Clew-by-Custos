"""src/clew/ingest/toolathlon.py — Toolathlon Trajectory JSONL → Trace.

매핑 규약: docs/TOOLATHLON.md §23 (사전등록, PR 승인 후 확정).

입력: `data/toolathlon/<model>_<run>.jsonl` (JSONL, 한 줄 = 한 트레이스).
출력: Clew 정규 Trace (synthetic CHAIN root + tool 스팬만).

주요 결정 (§23.2):
- 최상위 필드 값이 모두 JSON 문자열이라 재역직렬화 필요.
- per-message timestamp 없음 → synthetic: base + (msg_idx*1000 + sub_idx) 초.
- end_time = start_time (탐지기는 start_time 정렬만 사용).
- tool_calls[j].function.arguments 는 이미 JSON 문자열 → 재파싱 + sort_keys 재직렬화.

계약:
- ingest_toolathlon_jsonl(path) → Trace (첫 라인만; CC 와 계약 동일)
- iter_toolathlon_traces(path) → Iterator[Trace] (전량 스캔용)
"""
from __future__ import annotations

import json
import warnings
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from clew.model import Span, Trace

# synthetic timestamp 기준점. 절대값은 무의미 (탐지기는 정렬만 씀).
_TS_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _synth_ts(msg_idx: int, sub_idx: int) -> datetime:
    """§23.2: base + timedelta(seconds = msg_idx*1000 + sub_idx)."""
    return _TS_BASE + timedelta(seconds=msg_idx * 1000 + sub_idx)


def _load_str_field(entry: dict, key: str, expect_type: type) -> Any:
    """entry[key] 는 JSON 문자열이라고 README 가 명시 → loads. 실패 시 명시적 에러."""
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
    """§23.1: arguments (JSON 문자열) 재파싱 후 sort_keys 재직렬화.

    파싱 실패 시 조용히 원문 사용 금지 — 에러.
    단, 빈 문자열은 Toolathlon 관례상 "인자 없음" (recon Q2: playwright next_span 4세션).
    → 빈 문자열은 {} 로 정규화 (하드 에러 아님).
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
    """tool 메시지 content → 문자열.

    Toolathlon recon Q2 는 flat string 확인이지만 list-of-blocks 나오면 § 22.5 CC 규약 재사용.
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
    """한 JSONL 라인(=한 트레이스) 을 Trace 로."""
    # 순수 문자열 필드
    request_id = entry.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise ValueError(f"line {source_line}: request_id 필드 없음/비어있음")
    modelname_run = entry.get("modelname_run") or None
    task_name = entry.get("task_name") or None

    # JSON 문자열 필드 → 파싱
    messages = _load_str_field(entry, "messages", list)
    # task_status 는 metadata 로만 씀 — 필수는 아니지만 recon 상 항상 존재
    try:
        task_status = _load_str_field(entry, "task_status", dict)
    except ValueError:
        task_status = {}

    # 1차 스캔: tool_calls / tool_result 수집
    tool_uses: dict[str, tuple[dict, int, int]] = {}  # id → (fn_block, msg_idx, sub_idx)
    tool_results: dict[str, str] = {}  # tool_call_id → content_string
    seen_call_order: list[str] = []  # msg 순서 유지 (span_id 는 재사용 안 됨 가정)

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

    # 조인 검사 (§22.4 선례, §23.3)
    orphan_use = sorted(set(tool_uses) - set(tool_results))
    orphan_result = sorted(set(tool_results) - set(tool_uses))
    if orphan_use or orphan_result:
        raise ValueError(
            f"line {source_line}: 조인 실패 — orphan tool_call {len(orphan_use)}건 "
            f"(첫 5개: {orphan_use[:5]}), orphan tool_result {len(orphan_result)}건 "
            f"(첫 5개: {orphan_result[:5]})"
        )

    # Span 생성
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
    """첫 트레이스만 반환 (CC 와 계약 동일). 전량 스캔은 iter_toolathlon_traces."""
    for lineno, entry in _iter_raw_lines(path):
        with warnings.catch_warnings():
            warnings.simplefilter("default")
            return _build_trace_from_entry(entry, lineno)
    raise ValueError(f"{path}: 빈 JSONL 파일")


def iter_toolathlon_traces(path: Path) -> Iterator[Trace]:
    """파일 내 모든 트레이스를 yield.

    개별 트레이스 파싱 실패 시 조용히 skip 하지 않고 raise — 호출측이 결정한다.
    """
    for lineno, entry in _iter_raw_lines(path):
        yield _build_trace_from_entry(entry, lineno)
