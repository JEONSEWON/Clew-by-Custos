"""field_test/diagnostics/recon_cc_transcript.py

Claude Code 원본 transcript 리콘. 어댑터 코드 아님.

규율:
- transcript 자체는 레포에 커밋 금지 (~/.claude/projects/ 에서 읽기만).
- 텍스트 덤프는 앞 60자로 절단 후 출력. sk-... 패턴 마스킹.
- 표본은 "최근 세션" (규모 상위 N 아님) — 현재 실행 중 세션 회피를 위해
  현재 프로젝트의 두 번째 최신 세션 사용.

Usage:
    python field_test/diagnostics/recon_cc_transcript.py --q 1
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
TRUNC = 60
CUR_PROJECT_DIR = "C--Users-User-Desktop-Custos---clwe-project"


def _mask(s: str) -> str:
    return re.sub(r"sk-[A-Za-z0-9]{20,}", "sk-***", s)


def _trunc(s: str) -> str:
    s = _mask(s)
    return s if len(s) <= TRUNC else s[:TRUNC] + "…"


def target_session() -> Path:
    proj = PROJECTS / CUR_PROJECT_DIR
    files = sorted(proj.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        sys.exit("no jsonl in project dir")
    # 현재 실행 중 세션(files[0]) 회피 → 최신 완료 세션(files[1])
    return files[1] if len(files) > 1 else files[0]


def load_lines(path: Path) -> list[dict]:
    out: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                out.append(json.loads(s))
            except json.JSONDecodeError:
                pass
    return out


def q1() -> None:
    print(f"projects_dir: {PROJECTS}")
    print(f"exists: {PROJECTS.exists()}")
    proj_dirs = [p for p in PROJECTS.iterdir() if p.is_dir()]
    print(f"project_count: {len(proj_dirs)}")
    all_jsonl: list[Path] = []
    for p in proj_dirs:
        all_jsonl.extend(p.glob("*.jsonl"))
    print(f"total_jsonl: {len(all_jsonl)}")
    sizes = [f.stat().st_size for f in all_jsonl]
    if sizes:
        print(
            f"size_bytes: min={min(sizes)} median={int(statistics.median(sizes))} max={max(sizes)}"
        )
    tgt = target_session()
    print(f"target_project: {tgt.parent.name}")
    print(f"target_file: {tgt.name}")
    print(f"target_size: {tgt.stat().st_size}")
    print(f"target_mtime: {tgt.stat().st_mtime}")


def q2() -> None:
    tgt = target_session()
    lines = load_lines(tgt)
    print(f"file: {tgt.name}")
    print(f"total_lines: {len(lines)}")
    keyset_c: Counter[tuple[str, ...]] = Counter()
    for obj in lines:
        keyset_c[tuple(sorted(obj.keys()))] += 1
    print(f"distinct_keysets: {len(keyset_c)}")
    print("top10_keysets:")
    for keys, cnt in keyset_c.most_common(10):
        print(f"  {cnt:6d}  {list(keys)}")
    types = Counter(obj.get("type") for obj in lines)
    print(f"type_counts: {dict(types.most_common(10))}")
    roles: Counter[str | None] = Counter()
    for obj in lines:
        msg = obj.get("message") or {}
        if isinstance(msg, dict):
            roles[msg.get("role")] += 1
    print(f"message.role_counts: {dict(roles.most_common(10))}")
    print("first_3_lines_keys_only:")
    for i, obj in enumerate(lines[:3]):
        summary = {}
        for k, v in obj.items():
            if isinstance(v, dict):
                summary[k] = f"dict(keys={len(v)})"
            elif isinstance(v, list):
                summary[k] = f"list(len={len(v)})"
            elif isinstance(v, str):
                summary[k] = f"str(len={len(v)})"
            else:
                summary[k] = f"{type(v).__name__}={v!r}" if v is not None else "None"
        print(f"  L{i}: {summary}")


def _walk(obj, path=""):
    """usage 필드 재귀 탐색."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_path = f"{path}.{k}" if path else k
            if k == "usage" and isinstance(v, dict):
                yield new_path, v
            yield from _walk(v, new_path)
    elif isinstance(obj, list):
        for it in obj:
            yield from _walk(it, path + "[]")


def q3() -> None:
    tgt = target_session()
    lines = load_lines(tgt)
    print(f"file: {tgt.name}")
    print(f"n_lines: {len(lines)}")
    path_c: Counter[str] = Counter()
    field_values: dict[str, list[int]] = defaultdict(list)
    turn_type_with_usage: Counter[str | None] = Counter()
    role_with_usage: Counter[str | None] = Counter()
    for obj in lines:
        found_here = False
        for u_path, usage in _walk(obj):
            found_here = True
            for k, v in usage.items():
                path_c[f"{u_path}.{k}"] += 1
                if isinstance(v, (int, float)):
                    field_values[k].append(int(v))
        if found_here:
            turn_type_with_usage[obj.get("type")] += 1
            msg = obj.get("message") or {}
            role_with_usage[msg.get("role") if isinstance(msg, dict) else None] += 1
    print("token_field_paths (top 20):")
    for p, c in path_c.most_common(20):
        print(f"  {c:6d}  {p}")
    print("field_value_summary:")
    for k, vals in field_values.items():
        nz = [v for v in vals if v != 0]
        print(
            f"  {k}: n={len(vals)} nonzero={len(nz)} "
            f"min={min(vals)} max={max(vals)} "
            f"sum={sum(vals)}"
        )
    print(f"usage_on_type: {dict(turn_type_with_usage)}")
    print(f"usage_on_role: {dict(role_with_usage)}")


def q4() -> None:
    tgt = target_session()
    lines = load_lines(tgt)
    print(f"file: {tgt.name}")
    thinking_count = 0
    lens: list[int] = []
    sample: str | None = None
    seen_types: Counter[str] = Counter()
    for obj in lines:
        msg = obj.get("message") or {}
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            seen_types[btype] += 1
            if btype == "thinking":
                thinking_count += 1
                txt = block.get("thinking") or ""
                lens.append(len(txt))
                if sample is None and txt.strip():
                    sample = txt
    print(f"content_block_types: {dict(seen_types)}")
    print(f"thinking_blocks: {thinking_count}")
    if lens:
        print(
            f"thinking_len: min={min(lens)} median={int(statistics.median(lens))} max={max(lens)}"
        )
    if sample is not None:
        head = _mask(sample)[:300]
        print(f"sample_first_300 repr: {head!r}")


def q5() -> None:
    tgt = target_session()
    lines = load_lines(tgt)
    print(f"file: {tgt.name}")
    read_inputs: list[dict] = []
    read_results_text: list[str] = []
    for obj in lines:
        msg = obj.get("message") or {}
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "tool_use" and block.get("name") == "Read":
                read_inputs.append(block.get("input") or {})
            elif btype == "tool_result":
                c = block.get("content")
                if isinstance(c, list):
                    for cb in c:
                        if isinstance(cb, dict) and cb.get("type") == "text":
                            read_results_text.append(cb.get("text") or "")
                elif isinstance(c, str):
                    read_results_text.append(c)
    print(f"read_tool_use_count: {len(read_inputs)}")
    # 인자 구조
    input_keysets: Counter[tuple[str, ...]] = Counter()
    for inp in read_inputs:
        input_keysets[tuple(sorted(inp.keys()))] += 1
    print(f"read_input_keysets: {dict(input_keysets)}")
    print("read_input_samples (2):")
    for inp in read_inputs[:2]:
        safe = {k: (_trunc(v) if isinstance(v, str) else v) for k, v in inp.items()}
        print(f"  {safe}")
    # tool_result 앞 40자 repr — 라인번호 접두
    line_prefixed = [t for t in read_results_text if re.match(r"^\s*\d+", t)]
    print(f"tool_result_total: {len(read_results_text)}")
    print(f"tool_result_line_prefixed: {len(line_prefixed)}")
    print("line_prefixed_first_40_repr (2 samples):")
    for t in line_prefixed[:2]:
        head = t[:40]
        print(f"  repr = {head!r}")
        print(f"  ord  = {[ord(c) for c in head[:20]]}")
    # 캐시 마커
    lc_all = [t.lower() for t in read_results_text]
    unchanged = sum(1 for t in lc_all if "unchanged" in t)
    cached = sum(1 for t in lc_all if "cached" in t)
    not_changed = sum(1 for t in lc_all if "not changed" in t)
    print(
        f"cache_markers: unchanged={unchanged} cached={cached} not_changed={not_changed}"
    )


def q6() -> None:
    tgt = target_session()
    lines = load_lines(tgt)
    print(f"file: {tgt.name}")
    use_ids: list[tuple[str, str]] = []  # (tool_use.id, name)
    res_ids: list[str] = []
    for obj in lines:
        msg = obj.get("message") or {}
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "tool_use":
                tid = block.get("id")
                name = block.get("name", "?")
                if tid:
                    use_ids.append((tid, name))
            elif btype == "tool_result":
                tid = block.get("tool_use_id")
                if tid:
                    res_ids.append(tid)
    use_c = Counter(t for t, _ in use_ids)
    res_c = Counter(res_ids)
    print(f"tool_use_id_field: 'id' inside tool_use block")
    print(f"tool_result_join_field: 'tool_use_id' inside tool_result block")
    print(f"tool_use: total={len(use_ids)} unique={len(use_c)}")
    print(f"tool_result: total={len(res_ids)} unique={len(res_c)}")
    dup_use = [t for t, c in use_c.items() if c > 1]
    dup_res = [t for t, c in res_c.items() if c > 1]
    print(f"use_dup_ids: {len(dup_use)}")
    print(f"res_dup_ids: {len(dup_res)}")
    if dup_res:
        print(f"max_dup_per_res_id: {max(res_c.values())}")
    unmatched_res = [t for t in res_ids if t not in use_c]
    unmatched_use = [t for t, _ in use_ids if t not in res_c]
    print(f"result_without_matching_use: {len(unmatched_res)}")
    print(f"use_without_matching_result: {len(unmatched_use)}")
    # per-tool 분포
    per_tool_use = Counter(name for _, name in use_ids)
    per_tool_res: Counter[str] = Counter()
    use_id_to_name = {t: n for t, n in use_ids}
    for r in res_ids:
        per_tool_res[use_id_to_name.get(r, "?")] += 1
    print(f"per_tool_use: {dict(per_tool_use.most_common(15))}")
    print(f"per_tool_res_via_use_id: {dict(per_tool_res.most_common(15))}")
    # Read / Bash 특화 — 조인 카디널리티
    for tool in ("Read", "Bash"):
        tool_use_ids = [t for t, n in use_ids if n == tool]
        counts = [res_c.get(t, 0) for t in tool_use_ids]
        if counts:
            n_dup = sum(1 for c in counts if c > 1)
            print(
                f"{tool}: use={len(tool_use_ids)} res_pair_max={max(counts) if counts else 0} "
                f"use_with_>1_res={n_dup}"
            )


def q4a() -> None:
    """thinking 블록 1개 raw dump — 키 이름 절대 마스킹 금지."""
    tgt = target_session()
    print(f"file: {tgt.name}")
    redacted_count = 0
    for obj in load_lines(tgt):
        msg = obj.get("message") or {}
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if isinstance(b, dict) and b.get("type") == "redacted_thinking":
                redacted_count += 1
    print(f"redacted_thinking_blocks: {redacted_count}")
    # thinking block sample
    for obj in load_lines(tgt):
        msg = obj.get("message") or {}
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if isinstance(b, dict) and b.get("type") == "thinking":
                # mask value contents but NOT keys
                safe = {}
                for k, v in b.items():
                    if k == "signature" and isinstance(v, str):
                        safe[k] = v[:40] + f"...(len={len(v)})"
                    else:
                        safe[k] = v
                raw = json.dumps(safe, ensure_ascii=False)[:400]
                print(f"block_raw_first_400: {raw}")
                print(f"keys: {sorted(b.keys())}")
                for k, v in b.items():
                    if isinstance(v, str):
                        print(f"  {k}: str len={len(v)}")
                    else:
                        print(f"  {k}: {type(v).__name__} = {v!r}")
                return


def q4b() -> None:
    """전 프로젝트 전 세션 thinking 전수 확인."""
    total = 0
    nz = 0
    nz_details: list[tuple[str, str, int, str]] = []  # (project, file, len, ts)
    proj_dirs = [p for p in PROJECTS.iterdir() if p.is_dir()]
    file_count = 0
    for pd in proj_dirs:
        for jf in pd.glob("*.jsonl"):
            file_count += 1
            for line in jf.open(encoding="utf-8"):
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except json.JSONDecodeError:
                    continue
                msg = obj.get("message") or {}
                if not isinstance(msg, dict):
                    continue
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "thinking":
                        total += 1
                        txt = b.get("thinking") or ""
                        if len(txt) > 0:
                            nz += 1
                            nz_details.append(
                                (pd.name, jf.name, len(txt), obj.get("timestamp", ""))
                            )
    print(f"projects_scanned: {len(proj_dirs)}")
    print(f"files_scanned: {file_count}")
    print(f"thinking_total: {total}")
    print(f"thinking_nonzero_text: {nz}")
    if nz_details:
        print("nonzero_samples (up to 10):")
        for proj, fn, length, ts in nz_details[:10]:
            print(f"  {proj}/{fn[:16]}...  len={length}  ts={ts}")
    else:
        print("all_zero: True")


def q4c() -> None:
    """thinking timestamp 분포 (모든 세션)."""
    timestamps: list[str] = []
    lengths: list[int] = []
    ts_len_pairs: list[tuple[str, int]] = []
    for pd in [p for p in PROJECTS.iterdir() if p.is_dir()]:
        for jf in pd.glob("*.jsonl"):
            for line in jf.open(encoding="utf-8"):
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except json.JSONDecodeError:
                    continue
                msg = obj.get("message") or {}
                if not isinstance(msg, dict):
                    continue
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                ts = obj.get("timestamp", "")
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "thinking":
                        timestamps.append(ts)
                        L = len(b.get("thinking") or "")
                        lengths.append(L)
                        ts_len_pairs.append((ts, L))
    print(f"total: {len(timestamps)}")
    if timestamps:
        print(f"ts_min: {min(timestamps)}")
        print(f"ts_max: {max(timestamps)}")
    # 월별 그룹핑 (YYYY-MM)
    from collections import defaultdict
    by_month: dict[str, list[int]] = defaultdict(list)
    for ts, L in ts_len_pairs:
        m = ts[:7] if len(ts) >= 7 else "unknown"
        by_month[m].append(L)
    print("by_month (n, min_len, max_len, nonzero_count):")
    for m in sorted(by_month.keys()):
        vals = by_month[m]
        nzc = sum(1 for v in vals if v > 0)
        print(f"  {m}: n={len(vals)} min={min(vals)} max={max(vals)} nz={nzc}")


def q3a() -> None:
    """usage 전체 raw 덤프 + 필드명 + describe."""
    tgt = target_session()
    print(f"file: {tgt.name}")
    lines = load_lines(tgt)
    asst_total = 0
    usage_present = 0
    output_tokens_nz: list[int] = []
    field_names: set[str] = set()
    sample_usage = None
    for obj in lines:
        msg = obj.get("message") or {}
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "assistant":
            asst_total += 1
        usage = msg.get("usage")
        if isinstance(usage, dict):
            usage_present += 1
            for k in usage.keys():
                field_names.add(k)
            ot = usage.get("output_tokens")
            if isinstance(ot, int) and ot > 0:
                output_tokens_nz.append(ot)
            if sample_usage is None:
                sample_usage = usage
    print(f"assistant_turns: {asst_total}")
    print(f"turns_with_usage: {usage_present}")
    print(f"usage_field_names: {sorted(field_names)}")
    if sample_usage is not None:
        raw = json.dumps(sample_usage, ensure_ascii=False)
        print(f"sample_usage_raw: {raw[:500]}")
    if output_tokens_nz:
        print(
            f"output_tokens_nz: n={len(output_tokens_nz)} "
            f"min={min(output_tokens_nz)} "
            f"median={int(statistics.median(output_tokens_nz))} "
            f"max={max(output_tokens_nz)}"
        )


def q3b() -> None:
    """tool_result char 수 vs 다음/이전 assistant usage 5쌍."""
    tgt = target_session()
    print(f"file: {tgt.name}")
    lines = load_lines(tgt)
    # sequence: (idx, kind, ...)  kind ∈ {"asst_usage", "read_result"}
    events: list[tuple[int, str, dict]] = []
    for i, obj in enumerate(lines):
        msg = obj.get("message") or {}
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        # assistant with usage
        if msg.get("role") == "assistant":
            usage = msg.get("usage") or {}
            if isinstance(usage, dict) and usage:
                events.append(
                    (
                        i,
                        "asst",
                        {
                            "input": usage.get("input_tokens"),
                            "cache_read": usage.get("cache_read_input_tokens"),
                            "cache_create": usage.get("cache_creation_input_tokens"),
                            "output": usage.get("output_tokens"),
                        },
                    )
                )
        # tool_result Read
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    c = b.get("content")
                    txt = ""
                    if isinstance(c, list):
                        for cb in c:
                            if isinstance(cb, dict) and cb.get("type") == "text":
                                txt += cb.get("text") or ""
                    elif isinstance(c, str):
                        txt = c
                    if re.match(r"^\s*\d+", txt):
                        events.append((i, "read_res", {"chars": len(txt)}))
    # pick 5 read_res events with a preceding asst and following asst
    picked = 0
    print("pairs (prev_asst | read_res | next_asst):")
    for idx in range(len(events)):
        if events[idx][1] != "read_res":
            continue
        # find nearest prev asst
        prev_asst = None
        for j in range(idx - 1, -1, -1):
            if events[j][1] == "asst":
                prev_asst = events[j][2]
                break
        # find nearest next asst
        next_asst = None
        for j in range(idx + 1, len(events)):
            if events[j][1] == "asst":
                next_asst = events[j][2]
                break
        if prev_asst is None or next_asst is None:
            continue
        rc = events[idx][2]["chars"]
        print(
            f"  P#{picked}: read_chars={rc}  "
            f"prev in={prev_asst['input']} cache_r={prev_asst['cache_read']} out={prev_asst['output']}  |  "
            f"next in={next_asst['input']} cache_r={next_asst['cache_read']} cache_c={next_asst['cache_create']} out={next_asst['output']}"
        )
        picked += 1
        if picked >= 5:
            break


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--q", type=str, required=True)
    args = ap.parse_args()
    handlers = {
        "1": q1, "2": q2, "3": q3, "4": q4, "5": q5, "6": q6,
        "3a": q3a, "3b": q3b, "4a": q4a, "4b": q4b, "4c": q4c,
    }
    handlers[args.q]()
