"""Quantify 2 gaps found in v1 sample: /compact events and Agent/Task turns between Reads.

v1 = SPEC as-registered. v2 = v1 minus (compact-spanning OR agent-spanning) cases.
Direction: reduces waste count → honest, not post-hoc tuning.
"""
import csv
from collections import Counter
from pathlib import Path
from statistics import median, quantiles

import pyarrow.dataset as ds
from huggingface_hub import hf_hub_download

CASES_CSV = Path(__file__).parent / "swechat_waste_cases.csv"
OUT_CSV = Path(__file__).parent / "swechat_waste_cases_v2.csv"

COMPACT_MARKER = "This session is being continued from a previous conversation"
AGENT_TOOLS = {"Task", "Agent"}


def load_cases():
    with open(CASES_CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_ctx(session_ids):
    p = hf_hub_download('SALT-NLP/SWE-chat', 'conversations.parquet', repo_type='dataset')
    dset = ds.dataset(p, format='parquet')
    tbl = dset.to_table(
        columns=['session_id', 'turn_number', 'role', 'turn_type', 'tool_name', 'content'],
        filter=ds.field('session_id').isin(list(session_ids)),
    )
    return tbl.to_pandas()


def main():
    cases = load_cases()
    print(f"loaded {len(cases)} cases from {CASES_CSV.name}")

    sids = {c["session_id"] for c in cases}
    print(f"sessions to fetch context for: {len(sids)}")
    ctx = load_ctx(sids)
    print(f"fetched {len(ctx)} context rows")

    by_sess = {sid: g.sort_values("turn_number") for sid, g in ctx.groupby("session_id")}

    counters = Counter()
    gaps = []
    offset_kind = Counter()
    v2_cases = []

    for c in cases:
        sid = c["session_id"]
        tn = int(c["turn_number"])
        ptn = int(c["prev_turn_number"])
        gap = tn - ptn
        gaps.append(gap)
        has_off = bool(c["offset"]) and c["offset"] != ""
        offset_kind["range" if has_off else "FULL"] += 1

        sess = by_sess.get(sid)
        if sess is None:
            counters["no_ctx"] += 1
            continue

        between = sess[(sess.turn_number > ptn) & (sess.turn_number < tn)]

        has_compact = between.content.astype(str).str.contains(COMPACT_MARKER, na=False).any()
        has_agent = between.tool_name.isin(AGENT_TOOLS).any()

        if has_compact and has_agent:
            counters["both"] += 1
        elif has_compact:
            counters["compact_only"] += 1
        elif has_agent:
            counters["agent_only"] += 1
        else:
            counters["neither"] += 1
            v2_cases.append(c)

    print()
    print("=== Gap 1+2 quantification (v1 → v2) ===")
    print(f"compact-spanning:  {counters['compact_only']}")
    print(f"agent-spanning:    {counters['agent_only']}")
    print(f"both:              {counters['both']}")
    print(f"neither (v2 keep): {counters['neither']}")
    total_excluded = counters['compact_only'] + counters['agent_only'] + counters['both']
    print(f"total excluded:    {total_excluded} / {len(cases)} "
          f"= {total_excluded/len(cases)*100:.2f}%")

    print()
    print("=== v2 aggregate ===")
    print(f"v1 waste Read: {len(cases)}")
    print(f"v2 waste Read: {counters['neither']}")

    print()
    print("=== gap distribution (turn_number 차이) ===")
    qs = quantiles(gaps, n=4)
    print(f"n={len(gaps)}, min={min(gaps)}, max={max(gaps)}")
    print(f"P25={qs[0]:.0f}, median={median(gaps):.0f}, P75={qs[1]:.0f}, ...P75(again)={qs[2]:.0f}")
    print(f"mean={sum(gaps)/len(gaps):.1f}")

    print()
    print("=== offset kind (v1 994건) ===")
    print(f"FULL (offset 없음): {offset_kind['FULL']} ({offset_kind['FULL']/len(cases)*100:.1f}%)")
    print(f"range 지정:         {offset_kind['range']} ({offset_kind['range']/len(cases)*100:.1f}%)")

    # dump v2 cases
    if v2_cases:
        fields = list(v2_cases[0].keys())
        with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(v2_cases)
        print(f"\nv2 dump: {OUT_CSV} ({len(v2_cases)} rows)")


if __name__ == "__main__":
    main()
