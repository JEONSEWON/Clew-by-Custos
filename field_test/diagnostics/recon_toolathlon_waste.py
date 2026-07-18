"""field_test/diagnostics/recon_toolathlon_waste.py

Toolathlon 낭비 존재 확인 (리콘, 커밋 금지).

규율:
- 어댑터 코드 아님. 리콘.
- 데이터 커밋 금지 (.gitignore data/).
- raw. 카운트 O, 정의는 잠정 (사전등록 전).

대상: data/toolathlon/*.jsonl (여러 파일 있으면 전부)

Usage:
    python field_test/diagnostics/recon_toolathlon_waste.py
"""
from __future__ import annotations

import hashlib
import json
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

DATA_DIR = Path("data/toolathlon")


def _sha256(text: str) -> str:
    if not isinstance(text, str):
        text = json.dumps(text, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _head(s, n: int = 80) -> str:
    if not isinstance(s, str):
        s = str(s)
    s = s.replace("\n", " ").replace("\r", " ")
    return s if len(s) <= n else s[:n] + "..."


def _deser(d: dict) -> dict:
    """README: 값이 전부 JSON 문자열. 필요 필드만 loads."""
    out = dict(d)
    for k in ("config", "tool_calls", "messages", "key_stats", "agent_cost", "task_status"):
        v = out.get(k)
        if isinstance(v, str):
            try:
                out[k] = json.loads(v)
            except Exception:
                pass
    return out


def _load_all(paths):
    for p in paths:
        with p.open(encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                s = line.strip()
                if not s:
                    continue
                try:
                    yield (p.name, lineno, _deser(json.loads(s)))
                except Exception as e:
                    print(f"[SKIP] {p.name}:{lineno} {e}")


def _extract_calls_and_results(t: dict):
    """
    messages 순회 → (call_records, result_records) 반환.
    call_records: (msg_idx, sub_idx, id, name, arguments_str)  # sub_idx = tool_calls 안 순서
    result_records: (msg_idx, tool_call_id, content_str)
    """
    calls = []
    results = []
    msgs = t.get("messages")
    if not isinstance(msgs, list):
        return calls, results
    for i, m in enumerate(msgs):
        if not isinstance(m, dict):
            continue
        tc = m.get("tool_calls")
        if isinstance(tc, list):
            for j, c in enumerate(tc):
                if not isinstance(c, dict):
                    continue
                fn = c.get("function") or {}
                name = fn.get("name") if isinstance(fn, dict) else None
                args = fn.get("arguments") if isinstance(fn, dict) else None
                if not isinstance(args, str):
                    args = json.dumps(args, sort_keys=True, ensure_ascii=False)
                calls.append((i, j, c.get("id"), name, args))
        if m.get("role") == "tool":
            content = m.get("content")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            results.append((i, m.get("tool_call_id"), content))
    return calls, results


def q1(traces_meta):
    print("=" * 100)
    print("Q1 성공/실패 분포 + 호출 수")
    print("=" * 100)
    evals = Counter()
    runnings = Counter()
    call_counts = []
    counts_by_eval = defaultdict(list)
    counts_by_running = defaultdict(list)
    for meta in traces_meta:
        ev = str(meta["evaluation"])
        rn = str(meta["running"])
        evals[ev] += 1
        runnings[rn] += 1
        call_counts.append(meta["n_calls"])
        counts_by_eval[ev].append(meta["n_calls"])
        counts_by_running[rn].append(meta["n_calls"])
    print(f"  총 트레이스     : {len(traces_meta)}")
    print(f"  task_status.evaluation:")
    for k, c in evals.most_common():
        print(f"    {k!r:<12} {c}")
    print(f"  task_status.running:")
    for k, c in runnings.most_common():
        print(f"    {k!r:<24} {c}")

    def _desc(name, vals):
        if not vals:
            return
        vals_sorted = sorted(vals)
        n = len(vals_sorted)
        p50 = statistics.median(vals_sorted)
        p10 = vals_sorted[int(n * 0.1)]
        p90 = vals_sorted[int(n * 0.9)] if n > 1 else vals_sorted[-1]
        print(f"    {name:<40} n={n:<4}  min={min(vals_sorted):<4} p10={p10:<4} "
              f"p50={p50:<5} p90={p90:<5} max={max(vals_sorted):<5} mean={statistics.mean(vals_sorted):.1f}")

    print(f"\n  트레이스당 tool 호출 수 (describe):")
    _desc("전체", call_counts)
    for ev, vals in sorted(counts_by_eval.items()):
        _desc(f"evaluation={ev}", vals)
    for rn, vals in sorted(counts_by_running.items()):
        _desc(f"running={rn}", vals)


def q2(traces_meta):
    print()
    print("=" * 100)
    print("Q2 같은 (tool, arguments) 재호출 존재 여부")
    print("=" * 100)
    traces_with_repeat = 0
    total_repeat_pairs = 0
    top = []  # (count, task_name, file, tool, args)
    by_eval_traces = defaultdict(int)
    by_eval_repeats = defaultdict(int)
    by_eval_totals = Counter()
    for meta in traces_meta:
        by_eval_totals[str(meta["evaluation"])] += 1
        groups = defaultdict(list)  # (name, args) → [msg_idx]
        for (i, j, cid, name, args) in meta["calls"]:
            if name is None:
                continue
            groups[(name, args)].append(i)
        dup_groups = [(k, v) for k, v in groups.items() if len(v) >= 2]
        if dup_groups:
            traces_with_repeat += 1
            by_eval_traces[str(meta["evaluation"])] += 1
        pair_count = sum(len(v) - 1 for k, v in dup_groups)  # candidate 개수 = 그룹크기-1
        total_repeat_pairs += pair_count
        by_eval_repeats[str(meta["evaluation"])] += pair_count
        for (name, args), idxs in dup_groups:
            top.append((len(idxs), meta["task_name"], meta["file"], name, args))

    print(f"  전체 트레이스               : {len(traces_meta)}")
    print(f"  재호출 있는 트레이스        : {traces_with_repeat}")
    print(f"  재호출 candidate 총 건수    : {total_repeat_pairs}")
    print(f"    (candidate = 그룹크기 - 1, origin 은 정상)")

    print(f"\n  evaluation 별 재호출 비율:")
    for ev, tot in by_eval_totals.most_common():
        wt = by_eval_traces.get(ev, 0)
        pr = by_eval_repeats.get(ev, 0)
        print(f"    evaluation={ev!r:<8} 트레이스 {tot}  재호출있음 {wt} ({100*wt/tot:.0f}%)  cand총 {pr}")

    if top:
        top.sort(reverse=True, key=lambda x: x[0])
        print(f"\n  [상위 5개 그룹 (그룹크기 기준)]")
        for i, (cnt, tname, fname, name, args) in enumerate(top[:5], 1):
            print(f"    #{i} count={cnt}  task={tname!r}  file={fname}")
            print(f"        tool={name!r}")
            print(f"        args_head80={_head(args)!r}")


def q3(traces_meta):
    print()
    print("=" * 100)
    print("Q3 재호출 쌍의 출력 sha256 동일성 (§22.10 게이트 시뮬레이션)")
    print("=" * 100)
    total_pairs = 0
    equal_pairs = 0
    per_eval = defaultdict(lambda: [0, 0])  # [total, equal]

    for meta in traces_meta:
        # id → content 매핑
        id_to_out = {rid: content for (mi, rid, content) in meta["results"]}
        # (name, args) 그룹핑 (order 유지 = msg_idx 정렬)
        groups = defaultdict(list)
        for (i, j, cid, name, args) in meta["calls"]:
            if name is None:
                continue
            groups[(name, args)].append((i, j, cid))
        for (name, args), items in groups.items():
            if len(items) < 2:
                continue
            items.sort()  # msg 순
            _, _, origin_id = items[0]
            origin_out = id_to_out.get(origin_id, "")
            origin_sha = _sha256(origin_out)
            for (mi, mj, cand_id) in items[1:]:
                cand_out = id_to_out.get(cand_id, "")
                cand_sha = _sha256(cand_out)
                total_pairs += 1
                per_eval[str(meta["evaluation"])][0] += 1
                if cand_sha == origin_sha:
                    equal_pairs += 1
                    per_eval[str(meta["evaluation"])][1] += 1

    print(f"  재호출 (origin, cand) 쌍 총 : {total_pairs}")
    if total_pairs > 0:
        print(f"    sha256 동일 (게이트 통과) : {equal_pairs} ({100*equal_pairs/total_pairs:.1f}%)")
        print(f"    sha256 다름              : {total_pairs - equal_pairs} ({100*(total_pairs-equal_pairs)/total_pairs:.1f}%)")
    print(f"\n  evaluation 별:")
    for ev, (t, e) in per_eval.items():
        rate = f"{100*e/t:.1f}%" if t else "-"
        print(f"    evaluation={ev!r:<8} 쌍 {t}  sha동일 {e} ({rate})")


def q4(traces_meta):
    print()
    print("=" * 100)
    print("Q4 병렬 호출 + synthetic timestamp 안전성")
    print("=" * 100)
    parallel_msg_count = 0  # tool_calls list len >= 2 인 메시지 수
    parallel_dup_intra = 0  # 같은 assistant 메시지 안 (name, args) 중복
    results_out_of_order = 0  # tool 결과 순서가 tool_calls 순서와 다름

    for meta in traces_meta:
        # per-msg tool_calls
        msg_calls = defaultdict(list)  # msg_idx → [(sub_idx, cid, name, args)]
        for (i, j, cid, name, args) in meta["calls"]:
            msg_calls[i].append((j, cid, name, args))
        # per-msg results (다음 tool 메시지들의 tool_call_id 순서)
        # 결과가 오는 순서: msg_idx 오름차순, 같은 msg 안엔 하나
        # → 우리는 "그 assistant 메시지의 tool_calls 순서" 대비 "결과 msg 순서에서 매치"
        id_to_result_msgidx = {rid: mi for (mi, rid, _) in meta["results"]}
        for i, calls in msg_calls.items():
            if len(calls) < 2:
                continue
            parallel_msg_count += 1
            # intra-msg dup
            sigs = [(name, args) for _, _, name, args in calls]
            if len(set(sigs)) != len(sigs):
                parallel_dup_intra += 1
            # 결과 순서 (tool_calls 배열 순서대로 매치한 결과의 msg_idx 오름차순인가)
            result_idxs = []
            for _, cid, _, _ in calls:
                ri = id_to_result_msgidx.get(cid)
                if ri is not None:
                    result_idxs.append(ri)
            if result_idxs != sorted(result_idxs):
                results_out_of_order += 1

    print(f"  병렬 호출 메시지 수 (tool_calls>=2): {parallel_msg_count}")
    print(f"  같은 msg 안 (name, args) 중복    : {parallel_dup_intra}")
    print(f"  결과 순서 뒤바뀐 메시지 수        : {results_out_of_order}")
    print(f"    (0 이면 msg_idx→sub_idx 로 synthetic ts 매기면 순서 보존)")


def q5(traces_meta):
    print()
    print("=" * 100)
    print("Q5 tool 이름 목록 + Read/Edit 류 존재")
    print("=" * 100)
    name_counter = Counter()
    for meta in traces_meta:
        for (i, j, cid, name, args) in meta["calls"]:
            if name:
                name_counter[name] += 1

    print(f"  유니크 tool 이름 : {len(name_counter)}")
    print(f"\n  [상위 20 tool + 호출 수]")
    for name, c in name_counter.most_common(20):
        print(f"    {c:>6}  {name}")

    # Read/조회 계열 후보
    read_like_patterns = ("read", "get", "search", "list", "find", "fetch", "view", "query", "show", "cat")
    edit_like_patterns = ("edit", "write", "create", "update", "replace", "modify", "insert", "str_replace", "patch")

    read_hits = [n for n in name_counter if any(p in n.lower() for p in read_like_patterns)]
    edit_hits = [n for n in name_counter if any(p in n.lower() for p in edit_like_patterns)]
    print(f"\n  [Read/조회 계열 후보]  {len(read_hits)}개")
    for n in sorted(read_hits, key=lambda x: -name_counter[x])[:15]:
        print(f"    {name_counter[n]:>6}  {n}")
    print(f"\n  [Edit/쓰기 계열 후보]  {len(edit_hits)}개")
    for n in sorted(edit_hits, key=lambda x: -name_counter[x])[:15]:
        print(f"    {name_counter[n]:>6}  {n}")

    # Edit output 템플릿 유무 (첫 발견 3건)
    print(f"\n  [Edit 계열 output 샘플 (앞 200자)]")
    shown = 0
    for meta in traces_meta:
        id_to_out = {rid: c for (mi, rid, c) in meta["results"]}
        for (i, j, cid, name, args) in meta["calls"]:
            if not name:
                continue
            if not any(p in name.lower() for p in edit_like_patterns):
                continue
            out = id_to_out.get(cid, "")
            print(f"    file={meta['file']}  tool={name!r}")
            print(f"      out_head200={_head(out, 200)!r}")
            shown += 1
            if shown >= 3:
                break
        if shown >= 3:
            break


def main():
    t0 = time.perf_counter()
    paths = sorted(DATA_DIR.glob("*.jsonl"))
    if not paths:
        print(f"파일 없음: {DATA_DIR}/*.jsonl")
        return
    print(f"입력 파일: {[p.name for p in paths]}")
    print()

    traces_meta = []
    for fname, ln, t in _load_all(paths):
        calls, results = _extract_calls_and_results(t)
        ts = t.get("task_status") or {}
        traces_meta.append({
            "file": fname,
            "line": ln,
            "task_name": t.get("task_name"),
            "evaluation": ts.get("evaluation") if isinstance(ts, dict) else None,
            "running": ts.get("running") if isinstance(ts, dict) else None,
            "n_calls": len(calls),
            "calls": calls,
            "results": results,
        })

    print(f"총 로드 트레이스: {len(traces_meta)}")

    q1(traces_meta)
    q2(traces_meta)
    q3(traces_meta)
    q4(traces_meta)
    q5(traces_meta)

    print()
    print("=" * 100)
    print(f"wall time: {time.perf_counter() - t0:.1f}s")
    print("=" * 100)


if __name__ == "__main__":
    main()
