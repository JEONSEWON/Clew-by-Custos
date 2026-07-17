"""Part 2 diagnostic — v4 필터 모순 진단 (커밋 금지, 고치지 마라).

모순:
  벤더가 'File unchanged since last read' 를 반환하려면 이전에 그 파일을
  성공적으로 읽었어야 한다. 그 tool_result는 창문 안에 있어야.
  그러나 v1' vlw 71 중 compact/agent 24 제외한 47건에서 all_success=0.
  특히 all_error=31. 이전 읽기 전부 실패했는데 벤더가 캐시를 갖고 있다.

Tasks:
  2a: v4_reclassify.py classify 함수 전문 인용 (any vs all).
  2b: all_error 31건 중 seed=42 랜덤 5건 raw 덤프.
  2c: v3' 1,272건 gap 구간별 4분류 비율.
  2d: prev_turn Read의 tool_call_id 로 직접 재분류 → 창문 방식과 병기.

규율: 밀도 재계산 금지. 정의 변경 금지. 스크립트는 diagnostics/에 남긴다.
"""
import csv
import json
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


def classify_read_result_generic(content):
    """cache_hit / success / error — v4_reclassify.py 사양 그대로."""
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


def classify_vlw(content):
    """vendor_labeled_waste (cache_hit alias for v1' side)."""
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


# =============================================================
# 2a — classify 함수 전문 인용
# =============================================================
def task2a_cite_classifier():
    print("=" * 70)
    print("2a — v4_reclassify.py 분류 로직 전문 인용")
    print("=" * 70)
    p = FIELD_TEST / "v4_reclassify.py"
    with open(p, encoding='utf-8') as f:
        lines = f.readlines()
    # 함수 자체 + main 안의 분류 블록 모두
    print("--- classify_read_result 함수 (line 29-39) ---")
    for i in range(28, 40):
        print(f"  {i+1:>3}: {lines[i].rstrip()}")
    print()
    print("--- main 안 분류 블록 (line 76-91) ---")
    for i in range(75, 92):
        print(f"  {i+1:>3}: {lines[i].rstrip()}")
    print()
    print("=== 사실 확인 (해석 없이) ===")
    print("  분류 함수는 단일 tool_result 하나에 대해 3-way 라벨 반환")
    print("    (cache_hit / success / error).")
    print("  창문 내 여러 tool_result가 있을 때 aggregation 코드:")
    print("    line 84: kinds = [classify_read_result(r.content) ...]")
    print("    line 86: if 'cache_hit' in kinds  → has_cache_hit (any 기반)")
    print("    line 88: elif 'success' in kinds  → all_success   (any 기반)")
    print("    line 90: else                      → all_error     (잔여, 실제 all)")
    print("  이름 vs 로직:")
    print("    'all_success' 라벨의 실제 로직은 'any success and no cache_hit'")
    print("    'all_error' 라벨의 실제 로직은 '유일한 cache_hit도 success도 없음'")
    print("    ⇒ 'all_success' 이름은 로직('any success')과 일치하지 않는다.")


# =============================================================
# 2b — all_error 31건 중 seed=42 랜덤 5건 raw dump
# =============================================================
def task2b_all_error_dumps(state):
    print()
    print("=" * 70)
    print("2b — vendor_labeled_waste ∩ all_error 31건 중 seed=42 랜덤 5건 raw 덤프")
    print("=" * 70)
    v1 = state['v1_cases']
    ctx_by_sess = state['ctx_by_sess']
    tcid_class = state['tcid_class']
    use_key_v1 = state['use_key']
    result_by_tcid = state['result_by_tcid']

    with open(CASES_V2_CSV, encoding='utf-8') as f:
        v2 = pd.DataFrame(list(csv.DictReader(f)))
    for c in ['turn_number', 'prev_turn_number']:
        v2[c] = v2[c].astype(int)
    v2_ids = set(v2.turn_id)

    # vendor_labeled_waste 71건 중 v2 통과 & all_error 로 분류되는 건 뽑기
    vlw_ids = [tid for tid, cls in tcid_class.items() if cls == 'vendor_labeled_waste']
    v1_by_id = {r.turn_id: r for _, r in v1.iterrows()}

    def between_reads(sid, ptn, tn):
        sess = ctx_by_sess.get(sid)
        if sess is None:
            return None
        win = sess[(sess.turn_number > ptn) & (sess.turn_number < tn)]
        rr = win[(win.role == 'tool_result') & (win.tool_name == 'Read')]
        return rr.sort_values('turn_number')

    all_error_ids = []
    for tid in vlw_ids:
        row = v1_by_id[tid]
        if tid not in v2_ids:
            continue
        if int(row.turn_number) == int(row.prev_turn_number):
            continue
        rr = between_reads(row.session_id, int(row.prev_turn_number), int(row.turn_number))
        if rr is None or len(rr) == 0:
            continue
        kinds = [classify_read_result_generic(r.content) for _, r in rr.iterrows()]
        if 'cache_hit' in kinds:
            continue
        if 'success' in kinds:
            continue
        all_error_ids.append(tid)

    print(f"all_error 로 분류된 vlw 후보: {len(all_error_ids)}")
    print()

    rng = pd.Series(all_error_ids).sample(n=min(5, len(all_error_ids)),
                                          random_state=42).tolist()
    for i, tid in enumerate(rng, 1):
        row = v1_by_id[tid]
        sid = row.session_id
        tn = int(row.turn_number)
        ptn = int(row.prev_turn_number)
        gap = tn - ptn
        print(f"--- [{i}] turn_id={tid} ---")
        print(f"  session_id       : {sid}")
        print(f"  gap              : {gap} (ptn={ptn} → tn={tn})")
        print(f"  norm_path        : {row.norm_path}")
        print(f"  offset / limit   : {row.offset} / {row.limit}")

        # 창문 내 모든 Read tool_result
        rr = between_reads(sid, ptn, tn)
        print(f"  창문 안 Read tool_result: {len(rr)} 개")
        prev_in_window = False
        for _, r in rr.iterrows():
            cls = classify_read_result_generic(r.content)
            preview = (str(r.content)[:80] if r.content else '').replace('\n', ' ')
            marker = "  <-- ptn+1" if int(r.turn_number) == ptn + 1 else ""
            print(f"    tn={int(r.turn_number)} [{cls}] {preview!r}{marker}")
            if int(r.turn_number) == ptn + 1:
                prev_in_window = True

        # 이전 Read (ptn) 의 tool_result 는 창문 안에 있나?
        if prev_in_window:
            print(f"  이전 Read(ptn={ptn})의 tool_result 는 창문 안(tn={ptn+1})에 있음.")
        else:
            print(f"  이전 Read(ptn={ptn})의 tool_result 는 창문 안에 없음.")
            # ptn+1이 창문 안이 아닌 이유 확인 (개구간 정의상 항상 창문 안이어야 하나?)
            # ptn+1 > ptn (open) && ptn+1 < tn (필요) — tn == ptn+1이면 개구간 창문 비어있음.
            # 이 dump는 gap 검증 이후에 실행하므로 tn > ptn+1 이 보장돼야 하나 실측.
            print(f"    (gap={gap}, 즉 ptn+1={ptn+1} vs tn={tn}: "
                  f"{'ptn+1 == tn 이므로 창문 개구간 비어야 함' if ptn+1==tn else '창문 있어도 ptn+1이 없음 (turn_number 불연속)'})")

        # 후보 자신의 tool_result (tcid 조인)
        tcid = use_key_v1.get((sid, tn))
        content = result_by_tcid.get(tcid) if tcid is not None else None
        preview_own = (str(content)[:80] if content else '').replace('\n', ' ')
        own_cls = classify_read_result_generic(content) if content is not None else 'no_result'
        print(f"  후보 자신(tn={tn}) tool_result [{own_cls}]: {preview_own!r}")
        print()


# =============================================================
# 2c — v3' 1,272건 gap 구간별 4분류 비율
# =============================================================
def task2c_gap_breakdown_v3prime(parquet_path):
    print()
    print("=" * 70)
    print("2c — v3' 1,272건 gap 구간별 4분류 비율 (창문 방식)")
    print("=" * 70)
    with open(CASES_V2_CSV, encoding='utf-8') as f:
        v2 = pd.DataFrame(list(csv.DictReader(f)))
    for c in ['turn_number', 'prev_turn_number']:
        v2[c] = v2[c].astype(int)
    v3 = v2[v2.turn_number != v2.prev_turn_number].copy()
    v3['gap'] = v3.turn_number - v3.prev_turn_number
    print(f"v3' rows: {len(v3)}")

    sids = list(v3.session_id.unique())
    ctx = load_ctx(parquet_path, sids)
    ctx_by_sess = {s: g for s, g in ctx.groupby('session_id')}

    def classify_window(sid, ptn, tn):
        sess = ctx_by_sess.get(sid)
        if sess is None:
            return 'no_ctx'
        win = sess[(sess.turn_number > ptn) & (sess.turn_number < tn)]
        rr = win[(win.role == 'tool_result') & (win.tool_name == 'Read')]
        if len(rr) == 0:
            return 'no_read_result'
        kinds = [classify_read_result_generic(r.content) for _, r in rr.iterrows()]
        if 'cache_hit' in kinds:
            return 'has_cache_hit'
        elif 'success' in kinds:
            return 'all_success'
        else:
            return 'all_error'

    labels = []
    for _, row in v3.iterrows():
        cls = classify_window(row.session_id, int(row.prev_turn_number),
                              int(row.turn_number))
        labels.append(cls)
    v3['_label'] = labels

    print()
    print(f"{'구간':<20} {'n':>6} "
          f"{'all_success':>13} {'all_error':>13} "
          f"{'has_cache_hit':>15} {'no_read_result':>16}")
    for name, cond in [('전체', lambda g: True),
                       ('gap < 20', lambda g: g < 20),
                       ('20 <= gap < 100', lambda g: 20 <= g < 100),
                       ('gap >= 100', lambda g: g >= 100)]:
        sub = v3[v3.gap.apply(cond)]
        n = len(sub)
        if n == 0:
            continue
        cnt = Counter(sub._label)
        s_ = cnt.get('all_success', 0)
        e_ = cnt.get('all_error', 0)
        c_ = cnt.get('has_cache_hit', 0)
        nr = cnt.get('no_read_result', 0)
        print(f"  {name:<18} {n:>6} "
              f"{s_:>4} ({s_/n*100:6.2f}%)  {e_:>4} ({e_/n*100:6.2f}%)  "
              f"{c_:>4} ({c_/n*100:6.2f}%)   {nr:>4} ({nr/n*100:6.2f}%)")

    print()
    print("=== raw 카운트 확인 (SPEC 표와 대조: v3' 858/380/29/5) ===")
    total_cnt = Counter(v3._label)
    print(f"  all_success   : {total_cnt.get('all_success', 0)}  (SPEC v3': 858)")
    print(f"  all_error     : {total_cnt.get('all_error', 0)}   (SPEC v3': 380)")
    print(f"  has_cache_hit : {total_cnt.get('has_cache_hit', 0)}    (SPEC v3': 29)")
    print(f"  no_read_result: {total_cnt.get('no_read_result', 0)}     (SPEC v3': 5)")
    return v3, ctx, ctx_by_sess


# =============================================================
# 2d — prev_turn Read tool_call_id 직접 판정
# =============================================================
def task2d_prev_tcid_reclassify(v3, ctx):
    print()
    print("=" * 70)
    print("2d — 이전 Read(ptn)의 tool_call_id 로 직접 재분류 (창문 방식 병기)")
    print("=" * 70)
    # ptn 위치 Read tool_use 의 tcid 찾기
    read_use_key = {}
    for _, r in ctx[(ctx.tool_name == 'Read') & (ctx.turn_type == 'tool_use')].iterrows():
        read_use_key[(r.session_id, int(r.turn_number))] = r.tool_call_id
    # tcid → tool_result content
    result_by_tcid = {}
    for _, r in ctx[ctx.turn_type == 'tool_result'].iterrows():
        if pd.isna(r.tool_call_id):
            continue
        if r.tool_call_id in result_by_tcid:
            continue  # 중복 tcid는 나중에 처리 안 되나 여기선 first-seen
        result_by_tcid[r.tool_call_id] = r.content

    # 중복 tcid 별도 집계
    tcid_counts = ctx[(ctx.tool_name == 'Read')
                      & ctx.tool_call_id.notna()].groupby(
        ['tool_call_id', 'turn_type']).size().unstack(fill_value=0)
    dup_use = set(tcid_counts[tcid_counts.get('tool_use', 0) > 1].index) if 'tool_use' in tcid_counts.columns else set()
    dup_res = set(tcid_counts[tcid_counts.get('tool_result', 0) > 1].index) if 'tool_result' in tcid_counts.columns else set()
    dup_tcids = dup_use | dup_res
    print(f"Read dup tcids: {len(dup_tcids)}")

    prev_labels = []
    for _, row in v3.iterrows():
        sid = row.session_id
        ptn = int(row.prev_turn_number)
        tcid = read_use_key.get((sid, ptn))
        if tcid is None:
            prev_labels.append('prev_no_use_row')
            continue
        if pd.isna(tcid):
            prev_labels.append('prev_null_tcid')
            continue
        if tcid in dup_tcids:
            prev_labels.append('prev_dup_tcid')
            continue
        content = result_by_tcid.get(tcid)
        if content is None:
            prev_labels.append('prev_no_result')
            continue
        prev_labels.append(classify_read_result_generic(content))
    v3 = v3.copy()
    v3['_prev'] = prev_labels

    print()
    print("=== prev-tcid 재분류 raw 카운트 ===")
    for k, v in Counter(prev_labels).most_common():
        print(f"  {k}: {v} / {len(v3)} = {v/len(v3)*100:.3f}%")

    print()
    print("=== 창문 방식 vs prev-tcid 방식 나란히 표 (v3' 1,272) ===")
    print(f"  {'window':<18} {'prev_tcid':<18} {'count':>6}")
    combo_counts = Counter(zip(v3._label, v3._prev))
    for (w, p), c in combo_counts.most_common():
        print(f"  {w:<18} {p:<18} {c:>6}")

    print()
    print("=== 분류가 바뀐 건수 ===")
    # 매핑: prev == success → all_success, prev == cache_hit → has_cache_hit,
    #      prev == error   → all_error
    def align(prev):
        if prev == 'success':
            return 'all_success'
        if prev == 'cache_hit':
            return 'has_cache_hit'
        if prev == 'error':
            return 'all_error'
        return 'prev_' + prev  # join_fail 계열

    v3['_prev_aligned'] = v3._prev.apply(align)
    changed = 0
    total = 0
    for _, r in v3.iterrows():
        if r._prev_aligned.startswith('prev_'):
            continue  # 조인 실패는 비교 대상 아님
        total += 1
        if r._label != r._prev_aligned:
            changed += 1
    print(f"  비교 가능(prev 조인 성공): {total} / {len(v3)}")
    print(f"  분류 바뀜: {changed} / {total} = {changed/max(total,1)*100:.3f}%")

    print()
    print("=== prev-tcid 방식으로 산출한 v4' 재수 ===")
    v4_new = int((v3._prev == 'success').sum())
    v4_old_from_window = int((v3._label == 'all_success').sum())
    print(f"  창문 방식(all_success)      : {v4_old_from_window}  (SPEC v4': 858)")
    print(f"  prev-tcid 방식(prev=success): {v4_new}")
    print(f"  차이                         : {v4_new - v4_old_from_window}")

    # 창문 방식 상세 이동
    print()
    print("=== 창문 라벨별 prev-tcid 분해 (%표시는 각 창문 라벨 내) ===")
    for w in ['all_success', 'all_error', 'has_cache_hit', 'no_read_result']:
        sub = v3[v3._label == w]
        n = len(sub)
        if n == 0:
            continue
        print(f"  창문={w} (n={n}):")
        for k, c in Counter(sub._prev).most_common():
            print(f"    prev={k:<25} {c:>5} ({c/n*100:6.2f}%)")


# =============================================================
# 공용 state (Task 1 재사용 최소)
# =============================================================
def build_v1_state(parquet_path):
    with open(CASES_CSV, encoding='utf-8') as f:
        v1 = pd.DataFrame(list(csv.DictReader(f)))
    for c in ['turn_number', 'prev_turn_number']:
        v1[c] = v1[c].astype(int)
    sids = list(v1.session_id.unique())
    ctx = load_ctx(parquet_path, sids)
    ctx_by_sess = {s: g for s, g in ctx.groupby('session_id')}

    read_rows = ctx[ctx.tool_name == 'Read']
    tcid_notna = read_rows[read_rows.tool_call_id.notna()]
    tcid_counts = tcid_notna.groupby(['tool_call_id', 'turn_type']).size().unstack(fill_value=0)
    dup_use = set(tcid_counts[tcid_counts.get('tool_use', 0) > 1].index) if 'tool_use' in tcid_counts.columns else set()
    dup_res = set(tcid_counts[tcid_counts.get('tool_result', 0) > 1].index) if 'tool_result' in tcid_counts.columns else set()
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

    tcid_class = {}
    for _, case in v1.iterrows():
        key = (case.session_id, int(case.turn_number))
        tcid = use_key.get(key)
        if tcid is None or pd.isna(tcid):
            tcid_class[case.turn_id] = 'join_fail_no_tcid'
            continue
        if tcid in dup_tcids:
            tcid_class[case.turn_id] = 'excluded_dup_tcid'
            continue
        content = result_by_tcid.get(tcid)
        if content is None:
            tcid_class[case.turn_id] = 'join_fail_no_result'
            continue
        tcid_class[case.turn_id] = classify_vlw(content)

    return {
        'v1_cases': v1,
        'ctx': ctx,
        'ctx_by_sess': ctx_by_sess,
        'tcid_class': tcid_class,
        'use_key': use_key,
        'result_by_tcid': result_by_tcid,
        'dup_tcids': dup_tcids,
    }


def main():
    t0 = time.time()
    parquet_path = hf_hub_download('SALT-NLP/SWE-chat', 'conversations.parquet',
                                   repo_type='dataset')
    print(f"parquet: {parquet_path}")
    print()

    task2a_cite_classifier()

    state = build_v1_state(parquet_path)
    task2b_all_error_dumps(state)

    v3, ctx, _ = task2c_gap_breakdown_v3prime(parquet_path)
    task2d_prev_tcid_reclassify(v3, ctx)

    print()
    print(f"wall time: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
