"""SPEC §19 SWE-chat waste density scan (v1'~v4' — post-amendment).

Pre-registered: field_test/SWECHAT_SPEC.md.
Amendment 2026-07-16 (§19.1): EDIT_TOOLS pool contamination fix —
tool_name is on BOTH tool_use and tool_result rows. Filter edits to
turn_type == 'tool_use' before path-matching between Read pairs.
"미확인 Edit → 낭비 아님" 조항 제거. unresolved_between 카운터는
검증용으로 유지 (0이 나와야 정상).

Do NOT modify pool/target/waste rules after seeing results.
"""
import csv
import json
import os
import random
from collections import Counter
from pathlib import Path

import pyarrow.dataset as ds
import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

EDIT_TOOLS = {"Edit", "Write", "MultiEdit"}
OUT_DIR = Path(__file__).parent
CASES_CSV = OUT_DIR / "swechat_waste_cases.csv"
SAMPLE_JSON = OUT_DIR / "swechat_waste_sample20.json"
SAMPLE_SEED = 42


def parse_int(v):
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        try:
            return int(v)
        except ValueError:
            return None
    return None


def is_abs(p):
    if not p:
        return None
    return p.startswith('/') or (len(p) >= 2 and p[1] == ':')


def make_target(args):
    """Return (raw_path, norm_path, target) or (None, None, None)."""
    fp = args.get("file_path") or args.get("filePath")
    if not fp:
        return None, None, None
    raw = fp
    np = os.path.normpath(fp)
    off = parse_int(args.get("offset"))
    lim = parse_int(args.get("limit"))
    if off is None or lim is None:
        return raw, np, (np, "FULL")
    return raw, np, (np, off, lim)


def parse_args(s):
    if s is None:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def load():
    cols = ['turn_id', 'session_id', 'turn_number', 'turn_type', 'tool_name',
            'file_path', 'tool_input_json', 'agent', 'input_tokens', 'output_tokens']
    p = hf_hub_download('SALT-NLP/SWE-chat', 'conversations.parquet', repo_type='dataset')
    return pq.read_table(p, columns=cols).to_pandas()


def load_between_context(session_ids):
    """Second parquet scan for sampled sessions only. Push-down filter (memory-safe)."""
    p = hf_hub_download('SALT-NLP/SWE-chat', 'conversations.parquet', repo_type='dataset')
    dset = ds.dataset(p, format='parquet')
    tbl = dset.to_table(
        columns=['session_id', 'turn_number', 'role', 'turn_type', 'tool_name', 'content'],
        filter=ds.field('session_id').isin(list(session_ids)),
    )
    return tbl.to_pandas()


def scan():
    df = load()
    df = df[df.agent == "Claude Code"]

    # turn_id 데이터셋 중복 제외 (v3 계기: 같은 turn_id 2회 발생 원본 행)
    before_dedup = len(df)
    df = df.drop_duplicates(subset=['turn_id']).copy()
    turn_id_dupes_dropped = before_dedup - len(df)

    # pool 정의 (변경 없음): Claude Code Read + tool_input_json IS NOT NULL
    reads_tij_notna = df[(df.tool_name == "Read") & df.tool_input_json.notna()]
    # 검증: turn_type == 'tool_use' 필터와 결과가 같아야 함. 다르면 즉시 assert.
    reads_ttuse = df[(df.tool_name == "Read") & (df.turn_type == "tool_use")]
    if len(reads_tij_notna) != len(reads_ttuse):
        raise RuntimeError(
            f"POOL SANITY FAILED: tij_notna={len(reads_tij_notna)} "
            f"vs turn_type=='tool_use'={len(reads_ttuse)}. "
            "pool 정의 오류 가능성 — SPEC §19.1 중단조건 2 발동."
        )
    reads_raw = reads_tij_notna.copy()

    # §19.1 핵심 수정: edits 필터에 turn_type == 'tool_use' 강제
    # (기존은 tool_name만 필터하여 tool_result 행까지 포함 → 1,115건 부당 drop 원인)
    edits_raw = df[df.tool_name.isin(EDIT_TOOLS) & (df.turn_type == "tool_use")].copy()

    counters = Counter()
    counters["turn_id_dupes_dropped"] = turn_id_dupes_dropped
    counters["reads_in_pool"] = len(reads_raw)

    reads_raw["_args"] = reads_raw.tool_input_json.apply(parse_args)
    parsed = reads_raw._args.apply(lambda a: make_target(a) if a else (None, None, None))
    reads_raw["_raw_path"] = parsed.apply(lambda t: t[0])
    reads_raw["_np"] = parsed.apply(lambda t: t[1])
    reads_raw["_target"] = parsed.apply(lambda t: t[2])

    dropped = reads_raw._target.isna().sum()
    counters["reads_dropped_no_target"] = int(dropped)
    reads_raw = reads_raw[reads_raw._target.notna()].copy()

    reads_raw["_is_abs"] = reads_raw._raw_path.apply(is_abs)
    mixed_sessions = set()
    for sid, grp in reads_raw.groupby("session_id"):
        if grp._is_abs.nunique() > 1:
            mixed_sessions.add(sid)
    counters["sessions_excluded_mixed_paths"] = len(mixed_sessions)

    reads = reads_raw[~reads_raw.session_id.isin(mixed_sessions)].copy()
    counters["reads_after_mixed_exclusion"] = len(reads)

    def edit_path(row):
        a = parse_args(row.tool_input_json)
        if a is None:
            return None
        fp = a.get("file_path") or a.get("filePath")
        return os.path.normpath(fp) if fp else None

    edits_raw["_path"] = edits_raw.apply(edit_path, axis=1)
    edits = edits_raw[~edits_raw.session_id.isin(mixed_sessions)].copy()
    counters["edits_total"] = len(edits)
    counters["edits_unknown_path"] = int(edits._path.isna().sum())

    reads_by_sess = {sid: g.sort_values("turn_number").reset_index(drop=True)
                     for sid, g in reads.groupby("session_id")}
    edits_by_sess = {sid: g.sort_values("turn_number").reset_index(drop=True)
                     for sid, g in edits.groupby("session_id")}

    waste_cases = []
    file_level_waste_ids = set()
    waste_sessions = set()
    # 검증용 카운터 — turn_type=='tool_use' 필터로 edits._path가 결측일 리 없음.
    # 0이 나와야 정상 (SPEC §19.1 중단조건 1).
    unresolved_between = 0
    file_unresolved_between = 0

    for sid, s_reads in reads_by_sess.items():
        s_edits = edits_by_sess.get(sid)
        seen_target = {}
        seen_path = {}

        for _, r in s_reads.iterrows():
            tgt = r._target
            path = r._np
            tn = int(r.turn_number)

            if tgt in seen_target:
                prev_tn = seen_target[tgt]
                if s_edits is not None:
                    between = s_edits[(s_edits.turn_number > prev_tn) & (s_edits.turn_number < tn)]
                    known_hit = int((between._path == path).sum())
                    unknown_hit = int(between._path.isna().sum())
                    between_count = len(between)
                else:
                    known_hit = unknown_hit = between_count = 0

                if unknown_hit > 0:
                    unresolved_between += 1

                if known_hit > 0:
                    pass
                else:
                    off = tgt[1] if len(tgt) == 3 else ""
                    lim = tgt[2] if len(tgt) == 3 else ""
                    waste_cases.append({
                        "session_id": sid,
                        "turn_id": r.turn_id,
                        "turn_number": tn,
                        "norm_path": path,
                        "offset": off,
                        "limit": lim,
                        "prev_turn_number": prev_tn,
                        "between_edit_count": between_count,
                        "input_tokens": int(r.input_tokens or 0),
                        "output_tokens": int(r.output_tokens or 0),
                    })
                    waste_sessions.add(sid)
            seen_target[tgt] = tn

            if path in seen_path:
                prev_tn = seen_path[path]
                if s_edits is not None:
                    between = s_edits[(s_edits.turn_number > prev_tn) & (s_edits.turn_number < tn)]
                    if int(between._path.isna().sum()) > 0:
                        file_unresolved_between += 1
                    if int((between._path == path).sum()) == 0:
                        file_level_waste_ids.add(r.turn_id)
                else:
                    file_level_waste_ids.add(r.turn_id)
            seen_path[path] = tn

    n_read_sessions = len(reads_by_sess)
    total_reads = len(reads)
    total_tokens = int((reads.input_tokens.fillna(0) + reads.output_tokens.fillna(0)).sum())
    waste_token_sum = sum(c["input_tokens"] + c["output_tokens"] for c in waste_cases)

    print("=== SPEC §19 SWE-chat 낭비 밀도 결과 (v1' 재실행, EDIT_TOOLS 오염 수정) ===")
    print(f"turn_id 데이터셋 중복 drop: {counters['turn_id_dupes_dropped']}")
    print(f"pool: Claude Code Read + tool_input_json non-null = {counters['reads_in_pool']}")
    print(f"  (pool sanity 검증: turn_type=='tool_use'와 일치 확인 통과)")
    print(f"target 파싱 실패 drop: {counters['reads_dropped_no_target']}")
    print(f"절대·상대 혼용으로 제외된 세션: {counters['sessions_excluded_mixed_paths']}")
    print(f"분석 대상 Read: {counters['reads_after_mixed_exclusion']}")
    print(f"분석 대상 세션: {n_read_sessions}")
    print(f"Edit 계열 tool_use 총: {counters['edits_total']}  "
          f"(_path 결측: {counters['edits_unknown_path']} — 0이어야 정상)")
    print(f"[검증] unresolved_between (range-level): {unresolved_between} — 0이어야 정상")
    print(f"[검증] file_unresolved_between: {file_unresolved_between} — 0이어야 정상")
    print()
    print(f"[1] 낭비 1건+ 세션 비율: {len(waste_sessions)}/{n_read_sessions} = "
          f"{len(waste_sessions)/max(n_read_sessions,1)*100:.2f}%")
    print(f"[2] 낭비 Read / 전체 Read: {len(waste_cases)}/{total_reads} = "
          f"{len(waste_cases)/max(total_reads,1)*100:.3f}%")
    print(f"[3] 낭비 토큰 합: {waste_token_sum:,} / 전체 {total_tokens:,} = "
          f"{waste_token_sum/max(total_tokens,1)*100:.3f}%")
    print(f"[4] File-level 대조군 낭비 Read: {len(file_level_waste_ids)} "
          f"(range-level 대비 +{len(file_level_waste_ids)-len(waste_cases)})")
    if len(file_level_waste_ids) > 0:
        removal_rate = (1 - len(waste_cases) / len(file_level_waste_ids)) * 100
        print(f"    오탐 제거율: {removal_rate:.1f}%")

    fields = ["session_id", "turn_id", "turn_number", "norm_path", "offset", "limit",
              "prev_turn_number", "between_edit_count", "input_tokens", "output_tokens"]
    with open(CASES_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(waste_cases)
    print(f"\n케이스 덤프: {CASES_CSV} ({len(waste_cases)} rows)")

    rng = random.Random(SAMPLE_SEED)
    sample = rng.sample(waste_cases, min(20, len(waste_cases)))

    if sample:
        sids_needed = {c["session_id"] for c in sample}
        ctx_df = load_between_context(sids_needed)
        ctx_by_sess = {sid: g.sort_values("turn_number") for sid, g in ctx_df.groupby("session_id")}

        for c in sample:
            sess = ctx_by_sess.get(c["session_id"])
            if sess is None:
                c["between_turns"] = []
                continue
            bt = sess[(sess.turn_number > c["prev_turn_number"]) &
                      (sess.turn_number < c["turn_number"])]
            c["between_turns"] = [
                {
                    "turn_number": int(r.turn_number),
                    "role": str(r.role) if r.role else "",
                    "turn_type": str(r.turn_type) if r.turn_type else "",
                    "tool_name": str(r.tool_name) if r.tool_name else "",
                    "content_preview": (str(r.content)[:200] if r.content else ""),
                }
                for _, r in bt.iterrows()
            ]

    with open(SAMPLE_JSON, "w", encoding="utf-8") as f:
        json.dump({"seed": SAMPLE_SEED, "cases": sample}, f, indent=2, ensure_ascii=False)
    print(f"사람 판정용 20건 (between_turns 맥락 포함): {SAMPLE_JSON}")


if __name__ == "__main__":
    scan()
