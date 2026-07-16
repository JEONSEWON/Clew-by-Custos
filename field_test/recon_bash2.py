"""SWE-chat Bash/Grep Step 0.5 recon.

절대 규율:
- 반복/낭비/밀도 숫자 계산 금지
- content 통째 로드 금지 (세션 필터 후에만)
- 표본은 seed 고정 랜덤. 규모 상위 N 절대 금지 (길이 교란)
"""
import argparse
import random

import pyarrow.dataset as ds
import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

SEP = "=" * 72
SUBSEP = "-" * 72


def resolve_path(cli_arg):
    if cli_arg:
        return cli_arg
    return hf_hub_download('SALT-NLP/SWE-chat', 'conversations.parquet', repo_type='dataset')


def is_filled(v):
    if v is None:
        return False
    try:
        s = str(v)
    except Exception:
        return True
    return s.strip() != ""


def load_bashgrep_meta(pth):
    cols = ['turn_id', 'session_id', 'turn_number', 'role', 'turn_type',
            'tool_name', 'file_path', 'command', 'pattern', 'tool_input_json',
            'tool_call_id', 'bash_category', 'agent']
    dset = ds.dataset(pth, format='parquet')
    tbl = dset.to_table(
        columns=cols,
        filter=ds.field('tool_name').isin(['Bash', 'Grep']),
    )
    return tbl.to_pandas()


def q1_type_split(df):
    print(SEP)
    print("Q1 — turn_type 분리 (가설: tool_name이 tool_result 행에도 붙어있다)")
    print(SEP)
    hypothesis_confirmed_flags = []
    for (tool, agent), grp in df.groupby(['tool_name', 'agent'], dropna=False):
        n = len(grp)
        print(f"\n[{tool} / {agent!r}] n={n}")
        vc = grp.turn_type.value_counts(dropna=False)
        print(f"  turn_type value_counts:")
        for k, v in vc.items():
            print(f"    {k!r}: {v}")

        g = grp.copy()
        g['_tij_filled'] = g.tool_input_json.notna()
        ct = g.groupby(['turn_type', '_tij_filled'], dropna=False).size().unstack(fill_value=0)
        print(f"  crosstab: turn_type × tool_input_json notna")
        print("    " + ct.to_string().replace("\n", "\n    "))

        if tool == 'Bash':
            g['_cmd_filled'] = g.command.apply(is_filled)
            ct2 = g.groupby(['turn_type', '_cmd_filled'], dropna=False).size().unstack(fill_value=0)
            print(f"  crosstab: turn_type × command 채워짐")
            print("    " + ct2.to_string().replace("\n", "\n    "))
        else:
            g['_pat_filled'] = g.pattern.apply(is_filled)
            ct2 = g.groupby(['turn_type', '_pat_filled'], dropna=False).size().unstack(fill_value=0)
            print(f"  crosstab: turn_type × pattern 채워짐")
            print("    " + ct2.to_string().replace("\n", "\n    "))

        if agent == 'Claude Code':
            tu = g[g.turn_type == 'tool_use']
            tr = g[g.turn_type == 'tool_result']
            tij_in_tu = tu.tool_input_json.notna().sum() if len(tu) else 0
            tij_in_tr = tr.tool_input_json.notna().sum() if len(tr) else 0
            print(f"  요약: tool_use tij채움 {tij_in_tu}/{len(tu)}, "
                  f"tool_result tij채움 {tij_in_tr}/{len(tr)}")
            if len(tu) and len(tr):
                tu_ratio = tij_in_tu / len(tu)
                tr_ratio = tij_in_tr / len(tr)
                flag = (tu_ratio > 0.99) and (tr_ratio < 0.01)
                hypothesis_confirmed_flags.append(flag)

    print(f"\n※ Claude Code Bash/Grep 모두에서 (tool_use tij ~100%, tool_result tij ~0%)? "
          f"{all(hypothesis_confirmed_flags) if hypothesis_confirmed_flags else 'N/A'}")
    return all(hypothesis_confirmed_flags) if hypothesis_confirmed_flags else False


def q2_tool_call_id(df):
    print()
    print(SEP)
    print("Q2 — tool_call_id 조인 가능성")
    print(SEP)
    for (tool, agent), grp in df.groupby(['tool_name', 'agent'], dropna=False):
        if agent != 'Claude Code':
            continue
        print(f"\n[{tool} / {agent!r}]")
        g = grp.copy()
        g['_tci_filled'] = g.tool_call_id.apply(is_filled)
        ct = g.groupby(['turn_type', '_tci_filled'], dropna=False).size().unstack(fill_value=0)
        print(f"  turn_type × tool_call_id 채워짐:")
        print("    " + ct.to_string().replace("\n", "\n    "))

        tu = g[(g.turn_type == 'tool_use') & g.tool_call_id.apply(is_filled)]
        tr = g[(g.turn_type == 'tool_result') & g.tool_call_id.apply(is_filled)]
        tu_ids = set(tu.tool_call_id)
        tr_ids = set(tr.tool_call_id)
        inter = tu_ids & tr_ids
        only_tu = tu_ids - tr_ids
        only_tr = tr_ids - tu_ids
        print(f"  tool_use   tool_call_id (filled): total={len(tu)} unique={len(tu_ids)}")
        print(f"  tool_result tool_call_id (filled): total={len(tr)} unique={len(tr_ids)}")
        print(f"  교집합: {len(inter)}")
        print(f"  tool_use에만 (결과 없는 호출): {len(only_tu)}")
        print(f"  tool_result에만 (고아 결과): {len(only_tr)}")

        tu_dup = tu.tool_call_id.value_counts()
        tu_dup = tu_dup[tu_dup > 1]
        tr_dup = tr.tool_call_id.value_counts()
        tr_dup = tr_dup[tr_dup > 1]
        print(f"  tool_use 안 tool_call_id 1:N 있음: {len(tu_dup)} keys "
              f"(max_dup={int(tu_dup.max()) if len(tu_dup) else 0})")
        print(f"  tool_result 안 tool_call_id 1:N 있음: {len(tr_dup)} keys "
              f"(max_dup={int(tr_dup.max()) if len(tr_dup) else 0})")


def q3_true_missing(df):
    print()
    print(SEP)
    print("Q3 — [스킵] Q1 가설이 참이므로 결측 구조 조사 불필요")
    print(SEP)
    print("  (가설이 참이면: tij None은 tool_result 행의 정상 상태)")


def q4_result_content_sample(pth, df):
    print()
    print(SEP)
    print("Q4 — Bash tool_result content 실제 형태 (seed=42 세션 20)")
    print(SEP)
    cc_bash = df[(df.tool_name == 'Bash') & (df.agent == 'Claude Code')]
    all_sids = sorted(cc_bash.session_id.dropna().unique().tolist())
    print(f"  Claude Code Bash 세션 수: {len(all_sids)}")
    rng = random.Random(42)
    sample_sids = rng.sample(all_sids, min(20, len(all_sids)))
    print(f"  seed=42 random 20 세션 (규모 상위 금지 원칙 준수)")
    print(f"  샘플 세션 앞 3개: {sample_sids[:3]}")

    dset = ds.dataset(pth, format='parquet')
    tbl = dset.to_table(
        columns=['session_id', 'turn_number', 'turn_type', 'tool_name',
                 'tool_call_id', 'content'],
        filter=(ds.field('session_id').isin(sample_sids)
                & (ds.field('tool_name') == 'Bash')
                & (ds.field('turn_type') == 'tool_result')),
    )
    ctx = tbl.to_pandas().sort_values(['session_id', 'turn_number'])
    print(f"  로드된 Bash tool_result 행: {len(ctx)}")

    print(f"\n  세션당 1건씩 최대 20건 덤프 (첫 200자):")
    seen = set()
    dumped = 0
    for _, r in ctx.iterrows():
        sid = r.session_id
        if sid in seen:
            continue
        seen.add(sid)
        c = str(r.content) if r.content is not None else ""
        preview = c[:200].replace("\n", "\\n").replace("\r", "\\r")
        print(f"    --- sid={sid[:8]}... turn={int(r.turn_number)} len={len(c)} ---")
        print(f"    {preview!r}")
        dumped += 1
        if dumped >= 20:
            break

    print(f"\n  실패 마커 검색 (content 전체 20 세션분 Bash tool_result):")
    markers = [
        "command not found",
        "Exit code:",
        "exit code",
        "Error:",
        "error:",
        "No such file or directory",
        "Permission denied",
        "Traceback (most recent call last):",
        "syntax error",
    ]
    for m in markers:
        cnt = ctx.content.astype(str).str.contains(m, case=False, regex=False, na=False).sum()
        print(f"    {m!r}: {int(cnt)} rows / {len(ctx)}")


def q5_char_counts(pth):
    print()
    print(SEP)
    print("Q5 — tool_result char_count describe (Claude Code)")
    print(SEP)
    dset = ds.dataset(pth, format='parquet')
    tbl = dset.to_table(
        columns=['tool_name', 'char_count', 'word_count', 'turn_type', 'agent'],
        filter=((ds.field('turn_type') == 'tool_result')
                & (ds.field('agent') == 'Claude Code')
                & ds.field('tool_name').isin(['Bash', 'Read', 'Grep', 'Edit'])),
    )
    df = tbl.to_pandas()
    print(f"  전체: {len(df)} rows")
    for tool in ('Bash', 'Read', 'Grep', 'Edit'):
        sub = df[df.tool_name == tool]
        print(f"\n  [{tool}] n={len(sub)}")
        if len(sub) == 0:
            continue
        desc = sub.char_count.describe()
        for k, v in desc.items():
            print(f"    {k}: {v}")


def q6_hash_commands(df):
    print()
    print(SEP)
    print("Q6 — Claude Code Bash 중 command 첫 토큰이 '#'인 10건 덤프")
    print(SEP)
    cc_bash = df[(df.tool_name == 'Bash') & (df.agent == 'Claude Code')].copy()
    cmds = cc_bash.command.dropna().astype(str)
    cmds = cmds[cmds.str.strip().str.startswith('#')]
    print(f"  '#' 시작 command 총: {len(cmds)}")
    print(f"  앞 10건 (150자 절단, 줄바꿈 escape):")
    for i, c in enumerate(cmds.head(10).tolist()):
        prev = c[:150].replace("\n", "\\n").replace("\r", "\\r")
        print(f"    [{i}] {prev!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None)
    args = ap.parse_args()
    pth = resolve_path(args.data)
    print(f"# data: {pth}")

    df = load_bashgrep_meta(pth)
    print(f"# Bash/Grep 서브셋: {len(df)} rows\n")

    hypothesis_true = q1_type_split(df)
    print()
    print(SEP)
    print(f"### Q1 결론: 가설 {'참 — tool_name이 tool_result 행에도 붙어있다.' if hypothesis_true else '거짓 — 결측이 진짜다.'}")
    print(SEP)

    q2_tool_call_id(df)

    if hypothesis_true:
        q3_true_missing(df)
    else:
        print()
        print(SEP)
        print("Q3 — 결측이 진짜이므로 구조 조사 (본 스크립트에선 미구현, 별도 추적)")
        print(SEP)

    q4_result_content_sample(pth, df)
    q5_char_counts(pth)
    q6_hash_commands(df)


if __name__ == "__main__":
    main()
