"""field_test/diagnostics/recon_redundancybench.py

RedundancyBench (arXiv:2605.29893) 스키마 리콘.
- 어댑터 코드 없음. 리콘만.
- 데이터/스크립트 커밋 금지.
- 결론 금지, raw 만.

Usage:
    python field_test/diagnostics/recon_redundancybench.py
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path("data/redundancy_bench/data/domain")
DOMAINS = ["airline", "retail", "telecom"]


def _load(p: Path):
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def q1_repo_structure() -> None:
    print("=" * 78)
    print("Q1  레포 구조")
    print("=" * 78)
    print("  4open.science/r/RedundancyBench (익명, MIT 라이선스)")
    print("  ├── LICENSE          MIT © 2026 Minyang Hu")
    print("  ├── README.md        6970 bytes")
    print("  ├── assets/title.png")
    print("  ├── LLM_judge/")
    print("  │   ├── judge.py       (LLM inference — 사용 안 함)")
    print("  │   ├── evaluate.py    (평가 스크립트 — 우리 대조 기준)")
    print("  │   └── requirements.txt")
    print("  └── data/domain/")
    for d in DOMAINS:
        ann_p = ROOT / d / "annotation.json"
        tr_p = ROOT / d / "final_traces.json"
        an_sz = ann_p.stat().st_size if ann_p.exists() else 0
        tr_sz = tr_p.stat().st_size if tr_p.exists() else 0
        print(f"      ├── {d}/")
        print(f"      │   ├── annotation.json     ({an_sz:>7,} bytes)")
        print(f"      │   └── final_traces.json   ({tr_sz:>10,} bytes)")


def q2_label_structure() -> None:
    print()
    print("=" * 78)
    print("Q2  라벨 구조 (annotation.json)")
    print("=" * 78)
    print("  스키마: list[dict], dict keys = ['task_id', 'redundant_step_idx',")
    print("          'redundant_step_type', 'reason']")
    print()
    for d in DOMAINS:
        ann = _load(ROOT / d / "annotation.json")
        n = len(ann)
        with_red = sum(1 for a in ann if a["redundant_step_idx"])
        total_red = sum(len(a["redundant_step_idx"]) for a in ann)
        # type dist (non-empty)
        ct = Counter()
        empty_type_lists = 0
        for a in ann:
            types = a.get("redundant_step_type", [])
            for t in types:
                if t:
                    ct[t] += 1
            if a["redundant_step_idx"] and all(t == "" for t in types):
                empty_type_lists += 1
        print(f"  {d}: {n} tasks, {with_red} with_red, total_red_steps={total_red}, "
              f"empty-type-lists={empty_type_lists}")
        print(f"    typed dist: {dict(ct)}")

    # 예시 (task_id=1 airline)
    print()
    print("  === 예시: airline task_id=1 ===")
    ann = _load(ROOT / "airline" / "annotation.json")
    for a in ann:
        if a["task_id"] == "1":
            print(f"    redundant_step_idx: {a['redundant_step_idx']}")
            print(f"    redundant_step_type: {a['redundant_step_type']}")
            print(f"    reason[0]: {a['reason'][0][:80]!r}")
            break

    print()
    print("  4 카테고리 (README):")
    print("    - exploratory step  (탐색적 — 우리 pingpong 유사)")
    print("    - duplicated step   (중복 — 우리 sha256 게이트 직접 대응)")
    print("    - abnormal step     (예외/에러 툴콜)")
    print("    - incorrect step    (미션 벗어남)")


def q3_trajectory_format() -> None:
    print()
    print("=" * 78)
    print("Q3  trajectory 포맷 (final_traces.json)")
    print("=" * 78)
    print("  최상위: dict, keys = ['tasks', 'simulations']")
    print("    tasks       : list[dict]  — 문제 정의 (id, description, ...)")
    print("    simulations : list[dict]  — 실제 trajectory")
    print()
    print("  simulation.keys() 주요:")
    print("    id, task_id, timestamp, messages, ticks, reward_info, ...")
    print()
    print("  messages[i] 구조 (OpenAI-유사, 확장 필드 있음):")
    print("    - role: 'assistant' | 'user' | 'tool'")
    print("    - turn_idx: int (== list index. 확인됨)")
    print("    - content: str")
    print("    - tool_calls: null | list[{id, name, arguments, requestor}]")
    print("        (Toolathlon 은 function: {name, arguments(str)}. RB 는 name/arguments 가 flat)")
    print("        (arguments 는 dict, Toolathlon 은 JSON string)")
    print("    - timestamp: iso datetime")
    print()
    print("  tool 메시지: {'id': call_XXX, 'role': 'tool', 'content': str}")
    print("    ★ 조인 키: tool.id  ==  assistant.tool_calls[j].id")
    print("       (Toolathlon 은 tool_call_id — 필드명 다름)")
    print("    tool.tool_call_id 는 존재하지 않음 (None)")
    print()

    # 조인 검증 (airline 전 sim)
    tr = _load(ROOT / "airline" / "final_traces.json")
    print(f"  airline: tasks={len(tr['tasks'])} simulations={len(tr['simulations'])}")
    join_ok = 0
    join_bad = 0
    for s in tr["simulations"]:
        cids = []
        rids = []
        for m in s["messages"]:
            if m["role"] == "assistant" and isinstance(m.get("tool_calls"), list):
                for tc in m["tool_calls"]:
                    if isinstance(tc, dict):
                        cids.append(tc.get("id"))
            if m["role"] == "tool":
                rids.append(m.get("id"))
        cset = {c for c in cids if c}
        rset = {r for r in rids if r}
        if cset == rset:
            join_ok += 1
        else:
            join_bad += 1
    print(f"  airline 조인 상태: match={join_ok}, mismatch={join_bad}")

    # sample turn_idx == index 검증
    tr_ok = 0
    tr_bad = 0
    for s in tr["simulations"]:
        for i, m in enumerate(s["messages"]):
            if m.get("turn_idx") != i:
                tr_bad += 1
                break
        else:
            tr_ok += 1
    print(f"  airline turn_idx == index: ok={tr_ok}, mismatch_sims={tr_bad}")


def q3b_user_initiated_tool_calls() -> None:
    """Q3b — role=user 가 발행하는 tool_calls 검증.

    최초 Q3 (airline join) 은 assistant.tool_calls ↔ tool.id 만 봤다.
    실측 시 telecom 에서만 tool msg 수 > assistant.tool_calls 수 발견.
    원인: telecom 유저가 디바이스 상태를 시뮬레이션하는 tool msg 를 발행
         (`role=user, tool_calls=[...]` + `role=tool, requestor='user'`).
    어댑터 정책 (§24.2) 은 assistant-requestor 만 span 화 → 이 세트 제외.
    """
    print()
    print("=" * 78)
    print("Q3b  role=user 발행 tool_calls (도메인별)")
    print("=" * 78)
    for d in DOMAINS:
        tr = _load(ROOT / d / "final_traces.json")
        from collections import Counter as _C
        req_ct = _C()
        user_tc_ct = 0
        asst_tc_ct = 0
        for s in tr["simulations"]:
            for m in s["messages"]:
                if m.get("role") == "tool":
                    req_ct[m.get("requestor")] += 1
                if isinstance(m.get("tool_calls"), list):
                    n_tc = sum(1 for tc in m["tool_calls"] if isinstance(tc, dict) and tc.get("id"))
                    if m.get("role") == "user":
                        user_tc_ct += n_tc
                    elif m.get("role") == "assistant":
                        asst_tc_ct += n_tc
        print(f"  {d:8s}  tool msg requestor 분포 = {dict(req_ct)}")
        print(f"            assistant 발행 tool_calls = {asst_tc_ct}   user 발행 tool_calls = {user_tc_ct}")


def q4_scale() -> None:
    print()
    print("=" * 78)
    print("Q4  규모")
    print("=" * 78)
    total_traj = 0
    total_red = 0
    total_red_traj = 0
    all_types = Counter()
    all_msg = 0
    all_tool_msg = 0
    for d in DOMAINS:
        ann = _load(ROOT / d / "annotation.json")
        tr = _load(ROOT / d / "final_traces.json")
        n = len(ann)
        with_red = sum(1 for a in ann if a["redundant_step_idx"])
        red_ct = sum(len(a["redundant_step_idx"]) for a in ann)
        m_ct = sum(len(s["messages"]) for s in tr["simulations"])
        tool_ct = sum(1 for s in tr["simulations"] for m in s["messages"] if m["role"] == "tool")
        ct = Counter()
        for a in ann:
            for t in a.get("redundant_step_type", []):
                if t:
                    ct[t] += 1
        all_types.update(ct)
        total_traj += n
        total_red_traj += with_red
        total_red += red_ct
        all_msg += m_ct
        all_tool_msg += tool_ct
        print(f"  {d:8s}  trajs={n:>4}  with_red={with_red:>4}  red_steps={red_ct:>4}  "
              f"total_msgs={m_ct:>6}  tool_msgs={tool_ct:>5}")
    print()
    print(f"  TOTAL     trajs={total_traj:>4}  with_red={total_red_traj:>4}  "
          f"red_steps={total_red:>4}  msgs={all_msg}  tool_msgs={all_tool_msg}")
    print(f"  typed dist (전 도메인): {dict(all_types)}")


def q5_evaluation() -> None:
    print()
    print("=" * 78)
    print("Q5  평가 방법 (LLM_judge/evaluate.py 근거)")
    print("=" * 78)
    print("""
  두 지표:
    1) Trajectory-Level: redundancy_detection_accuracy
       = (both_red + both_non_red) / total_tasks
       = "has-redundant / not" 매칭 이진 정확도

    2) Step-Level: overall_f1 (micro-averaged)
       tp = |GT_set ∩ Pred_set|
       fp = |Pred_set - GT_set|
       fn = |GT_set - Pred_set|
       precision = tp / (tp + fp)
       recall    = tp / (tp + fn)
       f1 = 2*P*R / (P+R)   ← 논문 24.88% 라인
       (per-task f1 도 average_f1 로 별도 report)

  키 규약:
    airline / retail  : ground_truth = {task_id: set(redundant_step_idx)}
    telecom           : dict-keyed 방식 (dataset 정의상 미묘하게 다름 — 지금은 무시)

  우리가 필요한 것:
    - RB messages → Clew Trace 변환 (신규 어댑터 필요)
    - 우리 waste_span_ids → 각 span 의 turn_idx (= message index) 로 역매핑
    - {task_id: set(waste_turn_idx)} 형태로 dump
    - evaluate.py 의 evaluate_standard() 호출하거나 동일 계산 재현

  주의:
    - 우리 3단 게이트는 tool 메시지의 output_text sha256 비교. RB 라벨은
      **step_idx (turn_idx)** 단위 — assistant 콜 + tool 결과가 두 idx.
      우리 waste_span 은 tool 스팬 1개 → turn_idx 는 result 쪽 하나.
      annotation 은 assistant 콜 + tool 결과 pair 를 모두 label 하는 관례
      (airline task=1 예: [6,7,10,11,12,13,8,9,16,17,18,19] — 짝수/홀수 페어).
      → 우리 waste tool span 의 turn_idx 를 예측으로 넣을 때 어사이니 idx (예: 5→[4,5])
        확장할지 결정 필요. 사전등록 시 명시.
""")


def main() -> None:
    print(f"입력 root: {ROOT}")
    print()
    q1_repo_structure()
    q2_label_structure()
    q3_trajectory_format()
    q3b_user_initiated_tool_calls()
    q4_scale()
    q5_evaluation()


if __name__ == "__main__":
    main()
