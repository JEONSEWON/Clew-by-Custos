"""One-off diagnostic — verifies the SPEC/정직 경계 claim:

    "데이터셋에 assistant 텍스트 턴 없음 → '왜 다시 읽었나' 판정 불가
     → v1~v4' 모두 '후보'이지 확정 낭비 아님"

This claim was never empirically checked. recon_bash.py raw shows
turn_type value_counts includes 'assistant_response' 41,622 and
'assistant_thinking' 11,954 (role='assistant' 53,576 total). If those
rows are non-empty and land inside our v1' waste windows, the SPEC claim
above is on the same failure category as the EDIT_TOOLS contamination
found on 2026-07-16.

Reconnaissance only. No waste/density recomputation. No SPEC edits.

Rule 7 부칙: keep this script under field_test/diagnostics/ after fold-back.
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

LINE_PREFIX = re.compile(r'^\s*\d+→')
CACHE_MARKER = "File unchanged since last read"


def classify_read_result(content):
    if content is None:
        return "error"
    s = str(content).strip()
    if s == "":
        return "error"
    if s.startswith(CACHE_MARKER):
        return "cache_hit"
    if LINE_PREFIX.match(s):
        return "success"
    return "error"


def get_basename(p):
    return p.replace('\\', '/').rsplit('/', 1)[-1] if p else ''


def try_substring(needle, hay):
    """Return (hit, variant) — try as-is, then swap slash direction."""
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


def q1(parquet_path):
    print("=" * 70)
    print("Q1 — agent × turn_type crosstab (전수)")
    print("=" * 70)
    dset = ds.dataset(parquet_path, format='parquet')
    tbl = dset.to_table(columns=['agent', 'turn_type'])
    df = tbl.to_pandas()
    ct = df.groupby(['agent', 'turn_type'], dropna=False).size().unstack(fill_value=0)
    print(ct.to_string())
    print()
    cc_assistant = 0
    if 'Claude Code' in ct.index:
        for tt in ['assistant_response', 'assistant_thinking']:
            if tt in ct.columns:
                n = int(ct.loc['Claude Code', tt])
                print(f"  Claude Code × {tt}: {n}")
                cc_assistant += n
    print(f"  Claude Code × assistant_* total: {cc_assistant}")
    print()
    return cc_assistant


def q2(parquet_path):
    print("=" * 70)
    print("Q2 — content 채움률 (Claude Code × assistant_*)")
    print("=" * 70)
    dset = ds.dataset(parquet_path, format='parquet')
    filt = (ds.field('agent') == 'Claude Code') & \
           (ds.field('turn_type').isin(['assistant_response', 'assistant_thinking']))
    tbl = dset.to_table(columns=['turn_type', 'content'], filter=filt)
    df = tbl.to_pandas()
    df['non_empty'] = df.content.notna() & (df.content.astype(str).str.len() > 0)
    df['char_count'] = df.content.astype(str).where(df.non_empty).str.len()
    for tt in ['assistant_response', 'assistant_thinking']:
        sub = df[df.turn_type == tt]
        if len(sub) == 0:
            print(f"  {tt}: 0 rows")
            continue
        pct = sub.non_empty.mean() * 100
        print(f"  {tt}: n={len(sub)}, non_empty={sub.non_empty.sum()} ({pct:.2f}%)")
        cc = sub.char_count.dropna()
        if len(cc):
            print(f"    char_count: min={cc.min():.0f} p25={cc.quantile(0.25):.0f} median={cc.median():.0f} p75={cc.quantile(0.75):.0f} mean={cc.mean():.1f} max={cc.max():.0f}")
    print()


def load_ctx(parquet_path, sids):
    dset = ds.dataset(parquet_path, format='parquet')
    filt = ds.field('session_id').isin(sids)
    tbl = dset.to_table(
        columns=['session_id', 'turn_number', 'turn_id', 'turn_type', 'tool_name',
                 'tool_input_json', 'content', 'role'],
        filter=filt,
    )
    df = tbl.to_pandas().drop_duplicates(subset=['turn_id']).reset_index(drop=True)
    df['turn_number'] = df.turn_number.astype(int)
    return df


def session_read_targets(ctx):
    """Extract set of Read tool_use norm_paths per session_id."""
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
    return session_paths


def q3(parquet_path):
    print("=" * 70)
    print("Q3 — 우리 후보 창문 안에 assistant 텍스트가 있나 (200 표본, seed=42)")
    print("=" * 70)
    with open(CASES_CSV, encoding='utf-8') as f:
        cases = pd.DataFrame(list(csv.DictReader(f)))
    for c in ['turn_number', 'prev_turn_number']:
        cases[c] = cases[c].astype(int)
    print(f"v1' waste cases loaded: {len(cases)}")
    sample = cases.sample(n=200, random_state=42).reset_index(drop=True)
    print(f"sample n=200 (seed=42), unique sessions: {sample.session_id.nunique()}")
    print()

    sids = list(sample.session_id.unique())
    ctx = load_ctx(parquet_path, sids)
    print(f"context loaded (turn_id dedup): {len(ctx)} rows across {ctx.session_id.nunique()} sessions")
    print()

    session_paths = session_read_targets(ctx)
    ctx_by_sess = {s: g for s, g in ctx.groupby('session_id')}

    all_turn_types = Counter()
    per_window = []
    for _, case in sample.iterrows():
        sess = ctx_by_sess.get(case.session_id)
        if sess is None:
            continue
        win = sess[(sess.turn_number > case.prev_turn_number) & (sess.turn_number < case.turn_number)]
        for tt in win.turn_type:
            all_turn_types[tt] += 1
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

    print("3a. turn_type 분포 (200 창문 합산):")
    for tt, n in all_turn_types.most_common():
        print(f"  {tt}: {n}")
    print()

    n_with_text = sum(1 for w in per_window if w['has_text'])
    print(f"3b. assistant 텍스트 있는 창문: {n_with_text} / {len(per_window)} = {n_with_text/len(per_window)*100:.2f}%")
    print()

    char_counts = []
    for w in per_window:
        if w['has_text']:
            for c in w['text_rows'].content:
                char_counts.append(len(str(c)))
    if char_counts:
        s = pd.Series(char_counts)
        print(f"3c. assistant 텍스트 char_count (n={len(char_counts)}):")
        print(f"  min={s.min()} p25={s.quantile(0.25):.0f} median={s.median():.0f} p75={s.quantile(0.75):.0f} mean={s.mean():.1f} max={s.max()}")
    print()

    print("3d. gap 구간별 분해 (200 표본 전체):")
    for name, cond in [('gap < 20', lambda g: g < 20),
                       ('20 <= gap < 100', lambda g: 20 <= g < 100),
                       ('gap >= 100', lambda g: g >= 100)]:
        sub = [w for w in per_window if cond(w['gap'])]
        n = len(sub)
        if n < 10:
            print(f"  {name}: n={n} (표본 부족)")
        else:
            k = sum(1 for w in sub if w['has_text'])
            print(f"  {name}: n={n}, 텍스트 있는 창문 {k} / {n} = {k/n*100:.2f}%")
    print()

    return per_window, session_paths


def q4(per_window, session_paths):
    print("=" * 70)
    print("Q4 — 텍스트 있는 창문 dump (seed=42) + 200 매칭 집계")
    print("=" * 70)
    text_wins = [w for w in per_window if w['has_text']]
    print(f"텍스트 있는 창문: {len(text_wins)}")
    if len(text_wins) == 0:
        print("  → Q4 skip")
        return

    n_dump = min(10, len(text_wins))
    rng = np.random.default_rng(42)
    idxs = sorted(rng.choice(len(text_wins), size=n_dump, replace=False).tolist())

    for i, ix in enumerate(idxs):
        w = text_wins[ix]
        print(f"--- case {i+1}/{n_dump} ---")
        print(f"  session_id: {w['session_id']}")
        print(f"  turn_id: {w['turn_id']}")
        print(f"  gap: {w['gap']}")
        print(f"  norm_path: {w['norm_path']!r}")
        print(f"  offset: {w['offset']!r}")
        print(f"  limit: {w['limit']!r}")
        combined = "\n".join(str(c) for c in w['text_rows'].content)
        preview = combined[:300].replace('\n', '\\n').replace('\r', '\\r')
        print(f"  content [{len(combined)} chars] preview: {preview}")
        basename = get_basename(w['norm_path'])
        full_hit, full_var = try_substring(w['norm_path'], combined)
        base_hit, base_var = try_substring(basename, combined)
        sess_paths = session_paths.get(w['session_id'], set())
        n_same_base = sum(1 for p in sess_paths if get_basename(p) == basename)
        base_amb = n_same_base > 1
        print(f"  match_full     : {'yes' if full_hit else 'no'}" + (f" ({full_var})" if full_hit else ""))
        print(f"  match_basename : {'yes' if base_hit else 'no'}" + (f" ({base_var})" if base_hit else ""))
        print(f"  basename_ambiguous: {'yes' if base_amb else 'no'}  (session basename count={n_same_base})")
        print()

    # 200-sample aggregate
    print("=== 200 표본 집계 (텍스트 있는 창문 한정) ===")
    evals = []
    for w in text_wins:
        combined = "\n".join(str(c) for c in w['text_rows'].content)
        basename = get_basename(w['norm_path'])
        full_hit, _ = try_substring(w['norm_path'], combined)
        base_hit, _ = try_substring(basename, combined)
        sess_paths = session_paths.get(w['session_id'], set())
        base_amb = sum(1 for p in sess_paths if get_basename(p) == basename) > 1
        evals.append({
            'gap': w['gap'],
            'full': full_hit,
            'base': base_hit,
            'base_only': (base_hit and not full_hit),
            'amb': base_amb,
        })

    def stats(subset, label):
        n = len(subset)
        if n < 10:
            print(f"  {label}: n={n} (표본 부족)")
            return
        full = sum(1 for e in subset if e['full'])
        base = sum(1 for e in subset if e['base'])
        base_only = sum(1 for e in subset if e['base_only'])
        amb = sum(1 for e in subset if e['amb'])
        print(f"  {label}: n={n}")
        print(f"    match_full         {full}/{n} = {full/n*100:.2f}%")
        print(f"    match_basename     {base}/{n} = {base/n*100:.2f}%")
        print(f"    basename-only      {base_only}/{n} = {base_only/n*100:.2f}%")
        print(f"    basename_ambiguous {amb}/{n} = {amb/n*100:.2f}%")

    stats(evals, "전체")
    for name, cond in [('gap < 20', lambda g: g < 20),
                       ('20 <= gap < 100', lambda g: 20 <= g < 100),
                       ('gap >= 100', lambda g: g >= 100)]:
        stats([e for e in evals if cond(e['gap'])], name)
    print()


def q5(parquet_path):
    print("=" * 70)
    print("Q5 — 벤더 라벨 (File unchanged since last read) count")
    print("=" * 70)
    with open(CASES_CSV, encoding='utf-8') as f:
        cases = pd.DataFrame(list(csv.DictReader(f)))
    for c in ['turn_number', 'prev_turn_number']:
        cases[c] = cases[c].astype(int)
    print(f"v1' waste cases: {len(cases)}")

    sids = list(cases.session_id.unique())
    dset = ds.dataset(parquet_path, format='parquet')
    filt = ds.field('session_id').isin(sids)
    tbl = dset.to_table(
        columns=['session_id', 'turn_number', 'turn_id', 'role', 'tool_name', 'content'],
        filter=filt,
    )
    df = tbl.to_pandas().drop_duplicates(subset=['turn_id']).reset_index(drop=True)
    df['turn_number'] = df.turn_number.astype(int)
    ctx_by_sess = {s: g for s, g in df.groupby('session_id')}

    v1_cache_hit = 0
    v1_all_success = 0
    v1_all_error = 0
    v1_no_read = 0
    v4_ids = set()
    v1_cache_hit_ids = set()

    for _, case in cases.iterrows():
        sess = ctx_by_sess.get(case.session_id)
        if sess is None:
            continue
        win = sess[(sess.turn_number > case.prev_turn_number) & (sess.turn_number < case.turn_number)]
        read_results = win[(win.role == 'tool_result') & (win.tool_name == 'Read')]
        if len(read_results) == 0:
            v1_no_read += 1
            continue
        kinds = [classify_read_result(r.content) for _, r in read_results.iterrows()]
        if 'cache_hit' in kinds:
            v1_cache_hit += 1
            v1_cache_hit_ids.add(case.turn_id)
        elif 'success' in kinds:
            v1_all_success += 1
            v4_ids.add(case.turn_id)
        else:
            v1_all_error += 1

    total = len(cases)
    print(f"v1' 2,053 창문별 분류:")
    print(f"  cache_hit (사이 Read 중 1건이라도 'File unchanged'): {v1_cache_hit} / {total} = {v1_cache_hit/total*100:.3f}%")
    print(f"  all_success (v4' 후보): {v1_all_success}")
    print(f"  all_error: {v1_all_error}")
    print(f"  no_read_result: {v1_no_read}")
    print()
    print(f"v4' (=all_success) 집합 크기: {len(v4_ids)}  (SPEC 표: 858)")
    print(f"v4' 내 cache_hit: 0 (all_success 정의상 cache_hit 없음)")
    print()


def main():
    t0 = time.time()
    print("=" * 70)
    print("verify_assistant_text.py — reconnaissance (no waste recompute)")
    print("=" * 70)
    parquet_path = hf_hub_download('SALT-NLP/SWE-chat', 'conversations.parquet', repo_type='dataset')
    print(f"parquet: {parquet_path}")
    print()

    cc_assistant = q1(parquet_path)
    if cc_assistant == 0:
        print("STOP — Claude Code × assistant_* == 0. Remaining Q skipped.")
        return

    q2(parquet_path)
    per_window, session_paths = q3(parquet_path)
    q4(per_window, session_paths)
    q5(parquet_path)

    dt = time.time() - t0
    print(f"wall time: {dt:.1f}s")


if __name__ == "__main__":
    main()
