"""One-off diagnostic — reproduces SPEC §19.1 finding:
'old_unresolved 1,115 → v1\' waste: 1,115 전건 승격'
그리고 신규 1,114 vs 승격 1,115의 오차 1건 (turn_id 153f7e94-...#131이
old_waste ∩ old_unresolved 중복이라는 raw 확인).

이 스크립트는 OLD scan 로직(dedup 없음, turn_type 필터 없음)을 재현하여
1,115 unresolved turn_id 집합을 산출하고, 8018ae0 커밋의 v1 waste CSV와
현재 v1' waste CSV와 비교한다.

Rerun requires git access to commit 8018ae0.
"""
import csv
import json
import os
import subprocess
from pathlib import Path

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

EDIT_TOOLS = {"Edit", "Write", "MultiEdit"}
NEW_CSV = Path(__file__).parents[1] / "swechat_waste_cases.csv"
OLD_CSV_COMMIT = "8018ae0"
OLD_CSV_PATH = "field_test/swechat_waste_cases.csv"


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
    fp = args.get("file_path") or args.get("filePath")
    if not fp:
        return None, None, None
    np = os.path.normpath(fp)
    off = parse_int(args.get("offset"))
    lim = parse_int(args.get("limit"))
    if off is None or lim is None:
        return fp, np, (np, "FULL")
    return fp, np, (np, off, lim)


def parse_args_json(s):
    if s is None:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def old_scan_unresolved_and_waste():
    """Reproduce OLD scan (no turn_id dedup, no turn_type filter on edits).
    Returns (unresolved_turn_ids, waste_turn_ids)."""
    cols = ['turn_id', 'session_id', 'turn_number', 'tool_name', 'file_path',
            'tool_input_json', 'agent']
    p = hf_hub_download('SALT-NLP/SWE-chat', 'conversations.parquet', repo_type='dataset')
    df = pq.read_table(p, columns=cols).to_pandas()
    df = df[df.agent == "Claude Code"]

    reads_raw = df[(df.tool_name == "Read") & df.tool_input_json.notna()].copy()
    edits_raw = df[df.tool_name.isin(EDIT_TOOLS)].copy()

    reads_raw["_args"] = reads_raw.tool_input_json.apply(parse_args_json)
    parsed = reads_raw._args.apply(lambda a: make_target(a) if a else (None, None, None))
    reads_raw["_raw_path"] = parsed.apply(lambda t: t[0])
    reads_raw["_np"] = parsed.apply(lambda t: t[1])
    reads_raw["_target"] = parsed.apply(lambda t: t[2])
    reads_raw = reads_raw[reads_raw._target.notna()].copy()
    reads_raw["_is_abs"] = reads_raw._raw_path.apply(is_abs)

    mixed_sessions = set()
    for sid, grp in reads_raw.groupby("session_id"):
        if grp._is_abs.nunique() > 1:
            mixed_sessions.add(sid)
    reads = reads_raw[~reads_raw.session_id.isin(mixed_sessions)].copy()

    def edit_path(row):
        a = parse_args_json(row.tool_input_json)
        if a is None:
            return None
        fp = a.get("file_path") or a.get("filePath")
        return os.path.normpath(fp) if fp else None

    edits_raw["_path"] = edits_raw.apply(edit_path, axis=1)
    edits = edits_raw[~edits_raw.session_id.isin(mixed_sessions)].copy()

    reads_by_sess = {sid: g.sort_values("turn_number").reset_index(drop=True)
                     for sid, g in reads.groupby("session_id")}
    edits_by_sess = {sid: g.sort_values("turn_number").reset_index(drop=True)
                     for sid, g in edits.groupby("session_id")}

    unresolved = set()
    waste = set()
    for sid, s_reads in reads_by_sess.items():
        s_edits = edits_by_sess.get(sid)
        seen_target = {}
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
                else:
                    known_hit = unknown_hit = 0
                if known_hit > 0:
                    pass
                elif unknown_hit > 0:
                    unresolved.add(r.turn_id)
                else:
                    waste.add(r.turn_id)
            seen_target[tgt] = tn
    return unresolved, waste


def main():
    print("[1] Reproducing OLD scan (no dedup, no turn_type filter)...")
    old_unresolved, old_waste_reproduced = old_scan_unresolved_and_waste()
    print(f"  OLD unresolved: {len(old_unresolved)} (SPEC: 1,115)")
    print(f"  OLD waste (reproduced): {len(old_waste_reproduced)} (SPEC: 994)")

    print(f"\n[2] Loading v1' waste from {NEW_CSV.name}...")
    with open(NEW_CSV) as f:
        new_ids = {r["turn_id"] for r in csv.DictReader(f)}
    print(f"  v1' waste: {len(new_ids)} (SPEC: 2,053)")

    print(f"\n[3] Loading OLD v1 waste from git {OLD_CSV_COMMIT}:{OLD_CSV_PATH}...")
    try:
        out = subprocess.check_output(
            ["git", "show", f"{OLD_CSV_COMMIT}:{OLD_CSV_PATH}"],
            cwd=str(Path(__file__).parents[2]),
        ).decode()
        old_v1_from_git = {r["turn_id"] for r in csv.DictReader(out.splitlines())}
        print(f"  old v1 waste (from git): {len(old_v1_from_git)}")
    except subprocess.CalledProcessError:
        print("  (git access failed — using reproduced set instead)")
        old_v1_from_git = old_waste_reproduced

    print("\n[4] Set arithmetic ===")
    print(f"  old_unresolved ∩ v1' waste (promoted): {len(old_unresolved & new_ids)}")
    print(f"  old_unresolved - v1' waste (missing):  {len(old_unresolved - new_ids)}")
    overlap = old_unresolved & old_v1_from_git
    print(f"  old_unresolved ∩ old_waste (overlap):  {len(overlap)}")
    if overlap:
        print("  overlap turn_ids:")
        for tid in overlap:
            print(f"    {tid}")


if __name__ == "__main__":
    main()
