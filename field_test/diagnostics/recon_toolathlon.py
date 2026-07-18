"""field_test/diagnostics/recon_toolathlon.py

Step 0 리콘 — Toolathlon-Trajectories 스키마 확인 (진단, 커밋 금지).

규율:
- 어댑터 코드 아님. 리콘만.
- 데이터 파일 자체 커밋 금지 (.gitignore data/).
- raw. 결론 금지.

대상: data/toolathlon/claude-4.5-sonnet-0929_1.jsonl (파일 1개)

Usage:
    python field_test/diagnostics/recon_toolathlon.py
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter
from pathlib import Path

DATA = Path("data/toolathlon/claude-4.5-sonnet-0929_1.jsonl")


def _load_all():
    out = []
    with DATA.open(encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            out.append(json.loads(s))
    return out


def _deser(d: dict) -> dict:
    """README 경고: 값이 전부 JSON 문자열. 필요한 필드만 loads."""
    out = dict(d)
    for k in ("config", "tool_calls", "messages", "key_stats", "agent_cost", "task_status"):
        v = out.get(k)
        if isinstance(v, str):
            try:
                out[k] = json.loads(v)
            except Exception:
                pass  # 못 파싱하면 원본 유지 (task_status 는 dict 가 아닐 수도)
    return out


def _head(s: str, n: int = 80) -> str:
    if not isinstance(s, str):
        s = str(s)
    s = s.replace("\n", " ").replace("\r", " ")
    return s if len(s) <= n else s[:n] + "..."


def q1(traces):
    print("=" * 100)
    print("Q1 파일 규모 + 최상위 스키마")
    print("=" * 100)
    sz = os.path.getsize(DATA)
    print(f"  file          : {DATA}")
    print(f"  bytes         : {sz:,}")
    print(f"  lines(traces) : {len(traces)}")

    first = traces[0]
    print(f"  첫 트레이스 최상위 키 ({len(first)}):")
    for k, v in first.items():
        t = type(v).__name__
        length = len(v) if hasattr(v, "__len__") else "-"
        print(f"    - {k:<18} type={t:<6} len={length}")

    # 역직렬화 필요 필드 확인
    print("\n  [역직렬화 필요 (str → 파싱 성공하는 필드)]")
    for k, v in first.items():
        if not isinstance(v, str):
            continue
        try:
            parsed = json.loads(v)
            ptype = type(parsed).__name__
            plen = len(parsed) if hasattr(parsed, "__len__") else "-"
            print(f"    - {k:<18} → json.loads OK  parsed_type={ptype}  parsed_len={plen}")
        except json.JSONDecodeError:
            print(f"    - {k:<18} → 그냥 문자열 (JSON 아님)")


def q2(first_deser):
    print()
    print("=" * 100)
    print("Q2 messages 구조 (첫 트레이스)")
    print("=" * 100)
    msgs = first_deser.get("messages")
    if not isinstance(msgs, list):
        print(f"  messages 파싱 결과 리스트 아님: type={type(msgs).__name__}")
        return
    print(f"  messages 길이 : {len(msgs)}")

    # 각 원소 키 (union)
    key_union = Counter()
    role_counts = Counter()
    for m in msgs:
        if not isinstance(m, dict):
            continue
        for k in m.keys():
            key_union[k] += 1
        r = m.get("role")
        role_counts[str(r)] += 1
    print(f"  key 등장 (원소 중 몇 개에):")
    for k, c in key_union.most_common():
        print(f"    - {k:<25} {c}")
    print(f"  role value_counts:")
    for r, c in role_counts.most_common():
        print(f"    - role={r!r:<15} {c}")

    # tool_calls / tool_result 표현 확인
    print(f"\n  [tool 호출 표현 흔적]")
    has_tool_calls_field = sum(1 for m in msgs if isinstance(m, dict) and m.get("tool_calls") is not None)
    has_tool_role = sum(1 for m in msgs if isinstance(m, dict) and m.get("role") == "tool")
    has_tool_call_id = sum(1 for m in msgs if isinstance(m, dict) and m.get("tool_call_id") is not None)
    # content 안에 tool_use / tool_result 블록이 있는지 (Anthropic 스타일)
    anthropic_blocks = Counter()
    for m in msgs:
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict):
                    anthropic_blocks[str(b.get("type"))] += 1
    print(f"    messages 중 assistant.tool_calls 존재 : {has_tool_calls_field}")
    print(f"    messages 중 role=='tool'             : {has_tool_role}")
    print(f"    messages 중 tool_call_id 존재         : {has_tool_call_id}")
    print(f"    content list 안 블록 type 카운트     : {dict(anthropic_blocks) or '(list content 없음)'}")

    # 첫 3개 메시지 키만
    print(f"\n  [첫 3 메시지 — 키만, content 앞 80자]")
    for i, m in enumerate(msgs[:3]):
        if not isinstance(m, dict):
            print(f"    #{i} type={type(m).__name__}")
            continue
        print(f"    #{i} keys={list(m.keys())}")
        for k, v in m.items():
            t = type(v).__name__
            if isinstance(v, str):
                print(f"       {k}: str len={len(v)} head80={_head(v)!r}")
            elif isinstance(v, list):
                print(f"       {k}: list len={len(v)}")
                for j, e in enumerate(v[:2]):
                    if isinstance(e, dict):
                        print(f"          [{j}] dict keys={list(e.keys())}")
                    else:
                        print(f"          [{j}] {type(e).__name__} {_head(str(e))!r}")
            elif isinstance(v, dict):
                print(f"       {k}: dict keys={list(v.keys())}")
            else:
                print(f"       {k}: {t} value={v!r}")


def q3(first_deser):
    print()
    print("=" * 100)
    print("Q3 호출↔결과 조인 (첫 트레이스)")
    print("=" * 100)
    msgs = first_deser.get("messages")
    if not isinstance(msgs, list):
        print("  messages 없음")
        return

    # tool_call_id 사용 패턴 조사
    call_ids_in_assistant = []  # (msg_idx, id)
    call_ids_in_tool = []       # (msg_idx, id)
    parallel_calls_per_msg = []  # assistant 한 메시지에 몇 개
    for i, m in enumerate(msgs):
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        # OpenAI 스타일: assistant.tool_calls 리스트, 각 원소에 id
        tc = m.get("tool_calls")
        if isinstance(tc, list) and tc:
            parallel_calls_per_msg.append((i, len(tc)))
            for c in tc:
                if isinstance(c, dict):
                    call_ids_in_assistant.append((i, c.get("id"), c.get("type")))
        # OpenAI 스타일: role=='tool' 메시지의 tool_call_id
        if role == "tool":
            call_ids_in_tool.append((i, m.get("tool_call_id")))
        # Anthropic 스타일: content list 안 tool_use / tool_result
        content = m.get("content")
        if isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                btype = b.get("type")
                if btype == "tool_use":
                    call_ids_in_assistant.append((i, b.get("id"), "anthropic_tool_use"))
                elif btype == "tool_result":
                    call_ids_in_tool.append((i, b.get("tool_use_id")))

    print(f"  총 호출 id (assistant 측)  : {len(call_ids_in_assistant)}")
    print(f"  총 결과 id (tool 측)       : {len(call_ids_in_tool)}")

    # 병렬 호출 여부
    print(f"  한 assistant 메시지에 병렬 tool_calls 수 분포:")
    par_counts = Counter(n for _, n in parallel_calls_per_msg)
    for n, c in sorted(par_counts.items()):
        print(f"    calls_per_msg={n}: 메시지 {c}개")
    print(f"  병렬 호출 있는 메시지 수 (>1): {sum(1 for _, n in parallel_calls_per_msg if n > 1)}")

    # 조인 검사
    call_id_set = {cid for _, cid, _ in call_ids_in_assistant if cid}
    res_id_set = {rid for _, rid in call_ids_in_tool if rid}
    matched = call_id_set & res_id_set
    orphan_call = call_id_set - res_id_set
    orphan_res = res_id_set - call_id_set
    print(f"\n  [id 조인]")
    print(f"    assistant 호출 id 유니크 : {len(call_id_set)}")
    print(f"    tool 결과 id 유니크      : {len(res_id_set)}")
    print(f"    양쪽 매칭               : {len(matched)}")
    print(f"    orphan (호출만)          : {len(orphan_call)}")
    print(f"    orphan (결과만)          : {len(orphan_res)}")

    # 결과 메시지 위치 (호출 바로 다음? 같은 메시지?)
    print(f"\n  [결과 메시지 위치 패턴 — 첫 5쌍]")
    call_by_id = {cid: i for i, cid, _ in call_ids_in_assistant if cid}
    for i, rid in call_ids_in_tool[:5]:
        ci = call_by_id.get(rid)
        gap = (i - ci) if ci is not None else None
        print(f"    result_msg_idx={i}  tool_call_id={rid}  call_msg_idx={ci}  gap={gap}")


def q4(first_deser):
    print()
    print("=" * 100)
    print("Q4 최상위 tool_calls (available tools 목록 vs 실제 호출)")
    print("=" * 100)
    tc_top = first_deser.get("tool_calls")
    print(f"  최상위 tool_calls type : {type(tc_top).__name__}")
    if isinstance(tc_top, list):
        print(f"  최상위 tool_calls len  : {len(tc_top)}")
        # 실제 호출은 messages 안에 assistant.tool_calls 안 or content.tool_use
        msgs = first_deser.get("messages") or []
        inline_calls = 0
        for m in msgs:
            if not isinstance(m, dict):
                continue
            if isinstance(m.get("tool_calls"), list):
                inline_calls += len(m["tool_calls"])
            content = m.get("content")
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        inline_calls += 1
        print(f"  messages 내 실제 호출 수: {inline_calls}")
        print(f"\n  [최상위 tool_calls 첫 3원소 키/이름]")
        for i, t in enumerate(tc_top[:3]):
            if isinstance(t, dict):
                nm = t.get("function", {}).get("name") if isinstance(t.get("function"), dict) else t.get("name")
                print(f"    #{i} keys={list(t.keys())} name={nm!r}")
            else:
                print(f"    #{i} {type(t).__name__} {_head(str(t))!r}")
    elif isinstance(tc_top, dict):
        print(f"  최상위 tool_calls keys : {list(tc_top.keys())[:20]}")


def q5(first_deser):
    print()
    print("=" * 100)
    print("Q5 Span 매핑 가능성")
    print("=" * 100)
    from clew.model import Span
    print("  Span 필수 필드 (clew.model.Span):")
    for name, field in Span.model_fields.items():
        req = " required" if field.is_required() else " optional"
        print(f"    - {name:<22} {str(field.annotation):<40}{req}")

    print("\n  [Toolathlon → Span 매핑 후보]")
    print(f"    trace_id        : request_id ({first_deser.get('request_id')})")
    print(f"    span_id         : (tool call id) — id 필드에서")
    print(f"    parent_span_id  : synthetic root or None")
    print(f"    agent_or_node_id: tool.function.name")
    print(f"    span_kind       : 'tool'")
    print(f"    input_text      : tool_call.arguments (JSON dump)")
    print(f"    output_text     : tool result content")

    # 시간 필드 흔적
    msgs = first_deser.get("messages") or []
    ts_keys = Counter()
    for m in msgs:
        if not isinstance(m, dict):
            continue
        for k in m.keys():
            if "time" in k.lower() or "timestamp" in k.lower() or "created" in k.lower():
                ts_keys[k] += 1
    print(f"\n  [messages 안 시간 관련 키 흔적]  {dict(ts_keys) or '(없음)'}")
    print(f"  최상위 initial_run_time : {first_deser.get('initial_run_time')!r}")
    print(f"  최상위 completion_time  : {first_deser.get('completion_time')!r}")

    # token / key_stats
    ks = first_deser.get("key_stats")
    print(f"\n  key_stats type          : {type(ks).__name__}")
    if isinstance(ks, dict):
        print(f"  key_stats keys          : {list(ks.keys())}")
        print(f"  key_stats 전문          : {json.dumps(ks, ensure_ascii=False)[:300]}")

    # 채울 수 없는 필드
    print(f"\n  [채울 수 없을 가능성 필드]")
    print(f"    - start_time / end_time per span (메시지 단위 timestamp 없으면)")
    print(f"    - token_count per span (key_stats 는 트레이스 총합일 가능성)")
    print(f"    - cost_rate / model (트레이스 단위는 있지만 span 단위는 미상)")


def q6(first_deser):
    print()
    print("=" * 100)
    print("Q6 낭비 실재 여부 (눈으로만, 카운트 금지)")
    print("=" * 100)
    task_status = first_deser.get("task_status")
    print(f"  task_status type        : {type(task_status).__name__}")
    if isinstance(task_status, dict):
        print(f"  task_status keys        : {list(task_status.keys())}")
        for k, v in task_status.items():
            print(f"    {k}: {_head(str(v), 120)!r}")
    else:
        print(f"  task_status raw         : {_head(str(task_status), 200)!r}")

    # 같은 tool + 같은 인자 반복 흔적 (진짜 카운트 안 하고 "존재 여부"만)
    msgs = first_deser.get("messages") or []
    seen: dict[tuple, list[int]] = {}
    for i, m in enumerate(msgs):
        if not isinstance(m, dict):
            continue
        # OpenAI 스타일
        for tc in (m.get("tool_calls") or []) if isinstance(m.get("tool_calls"), list) else []:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") or {}
            name = fn.get("name") if isinstance(fn, dict) else None
            args = fn.get("arguments") if isinstance(fn, dict) else None
            if name is None:
                continue
            key = (name, args if isinstance(args, str) else json.dumps(args, sort_keys=True, ensure_ascii=False))
            seen.setdefault(key, []).append(i)
        # Anthropic 스타일
        content = m.get("content")
        if isinstance(content, list):
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_use":
                    continue
                name = b.get("name")
                args = b.get("input")
                if name is None:
                    continue
                key = (name, json.dumps(args, sort_keys=True, ensure_ascii=False))
                seen.setdefault(key, []).append(i)

    dup_keys = [k for k, v in seen.items() if len(v) >= 2]
    print(f"\n  같은 (tool, args) 로 2회 이상 호출된 group 존재?  → {'Y' if dup_keys else 'N'}")
    if dup_keys:
        print(f"  [예시 최대 3개 — args 앞 80자]")
        for name, args in dup_keys[:3]:
            idxs = seen[(name, args)]
            print(f"    tool={name!r} count={len(idxs)} msg_idxs={idxs[:5]}")
            print(f"      args_head80: {_head(args, 80)!r}")


def main():
    t0 = time.perf_counter()
    if not DATA.exists():
        print(f"파일 없음: {DATA}")
        return
    traces = _load_all()
    first_deser = _deser(traces[0])
    q1(traces)
    q2(first_deser)
    q3(first_deser)
    q4(first_deser)
    q5(first_deser)
    q6(first_deser)
    print()
    print("=" * 100)
    print(f"wall time: {time.perf_counter() - t0:.1f}s")
    print("=" * 100)


if __name__ == "__main__":
    main()
