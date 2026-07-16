"""LINE_PREFIX 정규식 진단 (리콘, 커밋 금지, 고치지 마라).

배경: v4_reclassify.py 는
    LINE_PREFIX = re.compile(r'^\\s*\\d+→')  # 화살표 U+2192
    match 실패 → error 로 fallback.
Part 2b 5건 표본에서 창문 내 tool_result 가 `\\d+\\t...` 로 시작하고 error 로
분류됨. 표본이 5건이므로 일반화 금지. 전수로 세라 (규율 5).

Q1: 63,556 Claude Code Read tool_result 전량 대상. content 앞부분 5-way 분포.
Q2: A vs B 를 가르는 요인 (session / model / timestamp / file_path 확장자).
Q3: A/B 각 1건 앞 40자 repr + ord 로 실제 바이트 확정.
Q4: 정규식 확장 시 v3' 1,272 / v3 761 재산출 (SPEC 수정 안 함).
Q5: `unknown` 범주 도입 시 v4' 변화.

스크립트: field_test/diagnostics/verify_line_prefix.py
"""
import csv
import re
import subprocess
import time
from collections import Counter
from pathlib import Path

import pandas as pd
import pyarrow.compute as pc
import pyarrow.dataset as ds
from huggingface_hub import hf_hub_download

REPO_ROOT = Path(__file__).parents[2]
FIELD_TEST = REPO_ROOT / "field_test"
CASES_V2_CSV = FIELD_TEST / "swechat_waste_cases_v2.csv"
OLD_V2_COMMIT = "8018ae0"
OLD_V2_PATH = "field_test/swechat_waste_cases_v2.csv"

CACHE_MARKER = "File unchanged since last read"
RE_ARROW = re.compile(r'^\s*\d+→')
RE_TAB = re.compile(r'^\s*\d+\t')
RE_UNION = re.compile(r'^\s*\d+[→\t]')


def load_read_tool_results(parquet_path):
    """Read tool_result 만 로드 (agent=Claude Code, 63,556 대상).
    필요한 컬럼만: turn_id, session_id, turn_number, content,
                   model, timestamp, file_path.
    """
    dset = ds.dataset(parquet_path, format='parquet')
    tbl = dset.to_table(
        columns=['turn_id', 'session_id', 'turn_number', 'tool_name',
                 'turn_type', 'agent', 'content', 'model', 'timestamp',
                 'file_path'],
        filter=(ds.field('agent') == 'Claude Code')
               & (ds.field('tool_name') == 'Read')
               & (ds.field('turn_type') == 'tool_result'),
    )
    return tbl.to_pandas().drop_duplicates(subset=['turn_id']).reset_index(drop=True)


def classify_start(content):
    if content is None:
        return 'D'
    s = str(content)
    if s == '' or s.strip() == '':
        return 'D'
    if s.startswith(CACHE_MARKER):
        return 'C'
    if RE_ARROW.match(s):
        return 'A'
    if RE_TAB.match(s):
        return 'B'
    return 'E'


# =============================================================
# Q1 — 5-way 전수 분포
# =============================================================
def q1_distribution(rr):
    print("=" * 70)
    print("Q1 — Claude Code Read tool_result content 앞부분 5-way 분포 (n=63,556 대상)")
    print("=" * 70)
    labels = rr.content.apply(classify_start)
    rr = rr.copy()
    rr['_bucket'] = labels
    total = len(rr)
    print(f"total rows: {total}")
    print()
    print(f"  {'bucket':<6} {'설명':<45} {'n':>8} {'%':>8}")
    for k, desc in [('A', r'^\s*\d+→ (current success)'),
                    ('B', r'^\s*\d+\t (current error fallback)'),
                    ('C', "starts with 'File unchanged since last read'"),
                    ('D', 'empty / None'),
                    ('E', '그 외')]:
        n = int((labels == k).sum())
        print(f"  {k:<6} {desc:<45} {n:>8} {n/total*100:>7.3f}%")

    e_rows = rr[rr._bucket == 'E']
    print()
    print(f"=== E 범주 앞 60자 seed=42 랜덤 10건 ===")
    n_e = len(e_rows)
    if n_e == 0:
        print("  (E 없음)")
    else:
        sample = e_rows.sample(n=min(10, n_e), random_state=42)
        for i, (_, r) in enumerate(sample.iterrows(), 1):
            s = str(r.content)[:60] if r.content is not None else ''
            print(f"  [{i}] {s!r}")
    return rr


# =============================================================
# Q2 — A vs B 가르는 요인
# =============================================================
def q2_a_vs_b(rr):
    print()
    print("=" * 70)
    print("Q2 — A(\\d+→) 와 B(\\d+\\t) 가르는 요인")
    print("=" * 70)
    a = rr[rr._bucket == 'A']
    b = rr[rr._bucket == 'B']
    print(f"A: {len(a)}, B: {len(b)}")
    if len(a) == 0 or len(b) == 0:
        print("A 또는 B 가 없으므로 비교 스킵.")
        return

    # session 분포
    a_sess = set(a.session_id)
    b_sess = set(b.session_id)
    both = a_sess & b_sess
    a_only = a_sess - b_sess
    b_only = b_sess - a_sess
    print()
    print(f"=== session-level ===")
    print(f"  A 있는 세션: {len(a_sess)}")
    print(f"  B 있는 세션: {len(b_sess)}")
    print(f"  A만 있는 세션: {len(a_only)}")
    print(f"  B만 있는 세션: {len(b_only)}")
    print(f"  A/B 혼재 세션: {len(both)}")

    # model crosstab
    print()
    print(f"=== model crosstab ===")
    ct = pd.crosstab(rr._bucket[rr._bucket.isin(['A', 'B'])],
                     rr.model[rr._bucket.isin(['A', 'B'])],
                     dropna=False)
    print(ct.to_string())

    # timestamp
    if 'timestamp' in rr.columns:
        print()
        print(f"=== timestamp (ISO 문자열 또는 datetime) ===")
        for label, sub in [('A', a), ('B', b)]:
            ts = pd.to_datetime(sub.timestamp, errors='coerce')
            valid = ts.dropna()
            if len(valid) == 0:
                print(f"  {label}: timestamp 파싱 불가 또는 결측")
                continue
            print(f"  {label}: min={valid.min()}, median={valid.median()}, max={valid.max()}")

    # file_path 확장자
    print()
    print(f"=== file_path 확장자 top 10 ===")
    def ext_of(p):
        if not p:
            return '(none)'
        s = str(p)
        if '.' not in s:
            return '(no-ext)'
        return '.' + s.rsplit('.', 1)[-1].lower()
    a_ext = a.file_path.apply(ext_of).value_counts().head(10)
    b_ext = b.file_path.apply(ext_of).value_counts().head(10)
    print(f"  A top 10:")
    for k, v in a_ext.items():
        print(f"    {k:<15} {v}")
    print(f"  B top 10:")
    for k, v in b_ext.items():
        print(f"    {k:<15} {v}")


# =============================================================
# Q3 — 실제 바이트 확정
# =============================================================
def q3_bytes(rr):
    print()
    print("=" * 70)
    print("Q3 — A/B 각 1건 앞 40자 repr + ord")
    print("=" * 70)
    a = rr[rr._bucket == 'A']
    b = rr[rr._bucket == 'B']
    for label, sub in [('A', a), ('B', b)]:
        if len(sub) == 0:
            print(f"  {label}: 표본 없음")
            continue
        s = str(sub.iloc[0].content)[:40]
        print(f"\n--- {label} 첫 40자 ---")
        print(f"  repr : {s!r}")
        print(f"  ord  : {[ord(c) for c in s]}")
        # 앞 5자 상세
        print(f"  first 5 chars detail:")
        for i, c in enumerate(s[:5]):
            print(f"    [{i}] {c!r} = U+{ord(c):04X} ({ord(c)})")


# =============================================================
# Q4 — 정규식 확장 영향 측정 (적용 금지)
# =============================================================
def build_ctx_for_v3(parquet_path, sids):
    dset = ds.dataset(parquet_path, format='parquet')
    tbl = dset.to_table(
        columns=['session_id', 'turn_number', 'turn_id', 'role', 'tool_name',
                 'content'],
        filter=ds.field('session_id').isin(sids),
    )
    df = tbl.to_pandas().drop_duplicates(subset=['turn_id']).reset_index(drop=True)
    df['turn_number'] = df.turn_number.astype(int)
    return df


def classify_old(content):
    """v4_reclassify.py 원본 사양."""
    if content is None:
        return 'error'
    s = str(content).strip()
    if s == '':
        return 'error'
    if s.startswith(CACHE_MARKER):
        return 'cache_hit'
    if RE_ARROW.match(s):
        return 'success'
    return 'error'


def classify_new(content):
    """확장 정규식: \\d+[→\\t]."""
    if content is None:
        return 'error'
    s = str(content).strip()
    if s == '':
        return 'error'
    if s.startswith(CACHE_MARKER):
        return 'cache_hit'
    if RE_UNION.match(s):
        return 'success'
    return 'error'


def classify_new_unknown(content):
    """확장 + unknown 범주."""
    if content is None:
        return 'unknown'  # was error
    s = str(content).strip()
    if s == '':
        return 'unknown'
    if s.startswith(CACHE_MARKER):
        return 'cache_hit'
    if RE_UNION.match(s):
        return 'success'
    return 'unknown'


def aggregate_kinds(kinds, has_unknown=False):
    """v4_reclassify.py aggregation 로직 그대로."""
    if len(kinds) == 0:
        return 'no_read_result'
    if 'cache_hit' in kinds:
        return 'has_cache_hit'
    if 'success' in kinds:
        return 'all_success'
    if has_unknown and 'unknown' in kinds and 'error' not in kinds:
        return 'all_unknown'
    return 'all_error'


def load_v3_prime():
    with open(CASES_V2_CSV, encoding='utf-8') as f:
        v2 = pd.DataFrame(list(csv.DictReader(f)))
    for c in ['turn_number', 'prev_turn_number']:
        v2[c] = v2[c].astype(int)
    v3 = v2[v2.turn_number != v2.prev_turn_number].copy()
    v3['gap'] = v3.turn_number - v3.prev_turn_number
    return v3


def load_v3_old():
    """OLD v2 CSV from commit 8018ae0, filter gap>0 → 761."""
    out = subprocess.check_output(
        ['git', 'show', f'{OLD_V2_COMMIT}:{OLD_V2_PATH}'],
        cwd=str(REPO_ROOT),
    ).decode()
    v2 = pd.DataFrame(list(csv.DictReader(out.splitlines())))
    for c in ['turn_number', 'prev_turn_number']:
        v2[c] = v2[c].astype(int)
    v3 = v2[v2.turn_number != v2.prev_turn_number].copy()
    v3['gap'] = v3.turn_number - v3.prev_turn_number
    return v3


def reclassify(v3, ctx_by_sess, classifier):
    labels = []
    for _, row in v3.iterrows():
        sess = ctx_by_sess.get(row.session_id)
        if sess is None:
            labels.append('no_ctx')
            continue
        win = sess[(sess.turn_number > row.prev_turn_number)
                   & (sess.turn_number < row.turn_number)]
        rr = win[(win.role == 'tool_result') & (win.tool_name == 'Read')]
        if len(rr) == 0:
            labels.append('no_read_result')
            continue
        kinds = [classifier(c) for c in rr.content]
        labels.append(aggregate_kinds(kinds))
    return labels


def reclassify_unknown(v3, ctx_by_sess):
    labels = []
    for _, row in v3.iterrows():
        sess = ctx_by_sess.get(row.session_id)
        if sess is None:
            labels.append('no_ctx')
            continue
        win = sess[(sess.turn_number > row.prev_turn_number)
                   & (sess.turn_number < row.turn_number)]
        rr = win[(win.role == 'tool_result') & (win.tool_name == 'Read')]
        if len(rr) == 0:
            labels.append('no_read_result')
            continue
        kinds = [classify_new_unknown(c) for c in rr.content]
        labels.append(aggregate_kinds(kinds, has_unknown=True))
    return labels


def print_breakdown(v3, col, label, expected=None):
    print(f"\n=== {label} 4/5-분류 ===")
    counts = Counter(v3[col])
    for k in ['all_success', 'all_error', 'all_unknown', 'has_cache_hit',
             'no_read_result', 'no_ctx']:
        v = counts.get(k, 0)
        if v == 0 and k not in expected_keys(expected):
            continue
        exp = ""
        if expected and k in expected:
            exp = f"  (기존: {expected[k]})"
        print(f"  {k:<18}: {v:>5}{exp}")

    # gap 분해
    print(f"\n  gap 구간별:")
    for name, cond in [('gap < 20', lambda g: g < 20),
                       ('20 <= gap < 100', lambda g: 20 <= g < 100),
                       ('gap >= 100', lambda g: g >= 100)]:
        sub = v3[v3.gap.apply(cond)]
        n = len(sub)
        s_ = int((sub[col] == 'all_success').sum())
        e_ = int((sub[col] == 'all_error').sum())
        u_ = int((sub[col] == 'all_unknown').sum())
        c_ = int((sub[col] == 'has_cache_hit').sum())
        print(f"    {name}: n={n}, success={s_}, error={e_}, unknown={u_}, cache={c_}")


def expected_keys(exp):
    return set(exp.keys()) if exp else set()


def q4_regex_extension(parquet_path):
    print()
    print("=" * 70)
    print("Q4 — 정규식 확장 (\\d+[→\\t]) 시 v3' / v3 재산출")
    print("=" * 70)

    # v3' 1,272 준비
    v3p = load_v3_prime()
    print(f"v3' rows: {len(v3p)}")
    # v3 761 준비 (OLD)
    v3o = load_v3_old()
    print(f"v3 (OLD) rows: {len(v3o)}")

    # ctx 로드 (v3' ∪ v3o sessions)
    sids = list(set(v3p.session_id) | set(v3o.session_id))
    print(f"ctx sessions to load: {len(sids)}")
    ctx = build_ctx_for_v3(parquet_path, sids)
    ctx_by_sess = {s: g for s, g in ctx.groupby('session_id')}

    # ---- v3' 1,272 (신) ----
    v3p['_old_label'] = reclassify(v3p, ctx_by_sess, classify_old)
    v3p['_new_label'] = reclassify(v3p, ctx_by_sess, classify_new)

    print(f"\n{'='*50}")
    print(f"v3' 1,272 재분류 결과 (기존 sanity check + 확장)")
    print(f"{'='*50}")
    print(f"\n  {'label':<18} {'기존(SPEC)':>12} {'재현(원본 regex)':>18} {'확장(→|\\t)':>15} {'차이':>8}")
    keys = ['all_success', 'all_error', 'has_cache_hit', 'no_read_result']
    spec_ref = {'all_success': 858, 'all_error': 380, 'has_cache_hit': 29,
                'no_read_result': 5}
    old_cnt = Counter(v3p._old_label)
    new_cnt = Counter(v3p._new_label)
    for k in keys:
        ref = spec_ref.get(k, 0)
        old = old_cnt.get(k, 0)
        new = new_cnt.get(k, 0)
        diff = new - old
        print(f"  {k:<18} {ref:>12} {old:>18} {new:>15} {diff:+d}")

    # gap 구간별 (신 v3')
    print(f"\n  v3' 확장 결과 gap 구간별:")
    for name, cond in [('gap < 20', lambda g: g < 20),
                       ('20 <= gap < 100', lambda g: 20 <= g < 100),
                       ('gap >= 100', lambda g: g >= 100)]:
        sub = v3p[v3p.gap.apply(cond)]
        n = len(sub)
        s_ = int((sub._new_label == 'all_success').sum())
        e_ = int((sub._new_label == 'all_error').sum())
        c_ = int((sub._new_label == 'has_cache_hit').sum())
        print(f"    {name}: n={n}, success={s_}, error={e_}, cache={c_}")

    # v4' 재수 (확장)
    v4p_new = int((v3p._new_label == 'all_success').sum())
    v4p_old = int((v3p._old_label == 'all_success').sum())
    print(f"\n  v4' 재수:")
    print(f"    기존(원본 regex): {v4p_old}  (SPEC: 858)")
    print(f"    확장(→|\\t)       : {v4p_new}  차이: {v4p_new - v4p_old:+d}")

    # ---- v3 761 (구) ----
    v3o['_old_label'] = reclassify(v3o, ctx_by_sess, classify_old)
    v3o['_new_label'] = reclassify(v3o, ctx_by_sess, classify_new)

    print(f"\n{'='*50}")
    print(f"v3 (OLD) 761 재분류 결과")
    print(f"{'='*50}")
    print(f"\n  {'label':<18} {'기존(SPEC)':>12} {'재현(원본 regex)':>18} {'확장(→|\\t)':>15} {'차이':>8}")
    spec_ref_old = {'all_success': 424, 'all_error': 317, 'has_cache_hit': 15,
                    'no_read_result': 5}
    old_cnt = Counter(v3o._old_label)
    new_cnt = Counter(v3o._new_label)
    for k in keys:
        ref = spec_ref_old.get(k, 0)
        old = old_cnt.get(k, 0)
        new = new_cnt.get(k, 0)
        diff = new - old
        print(f"  {k:<18} {ref:>12} {old:>18} {new:>15} {diff:+d}")

    v4o_new = int((v3o._new_label == 'all_success').sum())
    v4o_old = int((v3o._old_label == 'all_success').sum())
    print(f"\n  v4 재수:")
    print(f"    기존(원본 regex): {v4o_old}  (SPEC: 424)")
    print(f"    확장(→|\\t)       : {v4o_new}  차이: {v4o_new - v4o_old:+d}")

    return v3p, v3o, ctx_by_sess


# =============================================================
# Q5 — unknown 범주
# =============================================================
def q5_unknown(v3p, v3o, ctx_by_sess):
    print()
    print("=" * 70)
    print("Q5 — `unknown` 범주 도입 시 v4' 변화")
    print("=" * 70)

    v3p['_unk_label'] = reclassify_unknown(v3p, ctx_by_sess)
    v3o['_unk_label'] = reclassify_unknown(v3o, ctx_by_sess)

    print(f"\n=== v3' 1,272 ===")
    print(f"  {'label':<18} {'확장(→|\\t)':>15} {'확장+unknown':>15}")
    ext_cnt = Counter(v3p._new_label)
    unk_cnt = Counter(v3p._unk_label)
    keys = ['all_success', 'all_error', 'all_unknown', 'has_cache_hit', 'no_read_result']
    for k in keys:
        e_ = ext_cnt.get(k, 0)
        u_ = unk_cnt.get(k, 0)
        print(f"  {k:<18} {e_:>15} {u_:>15}")
    print(f"  → v4' (all_success): 확장={int((v3p._new_label=='all_success').sum())}"
          f", 확장+unknown={int((v3p._unk_label=='all_success').sum())}")

    print(f"\n=== v3 (OLD) 761 ===")
    ext_cnt = Counter(v3o._new_label)
    unk_cnt = Counter(v3o._unk_label)
    print(f"  {'label':<18} {'확장(→|\\t)':>15} {'확장+unknown':>15}")
    for k in keys:
        e_ = ext_cnt.get(k, 0)
        u_ = unk_cnt.get(k, 0)
        print(f"  {k:<18} {e_:>15} {u_:>15}")
    print(f"  → v4  (all_success): 확장={int((v3o._new_label=='all_success').sum())}"
          f", 확장+unknown={int((v3o._unk_label=='all_success').sum())}")

    # E 범주 (unknown fallback) 잔여 계산
    print(f"\n=== E 잔여 (정규식 확장 후에도 분류 안 되는 것) ===")
    print(f"  v3' 창문 전체에 대한 unknown 라벨 aggregation:")
    n_unk_p = int((v3p._unk_label == 'all_unknown').sum())
    n_unk_o = int((v3o._unk_label == 'all_unknown').sum())
    print(f"    v3': all_unknown = {n_unk_p}")
    print(f"    v3 : all_unknown = {n_unk_o}")


def main():
    t0 = time.time()
    parquet_path = hf_hub_download('SALT-NLP/SWE-chat', 'conversations.parquet',
                                   repo_type='dataset')
    print(f"parquet: {parquet_path}")
    print()

    print("[loading Read tool_result rows...]")
    rr = load_read_tool_results(parquet_path)
    print(f"loaded rows: {len(rr)}")
    print()

    rr_labeled = q1_distribution(rr)
    q2_a_vs_b(rr_labeled)
    q3_bytes(rr_labeled)

    v3p, v3o, ctx = q4_regex_extension(parquet_path)
    q5_unknown(v3p, v3o, ctx)

    print()
    print(f"wall time: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
