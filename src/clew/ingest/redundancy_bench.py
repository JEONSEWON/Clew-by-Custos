"""src/clew/ingest/redundancy_bench.py — RedundancyBench final_traces.json → Trace.

매핑 규약: docs/REDUNDANCY_BENCH.md §24 (사전등록, PR 승인 후 확정).

입력: `data/redundancy_bench/data/domain/<domain>/final_traces.json`
     최상위 dict `{"tasks": [...], "simulations": [...]}`  (JSON, JSONL 아님)
출력: 각 simulation 을 하나의 Clew 정규 Trace 로.

핵심 결정 (§24.2):
- Span 은 `role=='assistant'` 의 tool_calls 만. `role=='user'` + tool_calls (telecom
  사용자 시뮬레이션, requestor='user') 는 span 제외.
- 조인 키는 `tool.id` (Toolathlon 의 `tool_call_id` 필드명과 다름 — RB 는 flat).
- `arguments` 는 이미 dict (Toolathlon 은 JSON 문자열, 여기는 dict) → sort_keys 재직렬화만.
- `Trace.metadata["rb_span_to_turn_pair"][span_id] = (call_idx, result_idx)` 로
  §24.3 규약 A (pair expansion) 실행 가능하게 보존.
- 병렬 tool_calls 없음 확인 (recon Q3b). sub_idx 필요 없음.

계약:
- ingest_redundancy_bench_json(path) → Trace (첫 simulation 만; CLI 호환)
- iter_redundancy_bench_traces(path) → Iterator[Trace] (전량 스캔용)
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
    """RB messages[i].timestamp — ISO datetime str. 실패 시 None (fallback synthetic)."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        # ISO 8601 지원 (Z 접미사 포함)
        s = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _synth_ts(turn_idx: int) -> datetime:
    """fallback synthetic timestamp — turn_idx 기반, 단조 증가."""
    return _TS_BASE + timedelta(seconds=turn_idx)


def _normalize_arguments(raw: Any) -> str:
    """§24.2: RB arguments 는 dict. sort_keys 재직렬화로 sha256 안정.

    - dict/list → 그대로 재직렬화.
    - str → JSON 파싱 후 재직렬화 (안전장치, 실제로는 dict 로 옴).
    - None → "{}" (빈 인자).
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
    """tool 메시지 content → 문자열. RB 는 flat str 확인."""
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
    """simulation 하나를 Trace 로. requestor='user' tool 은 제외 (§24.2)."""
    sim_id = sim.get("id")
    if not isinstance(sim_id, str) or not sim_id:
        raise ValueError(f"RedundancyBench: simulation.id 없음/비어있음 (task={sim.get('task_id')!r})")

    messages = sim.get("messages")
    if not isinstance(messages, list):
        raise ValueError(f"RedundancyBench sim={sim_id}: messages 리스트 아님")

    task_id = sim.get("task_id")

    # RB 는 같은 sim 내 tool_call.id 를 재사용 (같은 툴 재호출 시). recon 확정:
    #   airline 20/40, retail 22/48, telecom 45/112 sim 에서 재사용 발생.
    # → tid 단위 FIFO 로 call↔result 매칭. span_id = f"{tid}#{call_idx}" 로 unique.
    #
    # 데이터 구조:
    #   pending_calls_by_tid[tid] = deque([(tc_dict, call_turn_idx, occurrence_idx), ...])
    #     — 아직 매치 안된 assistant call (FIFO)
    #   matched_pairs = [(tc_dict, call_idx, result_idx, content, tid, occ), ...]
    #     — 조인 완료한 pair (스팬 생성 재료), 순서 = call_idx 순
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
                # §24.2 정책: user-발행 tool 은 span 제외.
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

    # 조인 검사 (§21.4). 아직 매치 안된 call / result 확인.
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

    # Span 생성. call_idx 순 (temporal). span_id = f"{tid}#{call_idx}" (unique).
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
    """경로에서 domain 이름 추정. data/domain/<name>/final_traces.json 관례."""
    parts = path.parts
    for name in ("airline", "retail", "telecom"):
        if name in parts:
            return name
    return None


def ingest_redundancy_bench_json(path: Path) -> Trace:
    """첫 simulation 만 반환 (CC/Toolathlon 계약 동일). 전량은 iter_ 를 써라."""
    obj = _load_top_level(path)
    sims = obj["simulations"]
    if not isinstance(sims, list) or not sims:
        raise ValueError(f"{path}: simulations 리스트 비어있음")
    domain = _infer_domain(path)
    return _build_trace_from_sim(sims[0], domain)


def iter_redundancy_bench_traces(path: Path) -> Iterator[Trace]:
    """파일 내 모든 simulation 을 yield.

    개별 sim 파싱 실패는 조용히 skip 하지 않고 raise — 호출측(스캔/평가) 이 결정한다.
    """
    obj = _load_top_level(path)
    sims = obj["simulations"]
    if not isinstance(sims, list):
        raise ValueError(f"{path}: simulations 필드 리스트 아님")
    domain = _infer_domain(path)
    for sim in sims:
        yield _build_trace_from_sim(sim, domain)
