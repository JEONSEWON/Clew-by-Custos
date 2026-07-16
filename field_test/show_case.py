"""Show ONE case (by index in seed=42 sample) — compressed, no fold."""
import csv
import json
import os
import random
import re
import sys
from collections import Counter
from pathlib import Path

import pyarrow.dataset as ds
from huggingface_hub import hf_hub_download

CASES_CSV = Path(__file__).parent / "swechat_waste_cases_v2.csv"
SAMPLE_SEED = 42
N = 20


def parse_args_preview(s):
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        pass
    out = {}
    for key in ("file_path", "pattern", "command", "path"):
        m = re.search(rf'"{key}"\s*:\s*"([^"]*)"', s)
        if m:
            out[key] = m.group(1)
    return out


def brief_tool(tool_name, content):
    if not tool_name:
        return None
    a = parse_args_preview(content)
    if tool_name in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit"):
        fp = a.get("file_path") or a.get("filePath") or ""
        return f"{tool_name}({os.path.basename(fp)})"
    if tool_name == "Bash":
        cmd = (a.get("command") or "").replace("\n", " ")[:40]
        return f"Bash({cmd!r})"
    if tool_name in ("Grep", "Glob"):
        pat = (a.get("pattern") or "")[:30]
        return f"{tool_name}({pat!r})"
    if tool_name in ("Task", "Agent"):
        return f"{tool_name}(...)"
    return f"{tool_name}(...)"


def main(idx):
    with open(CASES_CSV, encoding="utf-8") as f:
        cases = list(csv.DictReader(f))
    rng = random.Random(SAMPLE_SEED)
    sample = rng.sample(cases, min(N, len(cases)))
    c = sample[idx]

    p = hf_hub_download('SALT-NLP/SWE-chat', 'conversations.parquet', repo_type='dataset')
    dset = ds.dataset(p, format='parquet')
    tbl = dset.to_table(
        columns=['session_id', 'turn_number', 'role', 'turn_type', 'tool_name', 'content'],
        filter=ds.field('session_id') == c["session_id"],
    )
    sess = tbl.to_pandas().sort_values("turn_number")

    tn = int(c["turn_number"])
    ptn = int(c["prev_turn_number"])
    gap = tn - ptn
    base = os.path.basename(c["norm_path"].replace("\\", "/"))
    kind = "range" if c["offset"] else "FULL"

    between = sess[(sess.turn_number > ptn) & (sess.turn_number < tn)]

    print(f"=== CASE {idx} ===")
    print(f"session: {c['session_id']}")
    print(f"path=  {base}")
    print(f"{kind}, prev={ptn}, turn={tn} (gap={gap})")
    print(f"between: {len(between)} turns")

    role_mix = Counter(str(r) for r in between.role)
    print(f"  role mix: {dict(role_mix)}")

    tools = []
    users = []
    for _, r in between.iterrows():
        role = str(r.role) if r.role else ""
        if role == "tool_use":
            t = brief_tool(r.tool_name, r.content)
            if t:
                tools.append(t)
        elif role == "user":
            s = str(r.content or "")[:100].replace("\n", " ")
            if s and not s.startswith("[Request interrupted"):
                users.append(s)

    if tools:
        print(f"  tools: {' → '.join(tools)}")
    else:
        print("  tools: (none)")

    for u in users:
        print(f"  user: {u!r}")

    # first Read (prev) 확인용
    prev_row = sess[sess.turn_number == ptn]
    curr_row = sess[sess.turn_number == tn]
    if not prev_row.empty:
        print(f"  [prev@{ptn}] tool={prev_row.iloc[0].tool_name} role={prev_row.iloc[0].role}")
    if not curr_row.empty:
        print(f"  [curr@{tn}] tool={curr_row.iloc[0].tool_name} role={curr_row.iloc[0].role}")


if __name__ == "__main__":
    main(int(sys.argv[1]))
