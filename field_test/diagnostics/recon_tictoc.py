"""TicToc 리콘 (arXiv:2510.23853, ACL 2026 Findings, UMD).

Step 0: 다운로드 + 스키마. 어댑터 미작성. 데이터 커밋 금지 (data/ .gitignore).

Q1 — 레포 구조 + LICENSE
Q2 [최우선] — 라벨 성격 (실행된 낭비 vs 결정 시점 인간 선호)

Q2 에서 스코프 미일치 확인 → Q3~Q5 건너뜀 (사전 지시).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TICTOC_DIR = ROOT / "data/tictoc"
MAIN = TICTOC_DIR / "merged_fully_labeled_data.json"


def q1():
    print("=" * 78)
    print("Q1 — 레포 구조 + LICENSE")
    print("=" * 78)
    files = sorted(p.name for p in TICTOC_DIR.iterdir() if p.is_file())
    dirs = sorted(p.name for p in TICTOC_DIR.iterdir() if p.is_dir())
    print("files:", files)
    print("dirs:", dirs)
    lic = list(TICTOC_DIR.rglob("LICENSE*")) + list(TICTOC_DIR.rglob("COPYING*"))
    print("LICENSE files:", [str(p.relative_to(TICTOC_DIR)) for p in lic] or "NONE")
    readme = (TICTOC_DIR / "README.md").read_text(encoding="utf-8")
    for ln in readme.splitlines():
        if "licen" in ln.lower() or "MIT" in ln:
            print("README license mention:", ln.strip())
    print()


def q2():
    print("=" * 78)
    print("Q2 — 라벨 성격 (실행된 낭비 vs 결정 시점 선호)")
    print("=" * 78)
    d = json.load(open(MAIN, encoding="utf-8"))
    print(f"total samples: {len(d)}")
    print("sample[0] keys:", list(d[0].keys()))
    print()
    s = d[0]
    print(f"id: {s['id']}")
    print(f"num_turn: {s['num_turn']}")
    print(f"preference: {s['preference']!r}")
    print(f"pref_score: {s['pref_score']}")
    print()
    print("history 마지막 2 메시지:")
    for m in s["history"][-2:]:
        print(json.dumps(m, ensure_ascii=False)[:300])
    print()
    print("call_tool_output:", str(s["call_tool_output"])[:300])
    print("no_call_tool_output:", str(s["no_call_tool_output"])[:300])
    print()
    pref = Counter(x["preference"] for x in d)
    print("preference 분포:", dict(pref))
    scores = [x["pref_score"] for x in d]
    print(f"pref_score range: {min(scores)}..{max(scores)}")
    print()
    print("판정: 각 샘플은 '해당 시점 다음 응답' 을 (call_tool_output, no_call_tool_output)")
    print("        두 branch 로 준비하고, 인간이 선호하는 branch 를 라벨로 부여한다.")
    print("        → 실행된 trajectory 의 redundant step 라벨이 아니라,")
    print("          결정 시점의 counterfactual preference 라벨.")


if __name__ == "__main__":
    q1()
    q2()
