"""One-off diagnostic — reproduces SPEC §19.1 claim:
'role == "tool_result"' is 1:1 with 'turn_type == "tool_result"' across
the full SWE-chat parquet (2,692,480 rows).

Rerun any time to reverify the invariant that underlies v4_reclassify.py's
filter choice.
"""
import pyarrow.dataset as ds
from huggingface_hub import hf_hub_download


def main():
    p = hf_hub_download('SALT-NLP/SWE-chat', 'conversations.parquet', repo_type='dataset')
    dset = ds.dataset(p, format='parquet')
    tbl = dset.to_table(columns=['role', 'turn_type'])
    df = tbl.to_pandas()

    print(f"total rows: {len(df)}")
    print()
    print("=== (role, turn_type) crosstab (전수) ===")
    ct = df.groupby(['role', 'turn_type'], dropna=False).size().reset_index(name='n')
    for _, r in ct.iterrows():
        print(f"  role={r.role!r}  turn_type={r.turn_type!r}  n={r.n}")

    print()
    print("=== 1:1 검사: role=='tool_result' ↔ turn_type=='tool_result' ===")
    tr_role = (df.role == 'tool_result').sum()
    tr_tt = (df.turn_type == 'tool_result').sum()
    tr_both = ((df.role == 'tool_result') & (df.turn_type == 'tool_result')).sum()
    tr_role_only = ((df.role == 'tool_result') & (df.turn_type != 'tool_result')).sum()
    tr_tt_only = ((df.role != 'tool_result') & (df.turn_type == 'tool_result')).sum()
    print(f"  role=='tool_result': {tr_role}")
    print(f"  turn_type=='tool_result': {tr_tt}")
    print(f"  둘 다: {tr_both}")
    print(f"  role만: {tr_role_only}")
    print(f"  turn_type만: {tr_tt_only}")
    print(f"  → 1:1 인가? {tr_role == tr_tt == tr_both and tr_role_only == 0 and tr_tt_only == 0}")


if __name__ == "__main__":
    main()
