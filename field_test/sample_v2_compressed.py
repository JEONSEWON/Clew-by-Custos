"""Sample v2 20 cases (seed=42) with compressed tool-sequence context.

Anomaly check: gap==0 count.
Compressed format: basename paths + tool sequence + user prompts only.
"""
import csv
import json
import os
import random
import re
from pathlib import Path

import pyarrow.dataset as ds
from huggingface_hub import hf_hub_download

CASES_CSV = Path(__file__).parent / "swechat_waste_cases_v2.csv"
SAMPLE_SEED = 42
N = 20


def load_cases():
    with open(CASES_CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_ctx(sids):
    p = hf_hub_download('SALT-NLP/SWE-chat', 'conversations.parquet', repo_type='dataset')
    dset = ds.dataset(p, format='parquet')
    tbl = dset.to_table(
        columns=['session_id', 'turn_number', 'role', 'turn_type', 'tool_name', 'content'],
        filter=ds.field('session_id').isin(list(sids)),
    )
    return tbl.to_pandas()


def parse_args_preview(s):
    """content_preview는 앞 200자 잘림. 유용한 필드만 추출."""
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        pass
    # partial JSON 시도: file_path/pattern/command 추출
    out = {}
    for key in ("file_path", "pattern", "command", "path"):
        m = re.search(rf'"{key}"\s*:\s*"([^"]*)"', s)
        if m:
            out[key] = m.group(1)
    return out


def brief_tool(tool_name, content):
    """tool_use 턴을 짧게: Tool(핵심인자)."""
    if not tool_name:
        return None
    a = parse_args_preview(content)
    if tool_name in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit"):
        fp = a.get("file_path") or a.get("filePath") or ""
        return f"{tool_name}({os.path.basename(fp)})"
    if tool_name == "Bash":
        cmd = (a.get("command") or "").replace("\n", " ")[:40]
        return f"Bash({cmd!r})"
    if tool_name == "Grep":
        pat = (a.get("pattern") or "")[:30]
        return f"Grep({pat!r})"
    if tool_name == "Glob":
        pat = (a.get("pattern") or "")[:30]
        return f"Glob({pat!r})"
    if tool_name in ("Task", "Agent"):
        return f"{tool_name}(...)"
    return f"{tool_name}(...)"


def format_case(c, sess):
    tn = int(c["turn_number"])
    ptn = int(c["prev_turn_number"])
    gap = tn - ptn
    path = c["norm_path"]
    base = os.path.basename(path.replace("\\", "/"))
    kind = "range" if c["offset"] else "FULL"

    between = sess[(sess.turn_number > ptn) & (sess.turn_number < tn)].sort_values("turn_number")

    tools = []
    user_prompts = []
    for _, r in between.iterrows():
        role = str(r.role) if r.role else ""
        if role == "tool_use":
            t = brief_tool(r.tool_name, r.content)
            if t:
                tools.append(t)
        elif role == "user":
            s = str(r.content or "")[:100].replace("\n", " ")
            if s and not s.startswith("[Request interrupted"):
                user_prompts.append(s)

    lines = [f"path={base}, {kind}, prev={ptn}, turn={tn} (gap={gap})"]

    if len(tools) > 20:
        lines.append(f"  between: {' → '.join(tools[:10])}"
                     f"  ...{len(tools)-20}개 생략...  {' → '.join(tools[-10:])}")
    elif tools:
        lines.append(f"  between: {' → '.join(tools)}")
    else:
        lines.append("  between: (tool_use 없음)")

    for up in user_prompts[:5]:
        lines.append(f"  user: {up!r}")

    return "\n".join(lines)


def main():
    cases = load_cases()
    print(f"v2 cases: {len(cases)}")

    # anomaly: gap==0
    gap0 = [c for c in cases if int(c["turn_number"]) == int(c["prev_turn_number"])]
    print(f"anomaly gap==0 (tn == prev_tn): {len(gap0)}")
    if gap0:
        print("  first 3 examples:")
        for c in gap0[:3]:
            print(f"    {c['session_id']} turn={c['turn_number']} path={os.path.basename(c['norm_path'].replace(chr(92), '/'))}")

    rng = random.Random(SAMPLE_SEED)
    sample = rng.sample(cases, min(N, len(cases)))
    print(f"\nsample seed={SAMPLE_SEED}, n={len(sample)}")

    sids = {c["session_id"] for c in sample}
    ctx = load_ctx(sids)
    by_sess = {sid: g.sort_values("turn_number") for sid, g in ctx.groupby("session_id")}

    print()
    for i, c in enumerate(sample):
        sess = by_sess.get(c["session_id"])
        if sess is None:
            print(f"CASE {i}: no context\n")
            continue
        print(f"CASE {i}: {format_case(c, sess)}\n")


if __name__ == "__main__":
    main()
