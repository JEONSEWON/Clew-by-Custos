"""v4 재산출: Read tool_result를 성공 패턴(라인번호 접두어)으로 판정.

- 성공(실제 파일 내용): r'^\s*\d+→' 로 시작
- 캐시 응답: 'File unchanged since last read'로 시작 (벤더가 이미 방지 중)
- 실패/에러: 그 외
"""
import csv
import re
from collections import Counter
from pathlib import Path

import pyarrow.dataset as ds
from huggingface_hub import hf_hub_download

CASES_CSV = Path(__file__).parent / "swechat_waste_cases_v2.csv"

LINE_PREFIX = re.compile(r'^\s*\d+→')
CACHE_MARKER = "File unchanged since last read"


def classify_read_result(content):
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


def load_ctx(sids):
    p = hf_hub_download('SALT-NLP/SWE-chat', 'conversations.parquet', repo_type='dataset')
    dset = ds.dataset(p, format='parquet')
    tbl = dset.to_table(
        columns=['session_id', 'turn_number', 'role', 'tool_name', 'content'],
        filter=ds.field('session_id').isin(list(sids)),
    )
    return tbl.to_pandas()


def main():
    with open(CASES_CSV, encoding="utf-8") as f:
        cases = list(csv.DictReader(f))
    v3 = [c for c in cases if int(c["turn_number"]) != int(c["prev_turn_number"])]
    print(f"v3 candidates (gap>0): {len(v3)}")

    sids = {c["session_id"] for c in v3}
    ctx = load_ctx(sids)
    by_sess = {sid: g.sort_values("turn_number") for sid, g in ctx.groupby("session_id")}

    stats = Counter()

    for c in v3:
        sess = by_sess.get(c["session_id"])
        if sess is None:
            stats["no_ctx"] += 1
            continue
        tn = int(c["turn_number"])
        ptn = int(c["prev_turn_number"])
        between = sess[(sess.turn_number > ptn) & (sess.turn_number < tn)]
        # Read tool_result만 판정 (Grep/Bash 결과는 제외)
        read_results = between[(between.role == "tool_result") & (between.tool_name == "Read")]

        if len(read_results) == 0:
            stats["no_read_result"] += 1
            continue

        kinds = [classify_read_result(r.content) for _, r in read_results.iterrows()]
        # 여러 개면 우선순위: cache_hit > success > error
        if "cache_hit" in kinds:
            stats["has_cache_hit"] += 1
        elif "success" in kinds:
            stats["all_success"] += 1
        else:
            stats["all_error"] += 1

    print()
    print("=== v3 761건 사이 Read tool_result 분류 ===")
    for k, v in stats.most_common():
        print(f"  {k}: {v} ({v/len(v3)*100:.2f}%)")

    print()
    # v4 = success (진짜 재읽기) 만
    v4 = stats["all_success"]
    v4_pool = 60778 - 56  # gap==0 데이터 중복 제외한 pool
    print(f"=== v4 산출 ===")
    print(f"v4 낭비 후보 (사이 Read 성공만): {v4}")
    print(f"v4 밀도: {v4} / {v4_pool} = {v4/v4_pool*100:.3f}%")
    print()
    print(f"벤더 캐시 응답 (Claude Code가 이미 방지): {stats['has_cache_hit']} ({stats['has_cache_hit']/len(v3)*100:.2f}%)")
    print(f"실패/에러 재시도 (정당): {stats['all_error']} ({stats['all_error']/len(v3)*100:.2f}%)")
    print(f"Read result 없음: {stats['no_read_result']} ({stats['no_read_result']/len(v3)*100:.2f}%)")


if __name__ == "__main__":
    main()
