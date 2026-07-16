"""One-off diagnostic — reproduces SPEC §19.1 관찰 3' (재배치 후: '§19.1 버그의
구조적 귀결') 근거:

    유지 939 median=9 mean=37.3
    신규 1,114 median=189 mean=413.5
    사라짐 55 (모두 gap==0)

옛 코드(8018ae0) drop 조건:
    elif unknown_hit > 0: unresolved += 1
    unknown_hit = 창문 내 아무 Edit 계열 tool_result 행 (파일 무관, 유령 분기)

창문이 길수록 P(하나라도 있음)↑ → waste로 살아남으려면 창문 안 Edit tool_result
가 정확히 0개여야 했다. 긴 gap 후보는 계통적으로 전멸.

Rerun 요건: git 접근으로 커밋 8018ae0의 v1 waste CSV 확보 가능해야 함.
"""
import csv
import subprocess
from pathlib import Path

import pandas as pd

NEW_CSV = Path(__file__).parents[1] / "swechat_waste_cases.csv"
OLD_CSV_COMMIT = "8018ae0"
OLD_CSV_PATH = "field_test/swechat_waste_cases.csv"


def load_new():
    with open(NEW_CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_old():
    out = subprocess.check_output(
        ["git", "show", f"{OLD_CSV_COMMIT}:{OLD_CSV_PATH}"],
        cwd=str(Path(__file__).parents[2]),
    ).decode()
    return list(csv.DictReader(out.splitlines()))


def main():
    new = load_new()
    old = load_old()

    new_ids = {r["turn_id"] for r in new}
    old_ids = {r["turn_id"] for r in old}

    kept_ids = new_ids & old_ids
    gone_ids = old_ids - new_ids
    promoted_ids = new_ids - old_ids

    print(f"kept  (old ∩ new): {len(kept_ids)}")
    print(f"gone  (old - new): {len(gone_ids)}")
    print(f"new   (new - old): {len(promoted_ids)}")
    print()

    def gap(r):
        return int(r["turn_number"]) - int(r["prev_turn_number"])

    kept_gaps = [gap(r) for r in new if r["turn_id"] in kept_ids]
    new_gaps = [gap(r) for r in new if r["turn_id"] in promoted_ids]
    gone_gaps = [gap(r) for r in old if r["turn_id"] in gone_ids]

    for name, arr in [("kept", kept_gaps), ("new", new_gaps), ("gone", gone_gaps)]:
        s = pd.Series(arr)
        print(f"=== {name} (n={len(s)}) ===")
        print(s.describe())
        print()


if __name__ == "__main__":
    main()
