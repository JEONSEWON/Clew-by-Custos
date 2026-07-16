"""gap==0 anomaly 규명: 데이터셋 중복인지, 우리 로직 버그인지."""
import csv
import json
import os
from pathlib import Path

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

CASES_CSV = Path(__file__).parent / "swechat_waste_cases_v2.csv"


def main():
    with open(CASES_CSV, encoding="utf-8") as f:
        cases = list(csv.DictReader(f))
    gap0 = [c for c in cases if int(c["turn_number"]) == int(c["prev_turn_number"])]
    print(f"gap==0 총: {len(gap0)}")
    print()

    p = hf_hub_download('SALT-NLP/SWE-chat', 'conversations.parquet', repo_type='dataset')
    cols = ['turn_id', 'session_id', 'turn_number', 'tool_name', 'file_path',
            'tool_input_json', 'agent', 'input_tokens', 'output_tokens']
    df = pq.read_table(p, columns=cols).to_pandas()
    df = df[df.agent == "Claude Code"]

    # 첫 3건 상세 확인
    for c in gap0[:5]:
        sid = c["session_id"]
        tn = int(c["turn_number"])
        base = os.path.basename(c["norm_path"].replace("\\", "/"))
        print(f"--- session={sid[:8]}... turn={tn} path={base} ---")

        # 같은 (session, turn_number) 조합에 몇 개 행이 있는지
        rows = df[(df.session_id == sid) & (df.turn_number == tn)]
        print(f"  같은 (session,turn_number) 행 개수: {len(rows)}")
        for _, r in rows.iterrows():
            fp = ""
            if r.tool_input_json:
                try:
                    fp = json.loads(r.tool_input_json).get("file_path", "")[:60]
                except Exception:
                    fp = "(parse fail)"
            print(f"    turn_id={r.turn_id} tool={r.tool_name} fp={fp}")
        print()

    # 전체 통계: (session, turn_number) 중복률
    print("=== 전체 통계 ===")
    reads = df[(df.tool_name == "Read") & df.tool_input_json.notna()]
    print(f"Read (Claude Code, tool_input_json 있음): {len(reads)}")
    dup_key = reads.groupby(['session_id', 'turn_number']).size()
    dups = dup_key[dup_key > 1]
    print(f"같은 (session_id, turn_number)에 Read 2건+ 이상: {len(dups)}건")
    if len(dups) > 0:
        print(f"  최대: {dups.max()}건 중복")
        print(f"  분포: {dups.value_counts().to_dict()}")


if __name__ == "__main__":
    main()
