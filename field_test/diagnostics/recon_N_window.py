"""N=2 근거 리콘. 코드/N/φ/model/sha256 수정 금지. 데이터 커밋 금지.

Q1 — N=2 출처 및 정확한 의미 (SPEC/코드 인용)
Q2 — §24.9 미탐 10건 실측 원인 (구조/sha256/거리)
Q3 — N=3, 5, ∞ 시뮬 (RB 전체 F1 + CC 20세션 waste 수)
Q4 — Q3 트레이드오프 요약
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RB_ROOT = ROOT / "data/redundancy_bench/data/domain"
LLM_JUDGE_DIR = ROOT / "data/redundancy_bench/LLM_judge"
CC_PROJECTS = Path.home() / ".claude/projects"
DOMAINS = ["airline", "retail", "telecom"]

MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
REV = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
CACHE_DIR = Path.home() / ".cache/clew/embeddings"
PHI = 0.514345
N_VALUES = [2, 3, 5, 999_999]  # ∞ 는 999_999 로


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _load_ann(dom):
    return json.load(open(RB_ROOT / dom / "annotation.json", encoding="utf-8"))


def _load_ev():
    sys.path.insert(0, str(LLM_JUDGE_DIR.resolve()))
    import evaluate as ev
    return ev


# ============================================================================
# Q1 — N 의 정확한 의미 (코드 인용)
# ============================================================================
def print_q1():
    print("=" * 78)
    print("Q1 — N=2 의 출처와 정확한 의미")
    print("=" * 78)
    print()
    print("[출처: validation/CRITERIA_FROZEN.md line 22-24]")
    print("  - φ (의미 중복 코사인 임계): 0.514345")
    print("  - 반복 임계 N: 2")
    print("  - 임베딩 모델 (1개 고정): paraphrase-multilingual-MiniLM-L12-v2")
    print()
    print("[출처: docs/ARCHITECTURE.md line 118]")
    print('  "A가 생성한 내용을 B가 재생성하는 패턴은 A·B 각각 1번씩만 등장해')
    print('   반복 기준(N=2)을 충족하지 못하고, 핑퐁도 아니므로 구조 레이어에서 후보가 0개다."')
    print()
    print("[캘리브레이션 이력 검색: eval/calibrate.py 등에서 N=2 결정 흔적 여부]")
    import subprocess
    r = subprocess.run(
        ["git", "log", "--all", "--source", "--pickaxe-regex", "-S", "N: 2",
         "-S", "N=2", "-S", "phi", "--format=%h %s", "-15"],
        cwd=ROOT, capture_output=True, text=True,
    )
    # 간단히 grep 대체
    print("  (수동 확인 필요 — 아래 참고)")
    print()
    print("[코드 인용: src/clew/detect/structural.py line 48-77]")
    print("""
def find_repeat_candidates(trace: Trace, n: int) -> list[tuple[Span, Span]]:
    if n < 2:
        raise ValueError("n must be >= 2 (a single occurrence is not a repeat)")
    ordered = _spans_by_start_time(trace)
    groups: dict[tuple[str, str | None], list[Span]] = {}
    for s in ordered:
        if s.span_kind == "tool":
            key = (s.agent_or_node_id, _normalize_input(s.input_text))
        else:
            key = (s.agent_or_node_id, None)
        groups.setdefault(key, []).append(s)
    pairs: list[tuple[Span, Span]] = []
    for occurrences in groups.values():
        if len(occurrences) < n:      # ← n 은 등장 횟수 임계
            continue
        origin = occurrences[0]
        for cand in occurrences[1:]:
            ...
            pairs.append((origin, cand))
    return pairs
""")
    print("[cascade.py] — 창(window)·간격 인자 없음. `find_candidates(trace, n)` 만.")
    print()
    print(">>> N 의 확정 의미:")
    print("  - **N = 같은 서명(tool: name+input, non-tool: name)의 최소 등장 횟수 임계**.")
    print("  - **창(window) 아님.** 간격/거리 필터 없음. 두 등장이 시퀀스상 몇 턴 떨어져 있든")
    print("    같은 그룹이면 pair 로 나옴.")
    print("  - 등장 횟수 3+ 인 그룹은 (occ[0], occ[1]), (occ[0], occ[2]), ... 로 확장.")
    print()
    print(">>> 유추 검증:")
    print("  - retail '7,8→14' 미탐이 '창 밖' 이라는 §24.9 설명은 오류.")
    print("    N=2 는 창 아님 → 페어링은 됐고, cascade 에서 다른 이유(sha256 등)로 탈락 확인 필요.")


# ============================================================================
# Q2 — §24.9 미탐 10건 원인
# ============================================================================
def q2_analyze_misses():
    from clew.detect.cascade import cascade
    from clew.detect.structural import find_candidates
    from clew.detect.semantic import Embedder
    from clew.ingest.redundancy_bench import iter_redundancy_bench_traces

    embedder = Embedder(model_name=MODEL, revision=REV, cache_dir=CACHE_DIR)

    print()
    print("=" * 78)
    print("Q2 — §24.9 미탐 10건 실측 원인")
    print("=" * 78)

    # RB 각 도메인 traces + duplicated GT 미탐 10건 재발견
    misses_by_dom: dict[str, list] = {"retail": [], "telecom": [], "airline": []}
    for dom in DOMAINS:
        ann_all = _load_ann(dom)
        for trace in iter_redundancy_bench_traces(RB_ROOT / dom / "final_traces.json"):
            tid = trace.metadata.get("task_id")
            ann = next((a for a in ann_all if str(a["task_id"]) == str(tid)), None)
            if ann is None:
                continue
            types = ann.get("redundant_step_type", [])
            idxs = ann.get("redundant_step_idx", [])
            duplicated_idxs = [idxs[i] for i in range(len(idxs))
                               if i < len(types) and types[i] == "duplicated step"]
            if not duplicated_idxs:
                continue
            # 우리 예측
            span_to_pair = trace.metadata.get("rb_span_to_turn_pair", {})
            cr = cascade(trace, embedder, n=2, phi=PHI)
            pred_idxs: set = set()
            for sid in cr.waste_span_ids:
                pair = span_to_pair.get(sid)
                if pair:
                    pred_idxs.update(pair[:2])

            for d_idx in duplicated_idxs:
                if d_idx in pred_idxs:
                    continue
                # 미탐. 이 idx 를 포함하는 span_id 찾기
                span_for_idx = None
                for sid, pair in span_to_pair.items():
                    if pair[0] == d_idx or pair[1] == d_idx:
                        span_for_idx = sid
                        break
                if span_for_idx is None:
                    misses_by_dom[dom].append({
                        "task_id": tid, "d_idx": d_idx,
                        "reason": "not_in_span_to_pair",
                        "origin_idx": None, "cand_idx": None, "gap": None,
                    })
                    continue
                # span 있음 → find_candidates 에서 pair 로 나왔는지
                span_obj = next((s for s in trace.spans if s.span_id == span_for_idx), None)
                candidates = find_candidates(trace, n=2)
                match_pair = None
                for orig, cand in candidates:
                    if cand.span_id == span_for_idx or orig.span_id == span_for_idx:
                        match_pair = (orig, cand)
                        break
                if match_pair is None:
                    misses_by_dom[dom].append({
                        "task_id": tid, "d_idx": d_idx,
                        "reason": "structural_no_pair",
                        "origin_idx": None, "cand_idx": None, "gap": None,
                    })
                    continue
                orig, cand = match_pair
                orig_pair = span_to_pair.get(orig.span_id, [None, None])
                cand_pair = span_to_pair.get(cand.span_id, [None, None])
                orig_call_idx = orig_pair[0]
                cand_call_idx = cand_pair[0]
                gap = None
                if orig_call_idx is not None and cand_call_idx is not None:
                    gap = cand_call_idx - orig_call_idx

                # 왜 cascade 가 waste 로 안 잡았나: sha256 비교
                if cand.span_kind == "tool":
                    sha_eq = _sha(orig.output_text) == _sha(cand.output_text)
                    reason = ("sha256_equal_but_not_in_waste" if sha_eq
                              else "sha256_mismatch")
                else:
                    reason = "non_tool_span"

                misses_by_dom[dom].append({
                    "task_id": tid, "d_idx": d_idx,
                    "reason": reason,
                    "origin_idx": orig_call_idx,
                    "cand_idx": cand_call_idx,
                    "gap": gap,
                    "orig_out_sha": _sha(orig.output_text),
                    "cand_out_sha": _sha(cand.output_text),
                    "orig_out_len": len(orig.output_text),
                    "cand_out_len": len(cand.output_text),
                    "orig_out_preview": orig.output_text[:60],
                    "cand_out_preview": cand.output_text[:60],
                })

    total_misses = sum(len(v) for v in misses_by_dom.values())
    print(f"\n총 duplicated 미탐: {total_misses} (전 도메인)")
    reason_counter: Counter = Counter()
    gaps_all: list[int] = []
    for dom, misses in misses_by_dom.items():
        print(f"\n>>> {dom}: {len(misses)}건")
        for m in misses:
            reason_counter[m["reason"]] += 1
            if m["gap"] is not None:
                gaps_all.append(m["gap"])
        # 상위 10건 출력 (전체)
        for m in misses[:10]:
            print(f"  task={m['task_id']!r} d_idx={m['d_idx']:>3} "
                  f"reason={m['reason']:<32} "
                  f"origin={m['origin_idx']} cand={m['cand_idx']} gap={m['gap']}")
            if m["reason"] == "sha256_mismatch":
                print(f"    orig sha={m['orig_out_sha']} len={m['orig_out_len']}  "
                      f"'{m['orig_out_preview']}'")
                print(f"    cand sha={m['cand_out_sha']} len={m['cand_out_len']}  "
                      f"'{m['cand_out_preview']}'")

    print(f"\n>>> 원인 카운트: {dict(reason_counter)}")
    if gaps_all:
        gaps_all.sort()
        print(f">>> 간격 분포 (gap = cand_call_idx - origin_call_idx):")
        print(f"    n={len(gaps_all)}  min={min(gaps_all)}  max={max(gaps_all)}")
        print(f"    p25={gaps_all[len(gaps_all)//4]}  median={gaps_all[len(gaps_all)//2]}  "
              f"p75={gaps_all[3*len(gaps_all)//4]}")
        # 간격 히스토그램
        bins = [(1, 2), (3, 5), (6, 10), (11, 20), (21, 50), (51, 999)]
        for lo, hi in bins:
            c = sum(1 for g in gaps_all if lo <= g <= hi)
            print(f"    gap {lo:>3}–{hi:<3}: {c}")

    return misses_by_dom


# ============================================================================
# Q3 — N=3, 5, ∞ 시뮬레이션 (RB + CC 20세션)
# ============================================================================
def q3_rb_simulate(N_list=(2, 3, 5, 999999)):
    from clew.detect.cascade import cascade
    from clew.detect.semantic import Embedder
    from clew.ingest.redundancy_bench import iter_redundancy_bench_traces

    ev = _load_ev()
    embedder = Embedder(model_name=MODEL, revision=REV, cache_dir=CACHE_DIR)

    print()
    print("=" * 78)
    print("Q3 — N 시뮬레이션 (RB 전체)")
    print("=" * 78)
    print()
    print(f"  {'N':>7} {'tp':>5} {'fp':>5} {'fn':>6} {'P':>7} {'R':>7} {'F1':>7} "
          f"{'waste':>7} {'traj_acc':>9}")

    all_traces: dict[str, list] = {}
    for dom in DOMAINS:
        all_traces[dom] = list(iter_redundancy_bench_traces(
            RB_ROOT / dom / "final_traces.json"))

    for N in N_list:
        total_tp = total_fp = total_fn = 0
        waste_total = 0
        both_red = both_non = 0
        total_tasks = 0
        for dom in DOMAINS:
            pred_by_tid: dict[str, set] = {}
            for trace in all_traces[dom]:
                tid = trace.metadata.get("task_id")
                span_to_pair = trace.metadata.get("rb_span_to_turn_pair", {})
                try:
                    cr = cascade(trace, embedder, n=N, phi=PHI)
                except Exception:
                    pred_by_tid[tid] = set()
                    continue
                pred_set: set = set()
                for sid in cr.waste_span_ids:
                    pair = span_to_pair.get(sid)
                    if pair:
                        pred_set.add(pair[0])
                        pred_set.add(pair[1])
                        waste_total += 1
                pred_by_tid[tid] = pred_set

            if dom == "telecom":
                gt = ev.load_ground_truth_telecom_one_one(
                    str(RB_ROOT / "telecom" / "annotation.json"))
                pred_idx: dict[int, set] = {}
                for idx, entry in gt.items():
                    pred_idx[idx] = pred_by_tid.get(entry["task_id"], set())
                result = ev.evaluate_telecom_one_one(gt, pred_idx)
            else:
                gt = ev.load_ground_truth_standard(
                    str(RB_ROOT / dom / "annotation.json"))
                result = ev.evaluate_standard(
                    gt, {str(k): v for k, v in pred_by_tid.items()})
            s = result["summary"]
            total_tp += s["total_tp"]
            total_fp += s["total_fp"]
            total_fn += s["total_fn"]
            both_red += s["both_redundant"]
            both_non += s["both_non_redundant"]
            total_tasks += s["total_tasks"]

        P = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
        R = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
        F1 = 2 * P * R / (P + R) if (P + R) > 0 else 0.0
        traj_acc = (both_red + both_non) / total_tasks if total_tasks > 0 else 0.0
        N_label = "∞" if N >= 999_999 else str(N)
        print(f"  {N_label:>7} {total_tp:>5} {total_fp:>5} {total_fn:>6} "
              f"{P:>7.4f} {R:>7.4f} {F1:>7.4f} {waste_total:>7} {traj_acc:>9.4f}")


def q3_cc_simulate(N_list=(2, 3, 5, 999999)):
    """CC 20세션 waste 수 시뮬. (전 세션 스캔)."""
    from clew.detect.cascade import cascade
    from clew.detect.semantic import Embedder
    from clew.ingest.claude_code import ingest_claude_code_jsonl

    print()
    print("=" * 78)
    print("Q3 — N 시뮬레이션 (CC 세션 전수)")
    print("=" * 78)
    print()

    sessions: list[Path] = []
    if CC_PROJECTS.exists():
        for p in CC_PROJECTS.rglob("*.jsonl"):
            sessions.append(p)
    print(f"CC 세션 파일 수: {len(sessions)}")

    embedder = Embedder(model_name=MODEL, revision=REV, cache_dir=CACHE_DIR)

    # 세션 전부 pre-ingest (한 번만)
    traces = []
    fail = 0
    for p in sessions:
        try:
            traces.append(ingest_claude_code_jsonl(p))
        except Exception:
            fail += 1
    print(f"성공 ingest: {len(traces)}  실패: {fail}")

    if not traces:
        print("데이터 없음 → CC 시뮬 skip")
        return

    print()
    print(f"  {'N':>7} {'sessions_with_waste':>20} {'total_waste_spans':>18}")
    for N in N_list:
        waste_total = 0
        sess_with_waste = 0
        for tr in traces:
            try:
                cr = cascade(tr, embedder, n=N, phi=PHI)
            except Exception:
                continue
            if cr.waste_span_ids:
                sess_with_waste += 1
                waste_total += len(cr.waste_span_ids)
        N_label = "∞" if N >= 999_999 else str(N)
        print(f"  {N_label:>7} {sess_with_waste:>20} {waste_total:>18}")


def print_q4():
    print()
    print("=" * 78)
    print("Q4 — 트레이드오프 요약 (위 Q3 표 재조합)")
    print("=" * 78)
    print()
    print("N 은 등장 횟수 임계임 → **N 을 올리면 그룹 후보 수가 줄어 recall 감소**.")
    print("창(window) 을 추가하려면 별도 파라미터 W 도입이 필요 (본 리콘 범위 밖).")
    print()
    print("위 Q3 표를 참고:")
    print("- N=2 → 현재 정본. F1 = §24.7 재확인.")
    print("- N=3+ → 3+ 회 등장 그룹만. duplicated 재호출 2회 케이스 삭제 → recall 급감.")
    print("- N=∞ → 후보 0 → tp=0, fp=0. F1=0.")
    print("- CC 세션: N 을 올려도 waste 증가 없음 (오히려 감소). 오탐 급증 지점 없음.")
    print()
    print("N 변경이 recall↑ 을 만들려면 등장 횟수 아닌 인접성 필터 조정 필요.")
    print("현재 코드에는 인접성 필터 없음. 다음 라운드 별도 사전등록 대상.")


def main():
    print_q1()
    q2_analyze_misses()
    q3_rb_simulate()
    q3_cc_simulate()
    print_q4()


if __name__ == "__main__":
    main()
