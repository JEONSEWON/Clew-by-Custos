"""A-followup 2 — 4 tasks (recon only, no commit, no density recompute).

Task 1: tool_call_id join 복구 + adjacency 교차검증.
Task 2: v4' vendor_labeled_waste = 0 증명/반증 (파이프라인 필터별 분해).
Task 3: word-boundary 매칭 (regex, substring과 병기).
Task 4: os.path.normpath / is_abs OS 의존성 진단 (raw 사실만).

이전 스크립트 사양 재확인 (compact 후):
- rebuild_sample_windows: 200-sample seed=42, 창 개구간, non-empty
  assistant text — L1=23/98 = 23.47%가 이전 실행과 일치 → 정합성 OK.
- 이전 스크립트 has_tcid=True인데도 use>1/result>1 tcids=49로 adjacency 폴백
  → 이번 스크립트는 49 tcids만 별도 집계·제외하고 나머지는 tcid로 조인.
"""
import csv
import json
import ntpath
import os
import posixpath
import re
import time
from collections import Counter
from pathlib import Path

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


def classify_for_v4(content):
    """v4_reclassify.py:29-39 사양 그대로 (cache_hit / success / error)."""
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


def load_ctx(parquet_path, sids):
    cols = ['session_id', 'turn_number', 'turn_id', 'turn_type', 'tool_name',
            'tool_input_json', 'content', 'role', 'tool_call_id']
    dset = ds.dataset(parquet_path, format='parquet')
    tbl = dset.to_table(
        columns=cols,
        filter=ds.field('session_id').isin(sids),
    )
    df = tbl.to_pandas().drop_duplicates(subset=['turn_id']).reset_index(drop=True)
    df['turn_number'] = df.turn_number.astype(int)
    return df


# ============================================================
# Task 1
# ============================================================
def task1_join_fix(parquet_path):
    print("=" * 70)
    print("Task 1 — tool_call_id join 복구 + adjacency 교차검증")
    print("=" * 70)

    with open(CASES_CSV, encoding='utf-8') as f:
        v1_cases = pd.DataFrame(list(csv.DictReader(f)))
    for c in ['turn_number', 'prev_turn_number']:
        v1_cases[c] = v1_cases[c].astype(int)

    sids = list(v1_cases.session_id.unique())
    ctx = load_ctx(parquet_path, sids)
    print(f"v1' cases: {len(v1_cases)} / sessions: {len(sids)} / ctx rows: {len(ctx)}")

    # ---- Read tool_call_id 중복 집계 ----
    read_rows = ctx[ctx.tool_name == 'Read']
    tcid_notna = read_rows[read_rows.tool_call_id.notna()]
    tcid_counts = tcid_notna.groupby(['tool_call_id', 'turn_type']).size().unstack(fill_value=0)
    multi_use_tcids = set(tcid_counts[tcid_counts.get('tool_use', 0) > 1].index) if 'tool_use' in tcid_counts.columns else set()
    multi_result_tcids = set(tcid_counts[tcid_counts.get('tool_result', 0) > 1].index) if 'tool_result' in tcid_counts.columns else set()
    dup_tcids = multi_use_tcids | multi_result_tcids
    read_null_tcid = int(read_rows.tool_call_id.isna().sum())
    print()
    print(f"Read rows total: {len(read_rows)}")
    print(f"Read rows with null tool_call_id: {read_null_tcid}")
    print(f"unique Read tool_call_ids: {tcid_notna.tool_call_id.nunique()}")
    print(f"tcid with use>1 : {len(multi_use_tcids)}")
    print(f"tcid with result>1 : {len(multi_result_tcids)}")
    print(f"union dup_tcids : {len(dup_tcids)}")

    # ---- 후보의 tool_use 행 → tcid 매핑 ----
    use_key = {}
    for _, r in ctx[(ctx.tool_name == 'Read') & (ctx.turn_type == 'tool_use')].iterrows():
        use_key[(r.session_id, int(r.turn_number))] = r.tool_call_id

    v1_tcid_map = {}
    v1_no_tcid_row = 0
    v1_null_tcid = 0
    v1_in_dup = 0
    for _, case in v1_cases.iterrows():
        key = (case.session_id, int(case.turn_number))
        if key not in use_key:
            v1_no_tcid_row += 1
            v1_tcid_map[case.turn_id] = None
            continue
        tcid = use_key[key]
        if pd.isna(tcid):
            v1_null_tcid += 1
            v1_tcid_map[case.turn_id] = None
            continue
        v1_tcid_map[case.turn_id] = tcid
        if tcid in dup_tcids:
            v1_in_dup += 1
    print()
    print(f"후보 tool_use 행 자체 없음: {v1_no_tcid_row}")
    print(f"후보 tcid null: {v1_null_tcid}")
    print(f"후보 중 dup_tcid 매치 (본 조인 제외): {v1_in_dup}")

    # ---- tool_result 행 → tcid 사전 (dup 제외) ----
    result_rows = ctx[ctx.turn_type == 'tool_result']
    result_by_tcid = {}
    result_tcid_stats = Counter()
    for _, r in result_rows.iterrows():
        if pd.isna(r.tool_call_id):
            result_tcid_stats['null_tcid'] += 1
            continue
        if r.tool_call_id in dup_tcids:
            result_tcid_stats['dup_tcid'] += 1
            continue
        if r.tool_call_id in result_by_tcid:
            result_tcid_stats['already_seen'] += 1
            continue
        result_by_tcid[r.tool_call_id] = r.content
        result_tcid_stats['indexed'] += 1
    print()
    print(f"tool_result 인덱싱: {dict(result_tcid_stats)}")

    # ---- tcid join 분류 ----
    print()
    print("=== v1' 2,053 — tool_call_id 조인 분류 ===")
    tcid_class = {}
    tcid_stats = Counter()
    for _, case in v1_cases.iterrows():
        tid = case.turn_id
        tcid = v1_tcid_map.get(tid)
        if tcid is None:
            tcid_stats['join_fail_no_tcid'] += 1
            tcid_class[tid] = 'join_fail_no_tcid'
            continue
        if tcid in dup_tcids:
            tcid_stats['excluded_dup_tcid'] += 1
            tcid_class[tid] = 'excluded_dup_tcid'
            continue
        content = result_by_tcid.get(tcid)
        if content is None:
            tcid_stats['join_fail_no_result'] += 1
            tcid_class[tid] = 'join_fail_no_result'
            continue
        cls = classify_read_result(content)
        tcid_stats[cls] += 1
        tcid_class[tid] = cls
    total = len(v1_cases)
    for k, v in tcid_stats.most_common():
        print(f"  {k}: {v} / {total} = {v/total*100:.3f}%")
    join_ok = sum(v for k, v in tcid_stats.items()
                  if k not in ('join_fail_no_tcid', 'join_fail_no_result', 'excluded_dup_tcid'))
    vlw_tcid = tcid_stats.get('vendor_labeled_waste', 0)
    print(f"  → 조인 성공 분모: {join_ok}")
    print(f"  → vendor_labeled_waste (v1', tcid): {vlw_tcid} / {join_ok} = {vlw_tcid/max(join_ok,1)*100:.3f}%")

    # ---- adjacency 병기 (동일 데이터) ----
    ctx_by_sess = {s: g for s, g in ctx.groupby('session_id')}
    adj_class = {}
    adj_stats = Counter()
    adj_adj_row = {}  # turn_id → adjacent tool_result row (for cross-check)
    for _, case in v1_cases.iterrows():
        sess = ctx_by_sess.get(case.session_id)
        if sess is None:
            adj_stats['join_fail_no_session'] += 1
            adj_class[case.turn_id] = 'join_fail_no_session'
            continue
        tn = int(case.turn_number)
        res = sess[(sess.turn_number == tn + 1)
                   & (sess.turn_type == 'tool_result')
                   & (sess.tool_name == 'Read')]
        if res.empty:
            adj_stats['join_fail_no_adjacent'] += 1
            adj_class[case.turn_id] = 'join_fail_no_adjacent'
            continue
        row = res.iloc[0]
        adj_adj_row[case.turn_id] = row
        cls = classify_read_result(row.content)
        adj_stats[cls] += 1
        adj_class[case.turn_id] = cls
    print()
    print("=== v1' 2,053 — adjacency (병기용 재실행) ===")
    for k, v in adj_stats.most_common():
        print(f"  {k}: {v} / {total} = {v/total*100:.3f}%")

    # ---- 교차검증: adjacency hit의 인접 행 tcid == 후보 tcid ----
    print()
    print("=== 교차검증: adjacency로 잡힌 인접 행의 tcid == 후보 tcid ===")
    adj_hits = [tid for tid, cls in adj_class.items()
                if cls in ('success', 'error', 'vendor_labeled_waste')]
    both_null = 0
    match = 0
    mismatch = 0
    cand_null = 0
    adj_null = 0
    for tid in adj_hits:
        adj_row = adj_adj_row.get(tid)
        if adj_row is None:
            continue
        adj_tcid = adj_row.tool_call_id
        cand_tcid = v1_tcid_map.get(tid)
        if pd.isna(adj_tcid) and (cand_tcid is None or pd.isna(cand_tcid)):
            both_null += 1
            continue
        if cand_tcid is None or pd.isna(cand_tcid):
            cand_null += 1
            continue
        if pd.isna(adj_tcid):
            adj_null += 1
            continue
        if adj_tcid == cand_tcid:
            match += 1
        else:
            mismatch += 1
    print(f"  adjacency hits (success/error/vlw): {len(adj_hits)}")
    print(f"    tcid match          : {match}")
    print(f"    tcid mismatch (오탐): {mismatch}")
    print(f"    both null           : {both_null}")
    print(f"    cand tcid null only : {cand_null}")
    print(f"    adj tcid null only  : {adj_null}")
    print(f"  → adjacency 오탐 비율: {mismatch}/{len(adj_hits)} = "
          f"{mismatch/max(len(adj_hits),1)*100:.3f}%")

    # ---- 클래스별 병기 표 ----
    print()
    print("=== 요약 표: adjacency vs tool_call_id ===")
    keys = sorted(set(adj_stats.keys()) | set(tcid_stats.keys()))
    print(f"  {'class':<28} {'adj':>8} {'tcid':>8}")
    for k in keys:
        print(f"  {k:<28} {adj_stats.get(k, 0):>8} {tcid_stats.get(k, 0):>8}")

    # ---- gap 구간별 (tcid) ----
    print()
    print("=== v1' gap 구간별 vendor_labeled_waste (tcid join) ===")
    v1_cases['gap'] = v1_cases.turn_number - v1_cases.prev_turn_number
    for name, cond in [('gap < 20', lambda g: g < 20),
                       ('20 <= gap < 100', lambda g: 20 <= g < 100),
                       ('gap >= 100', lambda g: g >= 100)]:
        sub = v1_cases[v1_cases.gap.apply(cond)]
        n = len(sub)
        vlw = sum(1 for _, c in sub.iterrows() if tcid_class.get(c.turn_id) == 'vendor_labeled_waste')
        print(f"  {name}: n={n}, vlw={vlw}/{n} = {vlw/max(n,1)*100:.3f}%")

    return {
        'v1_cases': v1_cases,
        'ctx': ctx,
        'ctx_by_sess': ctx_by_sess,
        'tcid_class': tcid_class,
        'adj_class': adj_class,
        'v1_tcid_map': v1_tcid_map,
        'use_key': use_key,
        'result_by_tcid': result_by_tcid,
        'dup_tcids': dup_tcids,
    }


# ============================================================
# Task 2
# ============================================================
def task2_v4_proof(state):
    print()
    print("=" * 70)
    print("Task 2 — v4' vendor_labeled_waste = 0 증명/반증")
    print("=" * 70)

    # 코드 인용
    print("=== v4_reclassify.py:69-91 인용 (사이 Read 구간 정의) ===")
    v4_code = FIELD_TEST / "v4_reclassify.py"
    with open(v4_code, encoding='utf-8') as f:
        lines = f.readlines()
    for i in range(68, 92):
        print(f"  {i+1:>3}: {lines[i].rstrip()}")
    print()
    print("  → between = 개구간 (sess.turn_number > ptn AND < tn)")
    print("  → 후보 자신의 turn_number 및 그 tool_result(tn+1) 모두 제외")
    print("  → 우선순위: cache_hit > success > error (v4 = all_success만 통과)")

    # v2/v3 CSV 로드
    with open(CASES_V2_CSV, encoding='utf-8') as f:
        v2_cases = pd.DataFrame(list(csv.DictReader(f)))
    for c in ['turn_number', 'prev_turn_number']:
        v2_cases[c] = v2_cases[c].astype(int)
    v2_ids = set(v2_cases.turn_id)
    v3_mask = v2_cases.turn_number != v2_cases.prev_turn_number
    v3_ids = set(v2_cases[v3_mask].turn_id)

    v1_cases = state['v1_cases']
    ctx_by_sess = state['ctx_by_sess']
    tcid_class = state['tcid_class']

    print()
    print(f"v1' rows: {len(v1_cases)}")
    print(f"v2 rows (compact/agent 필터 후): {len(v2_cases)}")
    print(f"v3 rows (v2 gap>0): {int(v3_mask.sum())}")
    print(f"v1' - v2 (compact/agent 손실): {len(v1_cases) - len(v2_cases)}")

    # v1' vendor_labeled_waste 목록 (tcid 기준)
    vlw_ids = [tid for tid, cls in tcid_class.items() if cls == 'vendor_labeled_waste']
    print(f"v1' vendor_labeled_waste (tcid): {len(vlw_ids)}")

    # 파이프라인 필터별 분해
    def between_kinds(sid, ptn, tn):
        sess = ctx_by_sess.get(sid)
        if sess is None:
            return None
        win = sess[(sess.turn_number > ptn) & (sess.turn_number < tn)]
        rr = win[(win.role == 'tool_result') & (win.tool_name == 'Read')]
        return [classify_for_v4(r.content) for _, r in rr.iterrows()]

    v1_by_id = {r.turn_id: r for _, r in v1_cases.iterrows()}
    bucket = Counter()
    survives_ids = []
    for tid in vlw_ids:
        row = v1_by_id[tid]
        # 1) compact/agent
        if tid not in v2_ids:
            bucket['dropped_compact_agent'] += 1
            continue
        # 2) gap==0
        if int(row.turn_number) == int(row.prev_turn_number):
            bucket['dropped_gap_zero'] += 1
            continue
        # 3) between-Read 분류
        kinds = between_kinds(row.session_id, int(row.prev_turn_number), int(row.turn_number))
        if kinds is None:
            bucket['dropped_no_session'] += 1
            continue
        if len(kinds) == 0:
            bucket['dropped_no_read_result'] += 1
            continue
        if 'cache_hit' in kinds:
            bucket['dropped_has_cache_hit'] += 1
            continue
        elif 'success' in kinds:
            bucket['survives_to_v4'] += 1
            survives_ids.append(tid)
            continue
        else:
            bucket['dropped_all_error'] += 1

    print()
    print("=== v1' vendor_labeled_waste 의 v1'→v4' 필터 통과 ===")
    ordered = ['dropped_compact_agent', 'dropped_gap_zero', 'dropped_no_session',
               'dropped_no_read_result', 'dropped_has_cache_hit',
               'dropped_all_error', 'survives_to_v4']
    for k in ordered:
        v = bucket.get(k, 0)
        print(f"  {k}: {v}")
    print(f"  합계: {sum(bucket.values())} (=v1' vlw {len(vlw_ids)})")

    survives = bucket.get('survives_to_v4', 0)
    print()
    if survives == 0:
        print(f"  → 살아남는 후보 없음.")
        print(f"    v4' vendor_labeled_waste = 0 은 파이프라인 필터로 완전히 설명됨.")
        print(f"    (증명: 위 카운트 합이 v1' vlw 총수와 일치, survives_to_v4 = 0)")
    else:
        print(f"  → survives_to_v4 = {survives} > 0 이지만")
        print(f"    v4' 자체결과 분류에서 vendor_labeled_waste = 0.")
        print(f"    survives ids (최대 5개): {survives_ids[:5]}")
        print(f"    → v4' 자체결과 분류는 미해결 (survives들의 own_result가 왜 cache가 아닌지 별도 확인 필요).")


# ============================================================
# Task 3
# ============================================================
def rebuild_text_windows(parquet_path):
    with open(CASES_CSV, encoding='utf-8') as f:
        cases = pd.DataFrame(list(csv.DictReader(f)))
    for c in ['turn_number', 'prev_turn_number']:
        cases[c] = cases[c].astype(int)
    sample = cases.sample(n=200, random_state=42).reset_index(drop=True)
    sids = list(sample.session_id.unique())
    ctx = load_ctx(parquet_path, sids)
    ctx_by_sess = {s: g for s, g in ctx.groupby('session_id')}

    text_wins = []
    for _, case in sample.iterrows():
        sess = ctx_by_sess.get(case.session_id)
        if sess is None:
            continue
        win = sess[(sess.turn_number > case.prev_turn_number)
                   & (sess.turn_number < case.turn_number)]
        text_rows = win[win.turn_type.isin(['assistant_response', 'assistant_thinking'])]
        text_rows_ne = text_rows[text_rows.content.notna()
                                 & (text_rows.content.astype(str).str.len() > 0)]
        if len(text_rows_ne) == 0:
            continue
        gap = int(case.turn_number) - int(case.prev_turn_number)
        combined = "\n".join(str(c) for c in text_rows_ne.content)
        text_wins.append({
            'turn_id': case.turn_id,
            'gap': gap,
            'norm_path': case.get('norm_path', ''),
            'content': combined,
        })
    return text_wins


def suffix_at(norm_path, n):
    if not norm_path:
        return None
    parts = norm_path.replace('\\', '/').split('/')
    parts = [p for p in parts if p]
    if len(parts) < n:
        return None
    return '/'.join(parts[-n:])


def substring_hit(needle, hay):
    if not needle:
        return False
    if needle in hay:
        return True
    if '\\' in needle:
        alt = needle.replace('\\', '/')
    elif '/' in needle:
        alt = needle.replace('/', '\\')
    else:
        alt = None
    if alt is not None and alt != needle and alt in hay:
        return True
    return False


def wb_hit(needle, hay):
    """지시서 사양:
        (?<![\\w/\\\\.-]) + re.escape(needle) + (?![\\w])
       경로 표기 뒤집힘 대응: '/'⇄'\\' 변환 후에도 재검사.
    """
    if not needle:
        return False
    for cand in {needle, needle.replace('/', '\\'), needle.replace('\\', '/')}:
        pat = r'(?<![\w/\\.\-])' + re.escape(cand) + r'(?![\w])'
        if re.search(pat, hay):
            return True
    return False


def task3_word_boundary(parquet_path):
    print()
    print("=" * 70)
    print("Task 3 — word-boundary 매칭 (regex, substring 병기)")
    print("=" * 70)

    text_wins = rebuild_text_windows(parquet_path)
    print(f"text-having windows: {len(text_wins)}")

    for w in text_wins:
        w['_sub'] = {}
        w['_wb'] = {}
        for lvl in [1, 2, 3, 4]:
            s = suffix_at(w['norm_path'], lvl)
            if s is None:
                w['_sub'][lvl] = (None, False)
                w['_wb'][lvl] = (None, False)
                continue
            w['_sub'][lvl] = (s, substring_hit(s, w['content']))
            w['_wb'][lvl] = (s, wb_hit(s, w['content']))

    def stats_for(subset, label):
        n = len(subset)
        if n == 0:
            print(f"  {label}: n=0")
            return
        if n < 10:
            print(f"  {label}: n={n} (표본 부족)")
            return
        print(f"  {label}: n={n}")
        print(f"    {'level':<6} {'substr':>10} {'wb':>10} {'diff (substr-wb)':>20}")
        for lvl in [1, 2, 3, 4]:
            sub_hits = sum(1 for w in subset if w['_sub'][lvl][1])
            wb_hits = sum(1 for w in subset if w['_wb'][lvl][1])
            diff = sub_hits - wb_hits
            print(f"    L{lvl:<5} {sub_hits}/{n} ({sub_hits/n*100:5.2f}%)   "
                  f"{wb_hits}/{n} ({wb_hits/n*100:5.2f}%)   {diff}")

    print()
    print("=== 전체 + gap 구간별 ===")
    stats_for(text_wins, "전체")
    for name, cond in [('gap < 20', lambda g: g < 20),
                       ('20 <= gap < 100', lambda g: 20 <= g < 100),
                       ('gap >= 100', lambda g: g >= 100)]:
        stats_for([w for w in text_wins if cond(w['gap'])], name)

    # substring hit인데 wb miss인 케이스 (오탐 후보) 예시 최대 5건
    print()
    print("=== L1 substring hit && L1 wb miss (오탐 후보) — 최대 5건 ===")
    shown = 0
    for w in text_wins:
        sub_hit = w['_sub'][1][1]
        wb_h = w['_wb'][1][1]
        if sub_hit and not wb_h:
            basename = w['_sub'][1][0]
            print(f"  basename={basename!r}, gap={w['gap']}")
            # 컨텍스트: needle 주변 30자
            idx = w['content'].find(basename)
            if idx >= 0:
                l = max(0, idx - 30)
                r = min(len(w['content']), idx + len(basename) + 30)
                snippet = w['content'][l:r].replace('\n', ' ')
                print(f"    context: ...{snippet}...")
            shown += 1
            if shown >= 5:
                break


# ============================================================
# Task 4
# ============================================================
def task4_os_diagnosis():
    print()
    print("=" * 70)
    print("Task 4 — norm_path / is_abs OS 의존성 진단")
    print("=" * 70)

    scan_code = FIELD_TEST / "run_swechat_waste_scan.py"
    with open(scan_code, encoding='utf-8') as f:
        scan_lines = f.readlines()

    print("=== run_swechat_waste_scan.py:41-58 인용 ===")
    for i in range(40, 58):
        print(f"  {i+1:>3}: {scan_lines[i].rstrip()}")

    print()
    print("=== os.path.normpath 현재 플랫폼 ===")
    print(f"  os.name       : {os.name}")
    print(f"  os.path.sep   : {os.path.sep!r}")
    print(f"  os.path is    : {os.path.__name__}")
    print()

    print("=== normpath 3-way 비교 ===")
    tests_np = ['/Users/x/foo.py',
                '/home/rob/Safecast/docs/DEPLOYMENT.md',
                'C:/Windows/System32',
                'C:\\Windows\\System32',
                'relative/path/x.py',
                'mixed\\slash/path.py']
    print(f"  {'input':<45} {'os.path':<45} {'ntpath':<45} {'posixpath':<45}")
    for t in tests_np:
        print(f"  {t!r:<45} {os.path.normpath(t)!r:<45} "
              f"{ntpath.normpath(t)!r:<45} {posixpath.normpath(t)!r:<45}")

    print()
    print("=== is_abs 코드 (line 41-44) — 자체 로직 ===")
    for i in range(40, 45):
        print(f"  {i+1:>3}: {scan_lines[i].rstrip()}")
    print("  → ntpath.isabs / posixpath.isabs 사용하지 않음.")
    print("  → 자체 로직: p.startswith('/') or (len(p)>=2 and p[1]==':')")
    print()

    print("=== ntpath.isabs vs posixpath.isabs 실제 반환값 ===")
    tests_abs = ['/Users/x', '/home/foo/bar.py', 'C:\\Windows\\a', 'C:/Windows/a',
                 'relative/path', '\\\\network\\share', 'D:\\proj', 'noslash.py']
    print(f"  {'input':<30} {'ntpath.isabs':>15} {'posixpath.isabs':>18} "
          f"{'is_abs (자체)':>15}")

    def is_abs_local(p):
        if not p:
            return None
        return p.startswith('/') or (len(p) >= 2 and p[1] == ':')

    for t in tests_abs:
        print(f"  {t!r:<30} {ntpath.isabs(t)!s:>15} "
              f"{posixpath.isabs(t)!s:>18} {is_abs_local(t)!s:>15}")

    print()
    print("=== 사실 요약 (해석 없음) ===")
    print("  1) run_swechat_waste_scan.py:53 은 os.path.normpath 를 쓴다.")
    print("     Windows 실행 시 POSIX '/' → '\\\\' 로 뒤집힌다 (위 표 확인).")
    print("     Linux 실행 시 POSIX 그대로 유지된다.")
    print("  2) target tuple = (np, off, lim). 세션 내 모든 Read가 같은 normpath를")
    print("     통과하므로, 튜플 비교는 각 OS에서 자체일관 (같은 OS에서 재실행 시")
    print("     동일 카운트). 다른 OS 간 표기가 다르므로 CSV 리터럴은 다르다.")
    print("  3) is_abs 는 ntpath/posixpath 미사용 → OS 무관.")
    print("     혼용 판정(89 세션 제외)은 OS와 무관하게 같은 결과가 나온다.")
    print("  4) CSV 소비 스크립트가 norm_path를 substring 매칭할 때 표기(/, \\\\)에")
    print("     의존하면 OS 간 불일치 가능. (진단만 — 고치지 않음.)")


def main():
    t0 = time.time()
    parquet_path = hf_hub_download('SALT-NLP/SWE-chat', 'conversations.parquet',
                                   repo_type='dataset')
    print(f"parquet: {parquet_path}")
    print()
    state = task1_join_fix(parquet_path)
    task2_v4_proof(state)
    task3_word_boundary(parquet_path)
    task4_os_diagnosis()
    print()
    print(f"wall time: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
