"""§19.2 개정 v4 재분류 (v4'' 재산출).

개정 내용 (§19.2, 커밋 82d905d 사전등록):
  A. 정규식 확장: r'^\\s*\\d+[→\\t]'  — U+2192 및 U+0009 (탭) 모두 인정.
  B. 판정 방식 교체: 창문 any → prev_turn_number Read 의 tool_call_id 직접 조인.
  C. unknown 범주 신설. 조용히 error 로 떨어뜨리지 않음.

우선순위 (개정 3):
  cache_marker → cache_hit
  ^\\s*\\d+[→\\t] → success
  '<tool_use_error>' → error
  'exceeds max tokens' → error
  빈 / None → error
  else → unknown (fallback 교체)

v4 = prev 가 success 인 것만.
cache_hit / error / unknown / 조인실패 각각 별도 집계.

원본 (변경 전) 은 8018ae0 / 911eeda 에 보존.
2×2 표(창문×정규식, prev-tcid×정규식) 를 v3'(1,272) 와 v3 OLD(761) 각각 대해
병기 출력하여 비교 축을 남긴다.

Usage:
    python v4_reclassify.py --pool <analysis_pool_size>
    (pool = run_swechat_waste_scan.py 의 reads_after_mixed_exclusion)
"""
import argparse
import csv
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds
from huggingface_hub import hf_hub_download

FIELD_TEST = Path(__file__).parent
REPO_ROOT = FIELD_TEST.parent
CASES_V1_CSV = FIELD_TEST / "swechat_waste_cases.csv"       # 2,053 rows (v1')
CASES_V2_CSV = FIELD_TEST / "swechat_waste_cases_v2.csv"    # 1,272 rows (v2' → v3')
OLD_V2_COMMIT = "8018ae0"
OLD_V2_PATH = "field_test/swechat_waste_cases_v2.csv"        # commit 8018ae0 → v3 OLD 761

CACHE_MARKER = "File unchanged since last read"
RE_ARROW = re.compile(r'^\s*\d+→')            # OLD regex
RE_UNION = re.compile(r'^\s*\d+[→\t]')        # NEW regex (사실 A 개정)
RE_LINENUM_ANY = re.compile(r'\d+[→\t]')      # 앵커 없음 (E sub-classify 용)
TOOL_USE_ERROR = "<tool_use_error>"
MAX_TOKENS_ERR = "exceeds max tokens"
SYSTEM_REMINDER_PREFIX = "<system-reminder>"

STOP_JOIN_FAIL_PCT = 5.0
UNKNOWN_NEGATIVE_PCT = 5.0
PREDICTION_LO, PREDICTION_HI = 950, 1000   # SPEC §19.2 예측 범위


# =============================================================
# 분류기
# =============================================================
def classify_new_unknown(content):
    """§19.2 개정 3: 우선순위 with unknown fallback."""
    if content is None:
        return "error"
    s = str(content).strip()
    if s == "":
        return "error"
    if s.startswith(CACHE_MARKER):
        return "cache_hit"
    if RE_UNION.match(s):
        return "success"
    if TOOL_USE_ERROR in s[:200]:
        return "error"
    if MAX_TOKENS_ERR in s[:200]:
        return "error"
    return "unknown"


def classify_old_2way(content):
    """OLD (변경 전) 재현용: [→] + error fallback."""
    if content is None:
        return "error"
    s = str(content).strip()
    if s == "":
        return "error"
    if s.startswith(CACHE_MARKER):
        return "cache_hit"
    if RE_ARROW.match(s):
        return "success"
    return "error"


def classify_new_2way(content):
    """확장 정규식 + error fallback (unknown 없이, 2×2 표 재현용)."""
    if content is None:
        return "error"
    s = str(content).strip()
    if s == "":
        return "error"
    if s.startswith(CACHE_MARKER):
        return "cache_hit"
    if RE_UNION.match(s):
        return "success"
    return "error"


# =============================================================
# 데이터 로드
# =============================================================
def load_v3_prime():
    with open(CASES_V2_CSV, encoding='utf-8') as f:
        v2 = pd.DataFrame(list(csv.DictReader(f)))
    for c in ['turn_number', 'prev_turn_number']:
        v2[c] = v2[c].astype(int)
    v3 = v2[v2.turn_number != v2.prev_turn_number].copy()
    v3['gap'] = v3.turn_number - v3.prev_turn_number
    return v3


def load_v3_old():
    """OLD v2 CSV from commit 8018ae0, filter gap>0 → v3 OLD 761."""
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


def load_ctx(parquet_path, sids):
    dset = ds.dataset(parquet_path, format='parquet')
    tbl = dset.to_table(
        columns=['session_id', 'turn_number', 'turn_id', 'turn_type',
                 'role', 'tool_name', 'content', 'tool_call_id'],
        filter=ds.field('session_id').isin(sids),
    )
    df = tbl.to_pandas().drop_duplicates(subset=['turn_id']).reset_index(drop=True)
    df['turn_number'] = df.turn_number.astype(int)
    return df


def load_read_tool_result_pool(parquet_path):
    """Claude Code Read tool_result 전량 (E sub-classify 용)."""
    dset = ds.dataset(parquet_path, format='parquet')
    tbl = dset.to_table(
        columns=['turn_id', 'session_id', 'turn_number', 'tool_name',
                 'turn_type', 'agent', 'content'],
        filter=(ds.field('agent') == 'Claude Code')
               & (ds.field('tool_name') == 'Read')
               & (ds.field('turn_type') == 'tool_result'),
    )
    return tbl.to_pandas().drop_duplicates(subset=['turn_id']).reset_index(drop=True)


# =============================================================
# 창문 방식 (기존, 재현용)
# =============================================================
def classify_window(v3, ctx_by_sess, classifier, has_unknown=False):
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
        if 'cache_hit' in kinds:
            labels.append('has_cache_hit')
        elif 'success' in kinds:
            labels.append('all_success')
        elif has_unknown and 'unknown' in kinds and 'error' not in kinds:
            labels.append('all_unknown')
        else:
            labels.append('all_error')
    return labels


# =============================================================
# prev-tcid 방식 (§19.2 개정)
# =============================================================
def build_prev_tcid_maps(ctx):
    """prev_turn Read tool_use → tool_call_id → tool_result content 맵.
    중복 tool_call_id 는 dup_tcids 로 조인 제외.
    """
    read = ctx[ctx.tool_name == 'Read']
    tcid_notna = read[read.tool_call_id.notna()]
    counts = tcid_notna.groupby(['tool_call_id', 'turn_type']).size().unstack(fill_value=0)
    dup_use = (
        set(counts[counts.get('tool_use', 0) > 1].index)
        if 'tool_use' in counts.columns else set()
    )
    dup_res = (
        set(counts[counts.get('tool_result', 0) > 1].index)
        if 'tool_result' in counts.columns else set()
    )
    dup_tcids = dup_use | dup_res

    use_key = {}
    for _, r in ctx[(ctx.tool_name == 'Read') & (ctx.turn_type == 'tool_use')].iterrows():
        use_key[(r.session_id, int(r.turn_number))] = r.tool_call_id

    result_by_tcid = {}
    for _, r in ctx[ctx.turn_type == 'tool_result'].iterrows():
        if pd.isna(r.tool_call_id):
            continue
        if r.tool_call_id in dup_tcids:
            continue
        if r.tool_call_id in result_by_tcid:
            continue
        result_by_tcid[r.tool_call_id] = r.content

    return use_key, result_by_tcid, dup_tcids


def classify_prev_tcid(v3, use_key, result_by_tcid, dup_tcids, classifier):
    """prev_turn_number Read tool_call_id 로 직접 판정.

    반환 labels: 'success' / 'cache_hit' / 'error' / 'unknown'
                 or 'join_fail_no_tcid' / 'join_fail_null_tcid'
                    / 'join_fail_dup_tcid' / 'join_fail_no_result'
    """
    labels = []
    for _, row in v3.iterrows():
        key = (row.session_id, int(row.prev_turn_number))
        tcid = use_key.get(key)
        if tcid is None:
            labels.append('join_fail_no_tcid')
            continue
        if pd.isna(tcid):
            labels.append('join_fail_null_tcid')
            continue
        if tcid in dup_tcids:
            labels.append('join_fail_dup_tcid')
            continue
        content = result_by_tcid.get(tcid)
        if content is None:
            labels.append('join_fail_no_result')
            continue
        labels.append(classifier(content))
    return labels


def summarize_join(labels, name):
    n = len(labels)
    cnt = Counter(labels)
    ok = sum(v for k, v in cnt.items() if not k.startswith('join_fail'))
    fail = n - ok
    print(f"\n[{name}] prev-tcid 조인 통계 (n={n}):")
    print(f"  ok               : {ok:>5}  ({ok/n*100:6.3f}%)")
    print(f"  join_fail 합계    : {fail:>5}  ({fail/n*100:6.3f}%)")
    for k in ['join_fail_no_tcid', 'join_fail_null_tcid',
              'join_fail_dup_tcid', 'join_fail_no_result']:
        v = cnt.get(k, 0)
        print(f"    {k:<25}: {v:>5}  ({v/n*100:6.3f}%)")
    return fail / n * 100.0


# =============================================================
# E 범주 sub-classify (사실 C 개정, E 1,489 전수)
# =============================================================
def sub_classify_e_category(rr_pool):
    def is_e(content):
        if content is None:
            return False
        s = str(content)
        if s == "" or s.strip() == "":
            return False
        if s.startswith(CACHE_MARKER):
            return False
        if RE_UNION.match(s):
            return False
        return True

    e_rows = rr_pool[rr_pool.content.apply(is_e)].reset_index(drop=True)
    print("=" * 70)
    print("E 범주 (정규식 확장 후에도 매치 안 됨) 전수 sub-classify")
    print("=" * 70)
    print(f"  E rows: {len(e_rows)}  (SPEC 실측: 1,489)")

    # 첫 매치 우선순위 (mutually exclusive)
    patterns = [
        ('<tool_use_error>', lambda s: TOOL_USE_ERROR in s[:200]),
        ('exceeds max tokens', lambda s: MAX_TOKENS_ERR in s[:200]),
        ('starts with <system-reminder>',
         lambda s: s.startswith(SYSTEM_REMINDER_PREFIX)),
        ('has 라인번호 접두어 어딘가 (앵커 우회)',
         lambda s: RE_LINENUM_ANY.search(s[:500]) is not None),
    ]
    labeled = {name: 0 for name, _ in patterns}
    unmatched = []
    for _, r in e_rows.iterrows():
        s = str(r.content)
        matched = None
        for name, cond in patterns:
            try:
                if cond(s):
                    matched = name
                    break
            except Exception:
                continue
        if matched:
            labeled[matched] += 1
        else:
            unmatched.append(s)

    print("\n  E 패턴별 건수 (첫 매치, 상호배제):")
    for name, _ in patterns:
        n = labeled[name]
        pct = n / max(len(e_rows), 1) * 100
        print(f"    {name:<45} {n:>5}  ({pct:6.2f}%)")
    print(f"    {'(어떤 패턴에도 매치 안 됨)':<45} {len(unmatched):>5}  "
          f"({len(unmatched)/max(len(e_rows),1)*100:6.2f}%)")

    # <system-reminder> + linenum 세부
    print("\n  <system-reminder> 접두 케이스 세부 (E 내 하위 분해):")
    sr_rows = e_rows[e_rows.content.apply(
        lambda c: c is not None and str(c).startswith(SYSTEM_REMINDER_PREFIX))]
    n_sr = len(sr_rows)
    n_sr_with_linenum = int(sr_rows.content.apply(
        lambda c: RE_LINENUM_ANY.search(str(c)[:2000]) is not None).sum())
    print(f"    <system-reminder> 시작 총            : {n_sr:>5}")
    print(f"    그 중 뒤에 \\d+[→\\t] 존재            : {n_sr_with_linenum:>5}")
    print(f"    → 앵커 ^ 가 라인번호 접두 감지 놓친 건: {n_sr_with_linenum:>5}")
    print("    (해석: SPEC §19.2 개정 3 우선순위상 이는 unknown 으로 분류됨. 문서 확인용.)")

    if unmatched:
        print("\n  unmatched 잔여 앞 60자 (최대 15건):")
        for i, s in enumerate(unmatched[:15]):
            preview = s[:60].replace('\n', ' ')
            print(f"    [{i+1}] {preview!r}")


# =============================================================
# 2×2 표
# =============================================================
def render_2x2(name, v3, ctx_by_sess, use_key, result_by_tcid, dup_tcids,
               spec_old_win=None, spec_new_win=None, spec_old_prev=None):
    """2×2 표 렌더: (창문 any) × (정규식 [→] / [→\\t]) — v3 별 4셀."""
    print("=" * 70)
    print(f"2×2 표 — {name} (n={len(v3)})")
    print("=" * 70)

    # 창문 방식 × OLD regex
    lab_win_old = classify_window(v3, ctx_by_sess, classify_old_2way)
    win_old_success = lab_win_old.count('all_success')

    # 창문 방식 × NEW regex
    lab_win_new = classify_window(v3, ctx_by_sess, classify_new_2way)
    win_new_success = lab_win_new.count('all_success')

    # prev-tcid × OLD regex
    lab_prev_old = classify_prev_tcid(v3, use_key, result_by_tcid, dup_tcids,
                                       classify_old_2way)
    prev_old_success = lab_prev_old.count('success')

    # prev-tcid × NEW regex (with unknown fallback — v4'' 본 산출)
    lab_prev_new_unk = classify_prev_tcid(v3, use_key, result_by_tcid, dup_tcids,
                                           classify_new_unknown)
    prev_new_success = lab_prev_new_unk.count('success')

    def fmt(v, spec):
        if spec is None:
            return f"{v}"
        marker = " ✓" if v == spec else f" ⚠ SPEC={spec}"
        return f"{v}{marker}"

    print()
    print(f"  {'':<18} {'창문 any (기존)':>22} {'prev-tcid (개정)':>22}")
    print(f"  {'-' * 18} {'-' * 22} {'-' * 22}")
    print(f"  {'정규식 [→]':<18} {fmt(win_old_success, spec_old_win):>22} "
          f"{fmt(prev_old_success, spec_old_prev):>22}")
    print(f"  {'정규식 [→\\t]':<18} {fmt(win_new_success, spec_new_win):>22} "
          f"{prev_new_success:>22}")

    return {
        'win_old': lab_win_old, 'win_new': lab_win_new,
        'prev_old': lab_prev_old, 'prev_new_unk': lab_prev_new_unk,
    }


# =============================================================
# gap 구간별 분해
# =============================================================
def gap_breakdown(v3, labels, col_name):
    v3 = v3.copy()
    v3['_label'] = labels
    print(f"\n  gap 구간별 ({col_name}):")
    print(f"    {'구간':<20} {'n':>5} {'success':>8} {'cache_hit':>10} "
          f"{'error':>8} {'unknown':>8} {'join_fail':>10}")
    for name, cond in [('전체', lambda g: True),
                       ('gap < 20', lambda g: g < 20),
                       ('20 <= gap < 100', lambda g: 20 <= g < 100),
                       ('gap >= 100', lambda g: g >= 100)]:
        sub = v3[v3.gap.apply(cond)]
        n = len(sub)
        if n == 0:
            continue
        c = Counter(sub._label)
        s_ = c.get('success', 0)
        ch = c.get('cache_hit', 0)
        e_ = c.get('error', 0)
        u_ = c.get('unknown', 0)
        jf = sum(v for k, v in c.items() if k.startswith('join_fail'))
        print(f"    {name:<20} {n:>5} {s_:>8} {ch:>10} {e_:>8} {u_:>8} {jf:>10}")


# =============================================================
# 중단조건 확인
# =============================================================
def check_stop_conditions(v3p_len, join_fail_pct_v3p):
    print("=" * 70)
    print("중단조건 확인 (SPEC §19.2)")
    print("=" * 70)

    # 조건 2: v1' 후보 수 = 2,053
    with open(CASES_V1_CSV, encoding='utf-8') as f:
        v1_rows = sum(1 for _ in csv.DictReader(f))
    ok2 = (v1_rows == 2053)
    print(f"  [2] v1' 후보 수 = 2,053              : 실측 {v1_rows}  "
          f"{'✓' if ok2 else '⚠ 다름'}")

    # 조건 3: file-level = 15,787, 오탐 제거율 = 87.0%
    # 이 라운드는 run_swechat_waste_scan.py 를 실행하지 않으므로
    # v4_reclassify.py 는 classify_read_result 만 변경한다.
    # SPEC §19.1 확정치 병기 (§19.2 중단조건 3 은 "바뀌면 잘못됨" 검출용).
    file_level_spec = 15787
    removal_pct_spec = (1 - 2053 / file_level_spec) * 100
    print("  [3a] file-level = 15,787             : SPEC 확정 15,787  "
          "(이 라운드 recompute 없음)")
    print(f"  [3b] 오탐 제거율 = 87.0%             : 유도값 "
          f"{removal_pct_spec:.3f}%  "
          f"{'✓' if abs(removal_pct_spec - 87.0) < 0.05 else '⚠ 다름'}")
    print("        (구성상 불변: 본 라운드는 run_swechat_waste_scan.py 미실행,")
    print("         classify_read_result 만 개정. file-level 계산 경로 무변경.)")

    # 조건 1: prev-tcid 조인 실패율 5% 초과
    ok1 = (join_fail_pct_v3p < STOP_JOIN_FAIL_PCT)
    print(f"  [1] v3' prev-tcid 조인 실패율 < 5%   : 실측 "
          f"{join_fail_pct_v3p:.3f}%  {'✓' if ok1 else '⚠ 초과 — 중단'}")

    if not (ok1 and ok2):
        print()
        print("!! 중단조건 위반. 아래 조건이 실패 —")
        if not ok1:
            print(f"   조인 실패율 {join_fail_pct_v3p:.3f}% > 5%. 즉시 멈춤.")
        if not ok2:
            print(f"   v1' 후보 수 {v1_rows} != 2,053. 상류가 바뀜.")
        sys.exit(2)


# =============================================================
# 예측 적중 확인
# =============================================================
def check_prediction(v4_pp):
    print()
    print("=" * 70)
    print("예측 적중 (SPEC §19.2 재실행 전 예측: 950 ~ 1,000)")
    print("=" * 70)
    hit = PREDICTION_LO <= v4_pp <= PREDICTION_HI
    print(f"  v4'' (v3' × prev-tcid × [→\\t] × unknown): {v4_pp}")
    print(f"  예측 범위                                 : [{PREDICTION_LO}, {PREDICTION_HI}]")
    if hit:
        print("  결과: 적중 ✓")
    else:
        direction = "미달" if v4_pp < PREDICTION_LO else "초과"
        print(f"  결과: 빗나감 ({direction}). 예측에 맞춰 정의 조정 금지 — 그대로 기록.")


# =============================================================
# main
# =============================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", type=int, required=True,
                    help="분석 pool 크기 (reads_after_mixed_exclusion)")
    args = ap.parse_args()

    t0 = time.time()
    parquet_path = hf_hub_download('SALT-NLP/SWE-chat', 'conversations.parquet',
                                   repo_type='dataset')
    print(f"parquet: {parquet_path}")
    print(f"pool (reads_after_mixed_exclusion): {args.pool}")
    print()

    # 후보 로드
    v3p = load_v3_prime()
    v3o = load_v3_old()
    print(f"v3' rows (post-amendment): {len(v3p)}  (SPEC: 1,272)")
    print(f"v3 OLD rows (8018ae0)   : {len(v3o)}  (SPEC:   761)")

    # ctx 로드
    sids = list(set(v3p.session_id) | set(v3o.session_id))
    print(f"ctx sessions to load    : {len(sids)}")
    print("[loading ctx...]")
    ctx = load_ctx(parquet_path, sids)
    ctx_by_sess = {s: g for s, g in ctx.groupby('session_id')}
    print(f"ctx rows loaded         : {len(ctx)}")

    use_key, result_by_tcid, dup_tcids = build_prev_tcid_maps(ctx)
    print(f"Read dup tcids          : {len(dup_tcids)}")
    print()

    # ----- 2×2 표 : v3' -----
    r_v3p = render_2x2(
        "v3' 1,272 기준", v3p, ctx_by_sess, use_key, result_by_tcid, dup_tcids,
        spec_old_win=858, spec_new_win=1006, spec_old_prev=812,
    )
    join_fail_pct_v3p = summarize_join(r_v3p['prev_new_unk'],
                                        "v3' × prev-tcid × [→\\t] × unknown")
    gap_breakdown(v3p, r_v3p['prev_new_unk'],
                  "v3' × prev-tcid × [→\\t] × unknown")

    # 창문(개정 unknown) 별도 산출 — SPEC v3' 858/380/29/5 sanity 및 unknown 규모
    lab_win_new_unk = classify_window(v3p, ctx_by_sess, classify_new_unknown,
                                       has_unknown=True)
    print()
    print("  v3' 창문 방식 (개정 unknown 포함) 라벨 분포:")
    for k, v in Counter(lab_win_new_unk).most_common():
        print(f"    {k:<18}: {v:>5}")

    # unknown 5% 임계
    n_unknown_prev_v3p = r_v3p['prev_new_unk'].count('unknown')
    unknown_pct_v3p = n_unknown_prev_v3p / len(v3p) * 100
    print()
    print("=" * 70)
    print("음성 결과 정의 확인 (§19.2)")
    print("=" * 70)
    print(f"  v3' × prev-tcid × unknown 건수: {n_unknown_prev_v3p} / {len(v3p)} "
          f"= {unknown_pct_v3p:.3f}%")
    if unknown_pct_v3p > UNKNOWN_NEGATIVE_PCT:
        print("  ⚠ 5% 초과 — SPEC §19.2 음성 결과 정의 발동:")
        print("    \"분류기가 데이터의 상당 부분을 이해하지 못한다\" 를 v4'' 숫자에 영구 부착.")
    else:
        print("  5% 이하 — 음성 결과 정의 미발동.")

    # ----- 2×2 표 : v3 OLD -----
    r_v3o = render_2x2(
        "v3 (OLD) 761 기준", v3o, ctx_by_sess, use_key, result_by_tcid, dup_tcids,
        spec_old_win=424, spec_new_win=516, spec_old_prev=None,
    )
    join_fail_pct_v3o = summarize_join(r_v3o['prev_new_unk'],
                                        "v3 OLD × prev-tcid × [→\\t] × unknown")

    # ----- E 범주 sub-classify -----
    print()
    print("[loading Read tool_result pool for E sub-classify...]")
    rr_pool = load_read_tool_result_pool(parquet_path)
    print(f"pool rows: {len(rr_pool)}")
    print()
    sub_classify_e_category(rr_pool)

    # ----- 중단조건 -----
    print()
    check_stop_conditions(len(v3p), join_fail_pct_v3p)

    # ----- v4'' 밀도 -----
    v4pp = r_v3p['prev_new_unk'].count('success')
    print()
    print("=" * 70)
    print("v4'' 산출 (§19.2 primary output)")
    print("=" * 70)
    v4_density = v4pp / args.pool * 100
    print(f"  v4'' (v3' × prev-tcid × [→\\t] × unknown): {v4pp}")
    print(f"  pool  (reads_after_mixed_exclusion)      : {args.pool}")
    print(f"  v4'' 밀도                                 : {v4pp}/{args.pool} "
          f"= {v4_density:.3f}%")
    print()
    print("  병기 (금지: 삭제):")
    print(f"    v4  (v3 OLD × 창문 any × [→])  = {r_v3o['win_old'].count('all_success')}"
          f"  (SPEC: 424)")
    print(f"    v4' (v3'    × 창문 any × [→])  = {r_v3p['win_old'].count('all_success')}"
          f"  (SPEC: 858)")

    # ----- 예측 적중 -----
    check_prediction(v4pp)

    print()
    print(f"wall time: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
