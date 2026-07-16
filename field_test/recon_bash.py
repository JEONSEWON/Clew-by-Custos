"""SWE-chat Bash/Grep recon — schema + fill rates ONLY.

절대 규율:
- 반복/낭비/밀도 숫자 계산 금지 (SPEC 확정 전 리콘 단계)
- content 컬럼 통째로 로드 금지 (1.25GB / 269만 행)
- pyarrow.dataset 컬럼 프로젝션 + 필터 푸시다운 사용
- 카운트는 전수, 표본 금지 (덤프 예시만 소수 허용)
"""
import argparse
import json
from collections import Counter

import pyarrow.dataset as ds
import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

SEP = "=" * 72
SUBSEP = "-" * 72


def resolve_path(cli_arg):
    if cli_arg:
        return cli_arg
    return hf_hub_download('SALT-NLP/SWE-chat', 'conversations.parquet', repo_type='dataset')


def missing_note(cols_present, wanted):
    return [c for c in wanted if c not in cols_present]


def is_filled(v):
    """None + 빈 문자열 둘 다 미충족."""
    if v is None:
        return False
    try:
        s = str(v)
    except Exception:
        return True
    return s.strip() != ""


def section0_schema(pth):
    print(SEP)
    print("SECTION 0 — conversations.parquet SCHEMA")
    print(SEP)
    pf = pq.ParquetFile(pth)
    schema = pf.schema_arrow
    for f in schema:
        print(f"  {f.name}: {f.type}")
    print(f"\n  num_rows(metadata): {pf.metadata.num_rows}")
    print(f"  num_row_groups: {pf.num_row_groups}")
    return [f.name for f in schema]


def section1_counts(pth, cols_all):
    print()
    print(SEP)
    print("SECTION 1 — 전체 카운트 (메타 컬럼만 프로젝션)")
    print(SEP)
    wanted = ['agent', 'tool_name', 'turn_type', 'role']
    miss = missing_note(cols_all, wanted)
    if miss:
        print(f"  MISSING columns: {miss}")
    load_cols = [c for c in wanted if c in cols_all]
    dset = ds.dataset(pth, format='parquet')
    tbl = dset.to_table(columns=load_cols)
    df = tbl.to_pandas()
    print(f"\n[1a] 전체 턴 수: {len(df)}")

    def dump_vc(label, col):
        print(f"\n[1b] {label} value_counts (dropna=False)")
        if col not in df.columns:
            print("  MISSING")
            return
        vc = df[col].value_counts(dropna=False)
        for k, v in vc.head(30).items():
            print(f"  {k!r}: {v}")

    dump_vc("turn_type", "turn_type")
    dump_vc("role", "role")
    dump_vc("agent", "agent")

    print("\n[1c] Claude Code tool_name top 15")
    if 'agent' in df.columns and 'tool_name' in df.columns:
        cc = df[df.agent == "Claude Code"]
        vc = cc.tool_name.value_counts(dropna=False).head(15)
        for k, v in vc.items():
            print(f"  {k!r}: {v}")
    else:
        print("  MISSING (need agent + tool_name)")

    print("\n[1d] Bash/Grep x agent 크로스탭")
    if 'agent' in df.columns and 'tool_name' in df.columns:
        sub = df[df.tool_name.isin(["Bash", "Grep"])]
        ct = sub.groupby(['tool_name', 'agent'], dropna=False).size().unstack(fill_value=0)
        print(ct.to_string())
    else:
        print("  MISSING")

    print("\n[1e] turn_type x role 크로스탭 (Bash/Grep 결과 저장 위치 확인)")
    if 'turn_type' in df.columns and 'role' in df.columns:
        ct = df.groupby(['turn_type', 'role'], dropna=False).size().unstack(fill_value=0)
        print(ct.to_string())
    else:
        print("  MISSING")
    del df


def section2_bashgrep_meta(pth, cols_all):
    print()
    print(SEP)
    print("SECTION 2 — Bash/Grep 서브셋 메타 (푸시다운 필터)")
    print(SEP)
    wanted = ['turn_id', 'session_id', 'turn_number', 'role', 'turn_type',
              'tool_name', 'file_path', 'command', 'pattern', 'tool_input_json',
              'bash_category', 'agent', 'input_tokens', 'output_tokens']
    miss = missing_note(cols_all, wanted)
    if miss:
        print(f"  MISSING columns: {miss}")
    load_cols = [c for c in wanted if c in cols_all]

    dset = ds.dataset(pth, format='parquet')
    tbl = dset.to_table(
        columns=load_cols,
        filter=ds.field('tool_name').isin(['Bash', 'Grep']),
    )
    df = tbl.to_pandas()
    print(f"\n[2a] Bash/Grep 서브셋 크기: {len(df)}")

    if 'turn_id' in df.columns:
        dup = df.turn_id.duplicated(keep=False)
        n_dup = int(dup.sum())
        print(f"[2b] turn_id 중복 행 수(전체 등장): {n_dup}")
        n_dup_keys = int(df.turn_id.duplicated().sum())
        print(f"     중복 초과분(중복키 - 유니크): {n_dup_keys}")
    else:
        print("[2b] turn_id MISSING")

    fill_cols = ['command', 'pattern', 'file_path', 'tool_input_json', 'bash_category']
    print(f"\n[2c] tool x agent 조합별 채움률 (None + '' 모두 미충족)")
    if 'agent' not in df.columns or 'tool_name' not in df.columns:
        print("  MISSING")
    else:
        combos = df.groupby(['tool_name', 'agent'], dropna=False)
        for (tool, agent), grp in combos:
            n = len(grp)
            print(f"\n  {tool} / {agent!r} (n={n})")
            for c in fill_cols:
                if c not in grp.columns:
                    print(f"    {c}: MISSING column")
                    continue
                filled = grp[c].apply(is_filled).sum()
                pct = filled / n * 100 if n else 0.0
                print(f"    {c}: {filled}/{n} ({pct:.2f}%)")
            for tc in ('input_tokens', 'output_tokens'):
                if tc not in grp.columns:
                    print(f"    {tc}: MISSING column")
                    continue
                nz = (grp[tc].fillna(0) != 0).sum()
                mx = grp[tc].fillna(0).max()
                print(f"    {tc}: non-zero {nz}/{n} ({nz/max(n,1)*100:.2f}%) max={mx}")

    print(f"\n[2d] 크로스탭: tool_input_json notna x command 채워짐 (per tool x agent)")
    if ('tool_input_json' in df.columns and 'command' in df.columns
            and 'agent' in df.columns and 'tool_name' in df.columns):
        df['_tij'] = df.tool_input_json.notna()
        df['_cmd'] = df.command.apply(is_filled)
        for (tool, agent), grp in df.groupby(['tool_name', 'agent'], dropna=False):
            ct = grp.groupby(['_tij', '_cmd']).size().unstack(fill_value=0)
            print(f"\n  {tool} / {agent!r}")
            print(ct.to_string())
    else:
        print("  MISSING (need tool_input_json + command + agent + tool_name)")

    return df


def section3_bash_cardinality(df_bg):
    print()
    print(SEP)
    print("SECTION 3 — Claude Code Bash 문자열 카디널리티")
    print(SEP)
    if 'agent' not in df_bg.columns or 'tool_name' not in df_bg.columns:
        print("  MISSING agent/tool_name")
        return
    cc_bash = df_bg[(df_bg.agent == "Claude Code") & (df_bg.tool_name == "Bash")].copy()
    print(f"\n[3a] Claude Code Bash 전체: {len(cc_bash)}")

    if 'command' in cc_bash.columns:
        cmds = cc_bash.command.dropna().astype(str)
        cmds = cmds[cmds.str.strip() != ""]
        total_nonempty = len(cmds)
        distinct = cmds.nunique()
        print(f"[3b] non-empty command: {total_nonempty}")
        print(f"     distinct(exact): {distinct}")
        if total_nonempty:
            print(f"     distinct/total: {distinct/total_nonempty*100:.3f}%")

        print(f"\n[3c] top 30 exact command 문자열")
        for cmd, cnt in cmds.value_counts().head(30).items():
            preview = cmd.replace("\n", "\\n")[:120]
            print(f"  [{cnt}] {preview!r}")

        print(f"\n[3d] top 30 첫 토큰")
        first_tok = cmds.str.split().str[0]
        for tok, cnt in first_tok.value_counts().head(30).items():
            print(f"  [{cnt}] {tok!r}")
    else:
        print("[3b-d] command column MISSING")

    if 'bash_category' in cc_bash.columns:
        print(f"\n[3e] bash_category value_counts (dropna=False)")
        for k, v in cc_bash.bash_category.value_counts(dropna=False).head(50).items():
            print(f"  {k!r}: {v}")

        if 'command' in cc_bash.columns:
            print(f"\n[3f] bash_category x command 채워짐 크로스탭")
            cc_bash['_cmd_filled'] = cc_bash.command.apply(is_filled)
            ct = cc_bash.groupby(['bash_category', '_cmd_filled'], dropna=False).size().unstack(fill_value=0)
            print(ct.to_string())
    else:
        print("[3e-f] bash_category column MISSING")


def section4_arg_schema(df_bg):
    print()
    print(SEP)
    print("SECTION 4 — 벤더별 tool_input_json 키셋 (덤프 우선)")
    print(SEP)
    if 'tool_input_json' not in df_bg.columns:
        print("  MISSING tool_input_json column")
        return
    for (tool, agent), grp in df_bg.groupby(['tool_name', 'agent'], dropna=False):
        rows_tij = grp[grp.tool_input_json.notna()]
        if len(rows_tij) == 0:
            print(f"\n[{tool} / {agent!r}] tool_input_json 전부 None")
            continue
        keyset_counter = Counter()
        parse_fail = 0
        for s in rows_tij.tool_input_json:
            try:
                obj = json.loads(s)
                if isinstance(obj, dict):
                    keyset_counter[tuple(sorted(obj.keys()))] += 1
                else:
                    keyset_counter[("__NON_DICT__",)] += 1
            except Exception:
                parse_fail += 1
        print(f"\n[{tool} / {agent!r}] tool_input_json 있는 행 {len(rows_tij)} / parse_fail {parse_fail}")
        print(f"  key-set 빈도 top 8:")
        for ks, cnt in keyset_counter.most_common(8):
            print(f"    [{cnt}] {list(ks)}")
        print(f"  raw 샘플 2건 (300자 절단):")
        for i, s in enumerate(rows_tij.tool_input_json.head(2).tolist()):
            print(f"    [{i}] {s[:300]!r}")


def section5_session_shape(df_bg):
    print()
    print(SEP)
    print("SECTION 5 — 세션 형태 (Claude Code, Bash/Grep 각각)")
    print(SEP)
    if 'agent' not in df_bg.columns or 'session_id' not in df_bg.columns:
        print("  MISSING agent/session_id")
        return
    cc = df_bg[df_bg.agent == "Claude Code"]
    for tool in ("Bash", "Grep"):
        sub = cc[cc.tool_name == tool]
        per_sess = sub.groupby('session_id').size()
        print(f"\n[{tool}]")
        print(f"  total turns: {len(sub)}")
        print(f"  세션 수 >=1: {(per_sess >= 1).sum()}")
        print(f"  세션 수 >=2: {(per_sess >= 2).sum()}")
        if len(per_sess) > 0:
            desc = per_sess.describe()
            print(f"  세션당 개수 describe:")
            for k, v in desc.items():
                print(f"    {k}: {v}")
        else:
            print("  no sessions")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None, help="conversations.parquet path (default: hf download)")
    args = ap.parse_args()
    pth = resolve_path(args.data)
    print(f"# data: {pth}")

    cols_all = section0_schema(pth)
    section1_counts(pth, cols_all)
    df_bg = section2_bashgrep_meta(pth, cols_all)
    section3_bash_cardinality(df_bg)
    section4_arg_schema(df_bg)
    section5_session_shape(df_bg)


if __name__ == "__main__":
    main()
