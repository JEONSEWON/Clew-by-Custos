"""CASE 2/4/8의 tool_result content + v3 761건 전체에서 에러/빈 결과 비율."""
import csv
import os
import random
import re
from pathlib import Path

import pyarrow.dataset as ds
from huggingface_hub import hf_hub_download

CASES_CSV = Path(__file__).parent / "swechat_waste_cases_v2.csv"
SAMPLE_SEED = 42

ERROR_PAT = re.compile(r"error|not found|does not exist|cannot read", re.IGNORECASE)


def is_error_or_empty(content):
    if content is None:
        return True, "None"
    s = str(content).strip()
    if s == "":
        return True, "empty"
    if ERROR_PAT.search(s):
        return True, "error_match"
    return False, "ok"


def load_ctx(sids):
    p = hf_hub_download('SALT-NLP/SWE-chat', 'conversations.parquet', repo_type='dataset')
    dset = ds.dataset(p, format='parquet')
    tbl = dset.to_table(
        columns=['session_id', 'turn_number', 'role', 'tool_name', 'content'],
        filter=ds.field('session_id').isin(list(sids)),
    )
    return tbl.to_pandas()


def show_cases_2_4_8():
    with open(CASES_CSV, encoding="utf-8") as f:
        cases = list(csv.DictReader(f))
    rng = random.Random(SAMPLE_SEED)
    sample = rng.sample(cases, 20)

    targets = {2: sample[2], 4: sample[4], 8: sample[8]}
    sids = {c["session_id"] for c in targets.values()}
    ctx = load_ctx(sids)

    for idx, c in targets.items():
        sess = ctx[ctx.session_id == c["session_id"]].sort_values("turn_number")
        tn = int(c["turn_number"])
        ptn = int(c["prev_turn_number"])
        base = os.path.basename(c["norm_path"].replace("\\", "/"))
        print(f"=== CASE {idx}: {base}, prev={ptn}, turn={tn} ===")

        # prev의 tool_result는 ptn+1 부근 (Read tool_use 다음 턴)
        # 하지만 tool_result가 정확히 어느 턴에 오는지 모르니 between 전체 중 tool_result 다 출력
        between = sess[(sess.turn_number > ptn) & (sess.turn_number < tn)]
        results = between[between.role == "tool_result"]
        print(f"  between tool_result 개수: {len(results)}")
        for _, r in results.iterrows():
            content = str(r.content) if r.content else ""
            print(f"  --- turn={int(r.turn_number)} tool={r.tool_name} len={len(content)} ---")
            print(f"  {content[:300]!r}")
        print()


def scan_v3_all():
    """v3 = v2 minus gap==0. 전체 761건에서 사이 tool_result 에러/빈 비율."""
    with open(CASES_CSV, encoding="utf-8") as f:
        cases = list(csv.DictReader(f))
    v3 = [c for c in cases if int(c["turn_number"]) != int(c["prev_turn_number"])]
    print("=== v3 규모 확인: 사이 tool_result 에러/빈 비율 ===")
    print(f"v3 candidates: {len(v3)}")

    sids = {c["session_id"] for c in v3}
    ctx = load_ctx(sids)
    by_sess = {sid: g.sort_values("turn_number") for sid, g in ctx.groupby("session_id")}

    stats = {"any_error_between": 0, "all_ok_between": 0, "no_result_between": 0}
    reasons = {"empty": 0, "error_match": 0, "None": 0}

    for c in v3:
        sess = by_sess.get(c["session_id"])
        if sess is None:
            continue
        tn = int(c["turn_number"])
        ptn = int(c["prev_turn_number"])
        between = sess[(sess.turn_number > ptn) & (sess.turn_number < tn)]
        results = between[between.role == "tool_result"]
        if len(results) == 0:
            stats["no_result_between"] += 1
            continue
        any_err = False
        for _, r in results.iterrows():
            err, why = is_error_or_empty(r.content)
            if err:
                any_err = True
                reasons[why] = reasons.get(why, 0) + 1
                break
        if any_err:
            stats["any_error_between"] += 1
        else:
            stats["all_ok_between"] += 1

    print(f"  사이에 에러/빈 tool_result 있음:  {stats['any_error_between']} ({stats['any_error_between']/len(v3)*100:.2f}%)")
    print(f"  사이에 tool_result 모두 정상:    {stats['all_ok_between']} ({stats['all_ok_between']/len(v3)*100:.2f}%)")
    print(f"  사이에 tool_result 없음:         {stats['no_result_between']} ({stats['no_result_between']/len(v3)*100:.2f}%)")
    print(f"  에러 사유별: {reasons}")
    print()
    v4_count = stats['all_ok_between'] + stats['no_result_between']
    print(f"v4 후보 (에러 재시도 제외): {v4_count} / 60,722 = {v4_count/60722*100:.3f}%")


if __name__ == "__main__":
    show_cases_2_4_8()
    scan_v3_all()
