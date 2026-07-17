"""Follow-up recon (task A follow-up):

Task 2: Suffix ladder matching (last 1/2/3/4 components) on the 98 text-having
        windows from the 200 sample (seed=42) used in verify_assistant_text.py.
        Also: 5 raw tool_input_json.file_path vs norm_path side-by-side.
        Also: 2-component match resolution rate for the 12 basename_ambiguous.

Task 3: Each waste candidate's OWN tool_result classification (vendor label).
        v1' 2,053 basis and v4' 858 basis. gap-bucket breakdown.
        Join method: prefer tool_call_id (if 1:1 for Read); fallback to
        (session_id, turn_number+1) adjacency. Join failures counted.

No waste/density recompute. No commits. Rule 7 부칙.
"""
import csv
import json
import os
import re
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
from huggingface_hub import hf_hub_download

REPO_ROOT = Path(__file__).parents[2]
FIELD_TEST = REPO_ROOT / "field_test"
CASES_CSV = FIELD_TEST / "swechat_waste_cases.csv"
CASES_V2_CSV = FIELD_TEST / "swechat_waste_cases_v2.csv"

LINE_PREFIX = re.compile(r'^\s*\d+→')
CACHE_MARKER = "File unchanged since last read"


def classify_read_result(content):
    if content is None:
        return "error"
    s = str(content).strip()
    if s == "":
        return "error"
    if s.startswith(CACHE_MARKER):
        return "vendor_labeled_waste"
    if LINE_PREFIX.match(s):
        return "success"
    return "error"


def try_substring(needle, hay):
    if not needle:
        return False, None
    if needle in hay:
        return True, 'as-is'
    if '\\' in needle:
        alt = needle.replace('\\', '/')
    elif '/' in needle:
        alt = needle.replace('/', '\\')
    else:
        alt = None
    if alt is not None and alt != needle and alt in hay:
        return True, 'swapped'
    return False, None


def suffix_at(norm_path, n):
    if not norm_path:
        return None
    parts = norm_path.replace('\\', '/').split('/')
    parts = [p for p in parts if p]
    if len(parts) < n:
        return None
    return '/'.join(parts[-n:])


def get_basename(p):
    return p.replace('\\', '/').rsplit('/', 1)[-1] if p else ''


def load_ctx(parquet_path, sids, extra_cols=()):
    cols = ['session_id', 'turn_number', 'turn_id', 'turn_type', 'tool_name',
            'tool_input_json', 'content', 'role'] + list(extra_cols)
    cols = list(dict.fromkeys(cols))
    dset = ds.dataset(parquet_path, format='parquet')
    tbl = dset.to_table(
        columns=cols,
        filter=ds.field('session_id').isin(sids),
    )
    df = tbl.to_pandas().drop_duplicates(subset=['turn_id']).reset_index(drop=True)
    df['turn_number'] = df.turn_number.astype(int)
    return df


def rebuild_sample_windows(parquet_path):
    """Reproduce the 200-sample seed=42 + text-having windows from prior script."""
    with open(CASES_CSV, encoding='utf-8') as f:
        cases = pd.DataFrame(list(csv.DictReader(f)))
    for c in ['turn_number', 'prev_turn_number']:
        cases[c] = cases[c].astype(int)
    sample = cases.sample(n=200, random_state=42).reset_index(drop=True)
    sids = list(sample.session_id.unique())
    ctx = load_ctx(parquet_path, sids)

    # session read targets (for ambiguous flag)
    read_use = ctx[(ctx.tool_name == 'Read') & (ctx.turn_type == 'tool_use') & ctx.tool_input_json.notna()]
    session_paths = {}
    for sid, grp in read_use.groupby('session_id'):
        paths = set()
        for tij in grp.tool_input_json:
            try:
                a = json.loads(tij)
            except Exception:
                continue
            fp = a.get('file_path') or a.get('filePath')
            if fp:
                paths.add(os.path.normpath(fp))
        session_paths[sid] = paths

    ctx_by_sess = {s: g for s, g in ctx.groupby('session_id')}
    per_window = []
    for _, case in sample.iterrows():
        sess = ctx_by_sess.get(case.session_id)
        if sess is None:
            continue
        win = sess[(sess.turn_number > case.prev_turn_number) & (sess.turn_number < case.turn_number)]
        text_rows = win[win.turn_type.isin(['assistant_response', 'assistant_thinking'])]
        text_rows_nonempty = text_rows[text_rows.content.notna() & (text_rows.content.astype(str).str.len() > 0)]
        has_text = len(text_rows_nonempty) > 0
        gap = int(case.turn_number) - int(case.prev_turn_number)
        per_window.append({
            'session_id': case.session_id,
            'turn_id': case.turn_id,
            'turn_number': int(case.turn_number),
            'prev_turn_number': int(case.prev_turn_number),
            'gap': gap,
            'has_text': has_text,
            'text_rows': text_rows_nonempty.reset_index(drop=True),
            'norm_path': case.get('norm_path', ''),
            'offset': case.get('offset', ''),
            'limit': case.get('limit', ''),
        })
    return cases, sample, ctx, session_paths, per_window


def task2_suffix_ladder(parquet_path):
    print("=" * 70)
    print("Task 2 — Suffix ladder matching (last 1/2/3/4 components)")
    print("=" * 70)
    cases, sample, ctx, session_paths, per_window = rebuild_sample_windows(parquet_path)
    text_wins = [w for w in per_window if w['has_text']]
    print(f"text-having windows: {len(text_wins)}")
    print()

    # 5 raw file_path vs norm_path
    print("=== raw tool_input_json.file_path vs norm_path (5건) ===")
    ctx_by_sess_tn = {(s, t): (t_id, tij)
                      for _, (s, t, t_id, tij) in ctx[['session_id', 'turn_number', 'turn_id', 'tool_input_json']].iterrows()}
    # Simpler: build a dict keyed by (session_id, turn_number)
    key_lookup = {}
    for _, r in ctx[(ctx.tool_name == 'Read') & (ctx.turn_type == 'tool_use') & ctx.tool_input_json.notna()].iterrows():
        key_lookup[(r.session_id, int(r.turn_number))] = r.tool_input_json
    shown = 0
    for w in text_wins:
        if shown >= 5:
            break
        tij = key_lookup.get((w['session_id'], w['turn_number']))
        if tij is None:
            continue
        try:
            a = json.loads(tij)
        except Exception:
            continue
        raw_fp = a.get('file_path') or a.get('filePath')
        print(f"  [{shown+1}] raw file_path : {raw_fp!r}")
        print(f"      norm_path     : {w['norm_path']!r}")
        shown += 1
    print()

    # Compute suffix ladder for each text-having window
    for w in text_wins:
        combined = "\n".join(str(c) for c in w['text_rows'].content)
        w['_content'] = combined
        w['_suffix'] = {}
        for lvl in [1, 2, 3, 4]:
            s = suffix_at(w['norm_path'], lvl)
            if s is None:
                w['_suffix'][lvl] = (None, False, None)
            else:
                hit, var = try_substring(s, combined)
                w['_suffix'][lvl] = (s, hit, var)

    def print_level_stats(subset, label):
        n = len(subset)
        if n == 0:
            print(f"  {label}: n=0")
            return
        if n < 10:
            print(f"  {label}: n={n} (표본 부족)")
            return
        print(f"  {label}: n={n}")
        for lvl in [1, 2, 3, 4]:
            hits = sum(1 for w in subset if w['_suffix'][lvl][1])
            na = sum(1 for w in subset if w['_suffix'][lvl][0] is None)
            print(f"    L{lvl}: {hits}/{n} = {hits/n*100:.2f}%   (N/A: {na})")

    print("=== 레벨별 매칭 창문 수 / 98 (전체 + gap 구간별) ===")
    print_level_stats(text_wins, "전체")
    for name, cond in [('gap < 20', lambda g: g < 20),
                       ('20 <= gap < 100', lambda g: 20 <= g < 100),
                       ('gap >= 100', lambda g: g >= 100)]:
        print_level_stats([w for w in text_wins if cond(w['gap'])], name)
    print()

    # basename_ambiguous 12 → L2 resolution
    ambiguous = []
    for w in text_wins:
        basename = get_basename(w['norm_path'])
        sess_paths = session_paths.get(w['session_id'], set())
        n_same = sum(1 for p in sess_paths if get_basename(p) == basename)
        if n_same > 1:
            ambiguous.append((w, n_same))
    print(f"=== basename_ambiguous 창문 (n={len(ambiguous)}) — L2 매칭 해소 여부 ===")
    l2_hits_amb = 0
    for i, (w, n_same) in enumerate(ambiguous):
        s2, hit2, var2 = w['_suffix'][2]
        print(f"  [{i+1}] session basename count={n_same}, gap={w['gap']}")
        print(f"      norm_path : {w['norm_path']!r}")
        print(f"      L2 suffix : {s2!r}")
        print(f"      L2 match  : {'yes' if hit2 else 'no'}" + (f" ({var2})" if hit2 else ""))
        if hit2:
            l2_hits_amb += 1
    if ambiguous:
        print(f"  → L2 hits in ambiguous: {l2_hits_amb}/{len(ambiguous)} = {l2_hits_amb/len(ambiguous)*100:.2f}%")
    print()


def task3_own_result(parquet_path):
    print("=" * 70)
    print("Task 3 — 후보 자신의 tool_result 분류 (외부 벤더 라벨)")
    print("=" * 70)

    # Load v1' waste cases
    with open(CASES_CSV, encoding='utf-8') as f:
        v1_cases = pd.DataFrame(list(csv.DictReader(f)))
    for c in ['turn_number', 'prev_turn_number']:
        v1_cases[c] = v1_cases[c].astype(int)
    print(f"v1' cases: {len(v1_cases)}")

    # Schema check
    dset = ds.dataset(parquet_path, format='parquet')
    col_names = [f.name for f in dset.schema]
    print(f"parquet columns: {col_names}")
    has_tcid = 'tool_call_id' in col_names
    print(f"tool_call_id present: {has_tcid}")
    print()

    # Load context for ALL v1' sessions
    sids = list(v1_cases.session_id.unique())
    extra = ['tool_call_id'] if has_tcid else ()
    ctx = load_ctx(parquet_path, sids, extra_cols=extra)
    print(f"context loaded (turn_id dedup): {len(ctx)} rows across {ctx.session_id.nunique()} sessions")

    # Verify tool_call_id 1:1 for Read
    join_method = None
    if has_tcid:
        read_rows = ctx[ctx.tool_name == 'Read']
        # Count use/result per tool_call_id
        tcid_counts = read_rows[read_rows.tool_call_id.notna()].groupby(['tool_call_id', 'turn_type']).size().unstack(fill_value=0)
        multi_use = int((tcid_counts.get('tool_use', 0) > 1).sum()) if 'tool_use' in tcid_counts.columns else 0
        multi_result = int((tcid_counts.get('tool_result', 0) > 1).sum()) if 'tool_result' in tcid_counts.columns else 0
        print(f"Read tool_call_id: use>1 tcids={multi_use}, result>1 tcids={multi_result}")
        null_tcid = read_rows.tool_call_id.isna().sum()
        print(f"Read rows with null tool_call_id: {null_tcid}")
        if multi_use == 0 and multi_result == 0 and null_tcid == 0:
            print("→ tool_call_id 1:1 confirmed. Using tool_call_id join.")
            join_method = 'tool_call_id'
        else:
            print("→ tool_call_id NOT clean 1:1. Falling back to adjacency (session_id, turn_number+1).")
            join_method = 'adjacency'
    else:
        join_method = 'adjacency'
        print("→ tool_call_id column absent. Using adjacency (session_id, turn_number+1).")
    print()

    # Build lookup: for each (session_id, turn_number) tool_use Read, find its tool_result content
    def get_own_result(sid, tn):
        sess = ctx[(ctx.session_id == sid)]
        if join_method == 'tool_call_id':
            use_row = sess[(sess.turn_number == tn) & (sess.turn_type == 'tool_use') & (sess.tool_name == 'Read')]
            if use_row.empty:
                return None, 'no_use_row'
            tcid = use_row.iloc[0].tool_call_id
            if pd.isna(tcid) or tcid is None:
                return None, 'null_tcid'
            res = sess[(sess.tool_call_id == tcid) & (sess.turn_type == 'tool_result')]
            if res.empty:
                return None, 'no_result'
            return res.iloc[0].content, None
        else:
            res = sess[(sess.turn_number == tn + 1) & (sess.turn_type == 'tool_result') & (sess.tool_name == 'Read')]
            if res.empty:
                return None, 'no_result'
            return res.iloc[0].content, None

    # Pre-index ctx for speed
    ctx_by_sess = {s: g for s, g in ctx.groupby('session_id')}
    if has_tcid and join_method == 'tool_call_id':
        use_lookup = {}
        for _, r in ctx[(ctx.tool_name == 'Read') & (ctx.turn_type == 'tool_use')].iterrows():
            use_lookup[(r.session_id, int(r.turn_number))] = r.tool_call_id
        result_lookup = {}
        for _, r in ctx[(ctx.turn_type == 'tool_result')].iterrows():
            if pd.notna(r.tool_call_id):
                result_lookup[r.tool_call_id] = r.content

    def classify_case(sid, tn):
        if join_method == 'tool_call_id':
            tcid = use_lookup.get((sid, tn))
            if tcid is None or pd.isna(tcid):
                return 'join_fail_no_tcid'
            content = result_lookup.get(tcid)
            if content is None:
                return 'join_fail_no_result'
        else:
            sess = ctx_by_sess.get(sid)
            if sess is None:
                return 'join_fail_no_session'
            res = sess[(sess.turn_number == tn + 1) & (sess.turn_type == 'tool_result') & (sess.tool_name == 'Read')]
            if res.empty:
                return 'join_fail_no_adjacent'
            content = res.iloc[0].content
        return classify_read_result(content)

    # v1' 2053 breakdown
    print("=== v1' 2,053 후보 자신의 tool_result 분류 ===")
    stats_v1 = Counter()
    v1_case_class = {}
    for _, case in v1_cases.iterrows():
        cls = classify_case(case.session_id, int(case.turn_number))
        stats_v1[cls] += 1
        v1_case_class[case.turn_id] = cls
    total = len(v1_cases)
    for k, v in stats_v1.most_common():
        print(f"  {k}: {v} / {total} = {v/total*100:.3f}%")
    vlw_v1 = stats_v1.get('vendor_labeled_waste', 0)
    print(f"  → vendor_labeled_waste (v1'): {vlw_v1} / {total} = {vlw_v1/total*100:.3f}%")
    print()

    # gap 구간별
    print("=== v1' 2,053 gap 구간별 vendor_labeled_waste ===")
    v1_cases['gap'] = v1_cases.turn_number - v1_cases.prev_turn_number
    for name, cond in [('gap < 20', lambda g: g < 20),
                       ('20 <= gap < 100', lambda g: 20 <= g < 100),
                       ('gap >= 100', lambda g: g >= 100)]:
        sub = v1_cases[v1_cases.gap.apply(cond)]
        n = len(sub)
        if n == 0:
            print(f"  {name}: n=0")
            continue
        vlw = sum(1 for _, c in sub.iterrows() if v1_case_class.get(c.turn_id) == 'vendor_labeled_waste')
        if n < 10:
            print(f"  {name}: n={n} (표본 부족)")
        else:
            print(f"  {name}: n={n}, vendor_labeled_waste {vlw}/{n} = {vlw/n*100:.3f}%")
    print()

    # v4' 858 derivation: from v2'/v3' 1272 basis, filter by between-Read all_success
    print("=== v4' 858 derivation (v3' compact/agent 필터 후 all_success) ===")
    if not CASES_V2_CSV.exists():
        print(f"  ! {CASES_V2_CSV} not found. v4' derivation skipped.")
        return
    with open(CASES_V2_CSV, encoding='utf-8') as f:
        v3_cases = pd.DataFrame(list(csv.DictReader(f)))
    for c in ['turn_number', 'prev_turn_number']:
        v3_cases[c] = v3_cases[c].astype(int)
    # v3 filter (gap > 0)
    v3_cases = v3_cases[v3_cases.turn_number != v3_cases.prev_turn_number].reset_index(drop=True)
    print(f"  v3' cases (after gap>0 filter from v2 CSV): {len(v3_cases)}")

    # Classify between-Reads to derive v4' (all_success)
    def between_kinds(sid, ptn, tn):
        sess = ctx_by_sess.get(sid)
        if sess is None:
            return []
        win = sess[(sess.turn_number > ptn) & (sess.turn_number < tn)]
        rr = win[(win.role == 'tool_result') & (win.tool_name == 'Read')]
        return [classify_read_result(r.content) for _, r in rr.iterrows()]

    v4_ids = []
    for _, case in v3_cases.iterrows():
        kinds = between_kinds(case.session_id, int(case.prev_turn_number), int(case.turn_number))
        if 'vendor_labeled_waste' in kinds:
            continue
        elif 'success' in kinds:
            v4_ids.append(case.turn_id)
        else:
            continue
    print(f"  v4' derived (all_success within v3'): {len(v4_ids)}  (SPEC 표: 858)")

    # v4' own-result breakdown
    v4_set = set(v4_ids)
    v4_case_rows = v3_cases[v3_cases.turn_id.isin(v4_set)]
    stats_v4 = Counter()
    v4_case_class = {}
    for _, case in v4_case_rows.iterrows():
        cls = classify_case(case.session_id, int(case.turn_number))
        stats_v4[cls] += 1
        v4_case_class[case.turn_id] = cls
    total4 = len(v4_case_rows)
    print(f"\n=== v4' 858 후보 자신의 tool_result 분류 ===")
    for k, v in stats_v4.most_common():
        print(f"  {k}: {v} / {total4} = {v/total4*100:.3f}%")
    vlw_v4 = stats_v4.get('vendor_labeled_waste', 0)
    print(f"  → vendor_labeled_waste (v4'): {vlw_v4} / {total4} = {vlw_v4/total4*100:.3f}%")
    print()

    # gap breakdown for v4'
    print("=== v4' gap 구간별 vendor_labeled_waste ===")
    v4_case_rows = v4_case_rows.copy()
    v4_case_rows['gap'] = v4_case_rows.turn_number - v4_case_rows.prev_turn_number
    for name, cond in [('gap < 20', lambda g: g < 20),
                       ('20 <= gap < 100', lambda g: 20 <= g < 100),
                       ('gap >= 100', lambda g: g >= 100)]:
        sub = v4_case_rows[v4_case_rows.gap.apply(cond)]
        n = len(sub)
        if n == 0:
            print(f"  {name}: n=0")
            continue
        vlw = sum(1 for _, c in sub.iterrows() if v4_case_class.get(c.turn_id) == 'vendor_labeled_waste')
        if n < 10:
            print(f"  {name}: n={n} (표본 부족)")
        else:
            print(f"  {name}: n={n}, vendor_labeled_waste {vlw}/{n} = {vlw/n*100:.3f}%")


def main():
    t0 = time.time()
    parquet_path = hf_hub_download('SALT-NLP/SWE-chat', 'conversations.parquet', repo_type='dataset')
    print(f"parquet: {parquet_path}")
    print()
    task2_suffix_ladder(parquet_path)
    task3_own_result(parquet_path)
    dt = time.time() - t0
    print(f"\nwall time: {dt:.1f}s")


if __name__ == "__main__":
    main()
