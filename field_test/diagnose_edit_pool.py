"""Step 1 진단: EDIT_TOOLS 판정 오염 규모 확인.

Step 0.5 리콘: tool_name이 tool_use / tool_result 양쪽에 붙는다.
가설: run_swechat_waste_scan.py의 edits_raw는 tool_result Edit 행까지 포함하고 있어
      "미확인 Edit" 조항이 그것들을 결측으로 오인하고 있다.

이 스크립트는 세지 않는다: 낭비/밀도.
확인만: Read/Edit/Write/MultiEdit 각각의 turn_type 분포 + tool_use 행의 file_path 채움률.
"""
import json
import pyarrow.dataset as ds
from huggingface_hub import hf_hub_download

TOOLS = ['Read', 'Edit', 'Write', 'MultiEdit']


def is_filled(v):
    if v is None:
        return False
    try:
        return str(v).strip() != ""
    except Exception:
        return True


def has_file_path_in_tij(s):
    if s is None:
        return False
    try:
        d = json.loads(s)
        if not isinstance(d, dict):
            return False
        return is_filled(d.get('file_path') or d.get('filePath'))
    except Exception:
        return False


def main():
    p = hf_hub_download('SALT-NLP/SWE-chat', 'conversations.parquet', repo_type='dataset')
    dset = ds.dataset(p, format='parquet')
    tbl = dset.to_table(
        columns=['tool_name', 'turn_type', 'agent', 'tool_input_json', 'file_path'],
        filter=(ds.field('agent') == 'Claude Code') & ds.field('tool_name').isin(TOOLS),
    )
    df = tbl.to_pandas()
    print(f"# Claude Code, tool_name ∈ {TOOLS}, total rows: {len(df)}")

    for tool in TOOLS:
        sub = df[df.tool_name == tool]
        print(f"\n[{tool}] n={len(sub)}")
        vc = sub.turn_type.value_counts(dropna=False)
        for k, v in vc.items():
            print(f"  turn_type={k!r}: {v}")

        for tt in ('tool_use', 'tool_result'):
            g = sub[sub.turn_type == tt]
            if len(g) == 0:
                continue
            tij_filled = int(g.tool_input_json.notna().sum())
            fp_col_filled = int(g.file_path.apply(is_filled).sum())
            has_fp = int(g.tool_input_json.apply(has_file_path_in_tij).sum())
            print(f"  {tt}: tij_notna={tij_filled}/{len(g)}  "
                  f"file_path_col_filled={fp_col_filled}/{len(g)}  "
                  f"tij_has_file_path={has_fp}/{len(g)}")

    print("\n# 결정적 확인: 현재 스캐너의 edits_raw 필터")
    print("#   df[df.tool_name.isin(EDIT_TOOLS)]   ← turn_type 필터 없음")
    print("# 이 필터가 잡는 Edit 계열 행 수 (Claude Code 한정):")
    edits_all = df[df.tool_name.isin(['Edit', 'Write', 'MultiEdit'])]
    print(f"  edits_raw 크기: {len(edits_all)}")
    print(f"  이 중 tool_result 행 (tij=None인 정상 결과): "
          f"{int((edits_all.turn_type == 'tool_result').sum())}")
    print(f"  이 중 tool_use 행 (실제 Edit 호출): "
          f"{int((edits_all.turn_type == 'tool_use').sum())}")
    print("# → tool_result 행 전부가 tij=None이라 edit_path()에서 None 반환")
    print("# → 그 tool_result 행이 두 Read 사이에 있으면 unknown_hit 카운트되어 unresolved_between로 drop")
    print("# → 이게 v1 리포트의 '판정 유보 1,115건'의 근본 원인")


if __name__ == "__main__":
    main()
