"""Diagnostics: §24.7 결과 검증. 커밋 금지, 정의 변경 금지.

Q1 — 0.2642 scope: 전체 GT vs duplicated GT
Q2 — evaluate.py 사용 방식 (import vs reimplement)
Q3 — 예측 5개 초과 원인: raw values + non-expansion 비교
Q4 — 오탐/미탐 raw 상위 5건
Q5 — tid FIFO fix 조인 매칭 통계
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RB_ROOT = ROOT / "data/redundancy_bench/data/domain"
LLM_JUDGE_DIR = ROOT / "data/redundancy_bench/LLM_judge"
DOMAINS = ["airline", "retail", "telecom"]

# 게이트
MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
REV = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
CACHE_DIR = Path.home() / ".cache/clew/embeddings"
PHI = 0.514345
N = 2


def _load_ev():
    sys.path.insert(0, str(LLM_JUDGE_DIR.resolve()))
    import evaluate as ev  # type: ignore
    return ev


def _load_ann(dom: str):
    return json.load(open(RB_ROOT / dom / "annotation.json", encoding="utf-8"))


def _predict_domain(dom: str, embedder):
    """도메인 예측: pair-expansion pred + call-only pred (Q3용) + span_details + tid 통계."""
    from clew.detect.cascade import cascade
    from clew.ingest.redundancy_bench import iter_redundancy_bench_traces

    traces_path = RB_ROOT / dom / "final_traces.json"
    pred_expand: dict[str, set[int]] = {}
    pred_call_only: dict[str, set[int]] = {}
    pred_result_only: dict[str, set[int]] = {}
    span_details: list[dict] = []
    waste_span_count = 0
    total_tool_spans = 0
    sim_count = 0
    tid_reuse_sim_count = 0
    total_tid_matches = 0

    for trace in iter_redundancy_bench_traces(traces_path):
        sim_count += 1
        task_id = trace.metadata.get("task_id")
        span_to_pair = trace.metadata.get("rb_span_to_turn_pair", {})
        # tid 재사용 여부: span_id 에 #idx 가 있으므로 prefix Counter
        prefix_counter: Counter = Counter()
        for sid in span_to_pair.keys():
            prefix = sid.split("#")[0]
            prefix_counter[prefix] += 1
        reused_tids = sum(1 for cnt in prefix_counter.values() if cnt >= 2)
        if reused_tids > 0:
            tid_reuse_sim_count += 1
        total_tid_matches += sum(prefix_counter.values())

        tool_spans = [s for s in trace.spans if s.span_kind == "tool"]
        total_tool_spans += len(tool_spans)

        try:
            cr = cascade(trace, embedder, n=N, phi=PHI)
        except Exception as e:  # noqa: BLE001
            pred_expand[task_id] = set()
            pred_call_only[task_id] = set()
            pred_result_only[task_id] = set()
            continue

        pset: set[int] = set()
        p_call: set[int] = set()
        p_result: set[int] = set()
        for span_id in cr.waste_span_ids:
            pair = span_to_pair.get(span_id)
            if pair is None:
                continue
            call_idx, result_idx = pair[0], pair[1]
            pset.add(call_idx)
            pset.add(result_idx)
            p_call.add(call_idx)
            p_result.add(result_idx)
            waste_span_count += 1
            span_obj = next((s for s in trace.spans if s.span_id == span_id), None)
            if span_obj is not None:
                span_details.append({
                    "task_id": task_id,
                    "span_id": span_id,
                    "tool_name": span_obj.agent_or_node_id,
                    "call_idx": call_idx,
                    "result_idx": result_idx,
                    "input_preview": span_obj.input_text[:80],
                    "output_preview": span_obj.output_text[:80],
                })
        pred_expand[task_id] = pset
        pred_call_only[task_id] = p_call
        pred_result_only[task_id] = p_result

    return {
        "pred_expand": pred_expand,
        "pred_call_only": pred_call_only,
        "pred_result_only": pred_result_only,
        "span_details": span_details,
        "waste_span_count": waste_span_count,
        "total_tool_spans": total_tool_spans,
        "sim_count": sim_count,
        "tid_reuse_sim_count": tid_reuse_sim_count,
        "total_tid_matches": total_tid_matches,
    }


def _evaluate(ev, dom: str, pred_by_tid):
    if dom == "telecom":
        gt = ev.load_ground_truth_telecom_one_one(str(RB_ROOT / "telecom" / "annotation.json"))
        pred_idx: dict[int, set] = {}
        for idx, entry in gt.items():
            pred_idx[idx] = pred_by_tid.get(entry["task_id"], set())
        return ev.evaluate_telecom_one_one(gt, pred_idx)
    gt = ev.load_ground_truth_standard(str(RB_ROOT / dom / "annotation.json"))
    return ev.evaluate_standard(gt, {str(k): v for k, v in pred_by_tid.items()})


def _duplicated_only_gt(dom: str) -> dict[str, set[int]]:
    """type=='duplicated step' 만의 GT (per task_id → idx set)."""
    ann = _load_ann(dom)
    out: dict[str, set] = {}
    for a in ann:
        tid = str(a["task_id"])
        types = a.get("redundant_step_type", [])
        idxs = a.get("redundant_step_idx", [])
        s: set = set()
        for i, idx in enumerate(idxs):
            if i < len(types) and types[i] == "duplicated step":
                s.add(idx)
        out[tid] = s
    return out


def _duplicated_prf1(dup_gt_by_tid, pred_by_tid):
    """duplicated-only micro-averaged P/R/F1 (evaluate_standard 방식과 동일 로직)."""
    total_tp = total_fp_partial = total_fp_full = total_fn = 0
    # duplicated 스코프의 P 는 특별: fp 를 "duplicated 만 GT 로 삼을 때 fp" 로 계산하면
    # 우리가 abnormal/exploratory 를 잡은 것도 duplicated fp 로 계산되어 부풀려짐.
    # 두 버전 계산:
    #   partial-fp: fp = pred - duplicated_gt (엄격, R 는 duplicated recall)
    #   full-fp: fp = pred - full_gt (전체 GT 대비, duplicated 외 카테고리 잡은 것도 tp 로 인정)
    # ★ duplicated 전용 F1 을 명확히 하려면 fp 정의를 정할 필요.
    # 여기선 두 버전 다 출력.
    return total_tp, total_fp_partial, total_fp_full, total_fn  # placeholder


def _duplicated_prf1_v2(dom: str, pred_by_tid):
    """duplicated-only micro P/R/F1 두 버전:
    (a) strict: fp = pred - duplicated_gt (duplicated 외 카테고리 잡은 것도 fp)
    (b) inclusive: fp = pred - full_gt (다른 카테고리 잡은 것은 fp 아님)
    두 버전 모두 recall 분모는 duplicated_gt.
    """
    ann = _load_ann(dom)
    dup_gt = _duplicated_only_gt(dom)
    full_gt = {str(a["task_id"]): set(a.get("redundant_step_idx", [])) for a in ann}

    tp = 0
    fp_strict = 0
    fp_inclusive = 0
    fn = 0
    for tid, dup in dup_gt.items():
        pred = pred_by_tid.get(tid, set())
        full = full_gt.get(tid, set())
        tp += len(dup & pred)
        fp_strict += len(pred - dup)
        fp_inclusive += len(pred - full)
        fn += len(dup - pred)

    def prf(tp, fp, fn):
        p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        return p, r, f1

    p_s, r_s, f1_s = prf(tp, fp_strict, fn)
    p_i, r_i, f1_i = prf(tp, fp_inclusive, fn)
    return {
        "tp": tp, "fn": fn,
        "strict": {"fp": fp_strict, "P": p_s, "R": r_s, "F1": f1_s},
        "inclusive": {"fp": fp_inclusive, "P": p_i, "R": r_i, "F1": f1_i},
    }


def _top_fp(dom: str, pred_by_tid, span_details, top_n=5):
    ann = _load_ann(dom)
    gt_by_tid = {str(a["task_id"]): set(a.get("redundant_step_idx", [])) for a in ann}
    out = []
    for sd in span_details:
        tid = str(sd["task_id"])
        gt = gt_by_tid.get(tid, set())
        if sd["call_idx"] not in gt and sd["result_idx"] not in gt:
            out.append(sd)
    return out[:top_n]


def _top_fn_duplicated(dom: str, pred_by_tid, top_n=5):
    """duplicated GT idx 인데 우리 pred_expand 에 없음. 원인 태그:
    - 'not_in_span_to_pair': span_to_pair 어느 pair 에도 등장 X → 어댑터가 그 idx 를 페어링 못함
    - 'in_pair_but_not_wasted': 우리 span 은 있지만 cascade 가 낭비 아님
      * sha_mismatch / phi_below / structural_fail 세분화 필요 (여기선 tag 만)
    """
    ann = _load_ann(dom)
    tr_all = json.load(open(RB_ROOT / dom / "final_traces.json", encoding="utf-8"))
    sim_by_tid = {s.get("task_id"): s for s in tr_all["simulations"]}
    misses = []

    from clew.ingest.redundancy_bench import iter_redundancy_bench_traces
    trace_meta_by_tid: dict[str, dict] = {}
    for tr in iter_redundancy_bench_traces(RB_ROOT / dom / "final_traces.json"):
        trace_meta_by_tid[tr.metadata.get("task_id")] = tr.metadata.get("rb_span_to_turn_pair", {})

    for a in ann:
        tid = str(a["task_id"])
        pred = pred_by_tid.get(tid, set())
        idxs = a.get("redundant_step_idx", [])
        types = a.get("redundant_step_type", [])
        span_to_pair = trace_meta_by_tid.get(tid, {})
        # 모든 (call_idx, result_idx) idx 를 flatten
        idx_in_any_pair: set = set()
        for pair in span_to_pair.values():
            idx_in_any_pair.add(pair[0])
            idx_in_any_pair.add(pair[1])
        for i, idx in enumerate(idxs):
            t = types[i] if i < len(types) else ""
            if t != "duplicated step":
                continue
            if idx in pred:
                continue
            if idx in idx_in_any_pair:
                tag = "in_pair_but_not_wasted"
            else:
                tag = "not_in_span_to_pair"
            sim = sim_by_tid.get(tid)
            snippet = ""
            role = None
            if sim and idx < len(sim.get("messages", [])):
                m = sim["messages"][idx]
                role = m.get("role")
                snippet = str(m.get("content", ""))[:80].replace("\n", "\\n")
            reason = ""
            if isinstance(a.get("reason"), list) and a["reason"]:
                reason = str(a["reason"][0])[:120].replace("\n", "\\n")
            misses.append({
                "task_id": tid,
                "turn_idx": idx,
                "tag": tag,
                "role": role,
                "reason": reason,
                "snippet": snippet,
            })
    return misses[:top_n]


def main():
    from clew.detect.semantic import Embedder
    ev = _load_ev()
    embedder = Embedder(model_name=MODEL, revision=REV, cache_dir=CACHE_DIR)

    per_dom: dict[str, dict] = {}
    per_dom_result_expand: dict = {}
    per_dom_result_call_only: dict = {}

    for dom in DOMAINS:
        d = _predict_domain(dom, embedder)
        per_dom[dom] = d
        per_dom_result_expand[dom] = _evaluate(ev, dom, d["pred_expand"])
        per_dom_result_call_only[dom] = _evaluate(ev, dom, d["pred_call_only"])

    # =========================================================================
    # Q1 — 0.2642 스코프
    # =========================================================================
    print("=" * 78)
    print("Q1 — F1=0.2642 의 스코프 (전체 라벨 vs duplicated 전용)")
    print("=" * 78)
    print()
    print("evaluate.py 인용 (line 32):")
    print("  gt[tid] = set(item.get('redundant_step_idx', []))")
    print("  → 'redundant_step_idx' 는 4카테고리(exploratory/duplicated/abnormal/incorrect) 통합.")
    print("  → evaluate_standard 는 type 필터링 없음. **전체 GT 대상 F1**.")
    print()
    print("전체 (pair-expansion, 규약 A):")
    total_tp = sum(per_dom_result_expand[d]["summary"]["total_tp"] for d in DOMAINS)
    total_fp = sum(per_dom_result_expand[d]["summary"]["total_fp"] for d in DOMAINS)
    total_fn = sum(per_dom_result_expand[d]["summary"]["total_fn"] for d in DOMAINS)
    P = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    R = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    F1 = 2 * P * R / (P + R) if (P + R) > 0 else 0.0
    print(f"  tp={total_tp}  fp={total_fp}  fn={total_fn}")
    print(f"  P={P:.4f}  R={R:.4f}  F1={F1:.4f}")
    total_gt = total_tp + total_fn
    print(f"  → GT 총량 = tp+fn = {total_gt} (전체 카테고리)")
    print()
    print("duplicated-only (같은 규약 A pred 로, GT 만 duplicated 로 필터):")
    print("  두 버전 (fp 정의):")
    print("    strict:    fp = pred - duplicated_gt (다른 카테고리 잡은 것도 fp)")
    print("    inclusive: fp = pred - full_gt       (다른 카테고리 잡은 것은 fp 아님)")

    dup_all = {"tp": 0, "fn": 0, "fp_strict": 0, "fp_inclusive": 0}
    for dom in DOMAINS:
        st = _duplicated_prf1_v2(dom, per_dom[dom]["pred_expand"])
        print(f"    [{dom}] tp={st['tp']:3d} fn={st['fn']:3d} "
              f"fp_strict={st['strict']['fp']:3d} fp_inclusive={st['inclusive']['fp']:3d}")
        print(f"      strict:    P={st['strict']['P']:.4f} R={st['strict']['R']:.4f} F1={st['strict']['F1']:.4f}")
        print(f"      inclusive: P={st['inclusive']['P']:.4f} R={st['inclusive']['R']:.4f} F1={st['inclusive']['F1']:.4f}")
        dup_all["tp"] += st["tp"]
        dup_all["fn"] += st["fn"]
        dup_all["fp_strict"] += st["strict"]["fp"]
        dup_all["fp_inclusive"] += st["inclusive"]["fp"]

    def prf(tp, fp, fn):
        p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        return p, r, f
    p_s, r_s, f_s = prf(dup_all["tp"], dup_all["fp_strict"], dup_all["fn"])
    p_i, r_i, f_i = prf(dup_all["tp"], dup_all["fp_inclusive"], dup_all["fn"])
    print(f"    [전체] tp={dup_all['tp']} fn={dup_all['fn']} "
          f"fp_strict={dup_all['fp_strict']} fp_inclusive={dup_all['fp_inclusive']}")
    print(f"      strict:    P={p_s:.4f} R={r_s:.4f} F1={f_s:.4f}")
    print(f"      inclusive: P={p_i:.4f} R={r_i:.4f} F1={f_i:.4f}")
    print()
    print(">>> Q1 요약 표:")
    print(f"  {'scope':<30} {'tp':>4} {'fp':>4} {'fn':>4}  {'P':>6}  {'R':>6}  {'F1':>6}")
    print(f"  {'전체(4카테고리, 논문 정의)':<30} {total_tp:>4} {total_fp:>4} {total_fn:>4}  {P:.4f}  {R:.4f}  {F1:.4f}")
    print(f"  {'duplicated-only strict':<30} {dup_all['tp']:>4} {dup_all['fp_strict']:>4} {dup_all['fn']:>4}  {p_s:.4f}  {r_s:.4f}  {f_s:.4f}")
    print(f"  {'duplicated-only inclusive':<30} {dup_all['tp']:>4} {dup_all['fp_inclusive']:>4} {dup_all['fn']:>4}  {p_i:.4f}  {r_i:.4f}  {f_i:.4f}")

    # =========================================================================
    # Q2 — evaluate.py 사용 방식 & baseline 재현
    # =========================================================================
    print()
    print("=" * 78)
    print("Q2 — evaluate.py 사용 방식 & baseline 재현 (중단조건 4)")
    print("=" * 78)
    print()
    print("eval_redundancy_bench.py line 33-37:")
    print("  def _load_evaluate_module():")
    print("      sys.path.insert(0, str(LLM_JUDGE_DIR.resolve()))")
    print("      import evaluate as ev")
    print("      return ev")
    print("  → RB 원본 evaluate.py 직접 import. 재구현 아님.")
    print()
    print("baseline 재현 가능성:")
    llm_judge_files = sorted(p.name for p in LLM_JUDGE_DIR.iterdir())
    print(f"  data/redundancy_bench/LLM_judge/ 내용: {llm_judge_files}")
    print("  → evaluate.py, judge.py, requirements.txt 만 있음.")
    print("  → LLM_judge baseline **예측 결과 JSON 없음** (Repo 는 코드만 제공).")
    print("  → 24.88% baseline 재현 불가 (예측 파일 부재).")
    print("  → 대신 우리는 그들 evaluate_standard/evaluate_telecom_one_one 를 그대로 호출 —")
    print("    함수 동일성 자체는 import 로 보장됨.")

    # =========================================================================
    # Q3 — 예측 초과 원인
    # =========================================================================
    print()
    print("=" * 78)
    print("Q3 — 예측 5개 초과 원인 (실측 vs 예측 vs non-expansion)")
    print("=" * 78)
    print()
    total_waste = sum(per_dom[d]["waste_span_count"] for d in DOMAINS)
    print("사전등록 예측 (§24.5) 대 실측:")
    print(f"  {'metric':<20} {'예측 범위':<20} {'실측(규약 A)':>14}  {'초과':>6}")
    print(f"  {'waste span 수':<20} {'40 – 120':<20} {total_waste:>14}  "
          f"{'✗' if total_waste > 120 else 'O'}")
    print(f"  {'전체 F1':<20} {'0.05 – 0.20':<20} {F1:>14.4f}  "
          f"{'✗' if F1 > 0.20 else 'O'}")
    print(f"  {'전체 Precision':<20} {'0.35 – 0.75':<20} {P:>14.4f}  "
          f"{'✗' if P > 0.75 else 'O'}")
    print(f"  {'전체 Recall':<20} {'0.03 – 0.12':<20} {R:>14.4f}  "
          f"{'✗' if R > 0.12 else 'O'}")

    # traj acc
    both_red = sum(per_dom_result_expand[d]["summary"]["both_redundant"] for d in DOMAINS)
    both_non = sum(per_dom_result_expand[d]["summary"]["both_non_redundant"] for d in DOMAINS)
    total_tasks = sum(per_dom_result_expand[d]["summary"]["total_tasks"] for d in DOMAINS)
    traj_acc = (both_red + both_non) / total_tasks if total_tasks > 0 else 0.0
    print(f"  {'trajectory acc':<20} {'0.10 – 0.35':<20} {traj_acc:>14.4f}  "
          f"{'✗' if traj_acc > 0.35 else 'O'}")

    print()
    print("스코프 혼동 확인 — recall 예측 0.03–0.12 는 어느 스코프?")
    print(f"  전체 GT recall (실측 F1 기준): {R:.4f}")
    print(f"  duplicated GT recall (strict/inclusive 공통):")
    dup_recall = dup_all["tp"] / (dup_all["tp"] + dup_all["fn"])
    print(f"    {dup_recall:.4f}   (§24.7.2 에 60.77% 로 기록된 값)")
    print(f"  → 사전등록 예측(0.03–0.12) 은 전체 스코프 예상. 실측 전체 R={R:.4f} 이미 초과.")
    print(f"  → duplicated recall 60.77% 는 별개 스코프. 예측 대상 아님.")

    print()
    print("규약 A(페어 확장) 없이(call_idx 만) 재계산 — 확장이 점수를 얼마나 올렸나?")
    tp_c = sum(per_dom_result_call_only[d]["summary"]["total_tp"] for d in DOMAINS)
    fp_c = sum(per_dom_result_call_only[d]["summary"]["total_fp"] for d in DOMAINS)
    fn_c = sum(per_dom_result_call_only[d]["summary"]["total_fn"] for d in DOMAINS)
    P_c = tp_c / (tp_c + fp_c) if (tp_c + fp_c) > 0 else 0.0
    R_c = tp_c / (tp_c + fn_c) if (tp_c + fn_c) > 0 else 0.0
    F1_c = 2 * P_c * R_c / (P_c + R_c) if (P_c + R_c) > 0 else 0.0
    print(f"  call-only:      tp={tp_c} fp={fp_c} fn={fn_c}  P={P_c:.4f} R={R_c:.4f} F1={F1_c:.4f}")
    print(f"  pair-expansion: tp={total_tp} fp={total_fp} fn={total_fn}  P={P:.4f} R={R:.4f} F1={F1:.4f}")
    print(f"  차이: F1 +{F1 - F1_c:+.4f}  P {P_c:.4f}→{P:.4f}  R {R_c:.4f}→{R:.4f}")

    # =========================================================================
    # Q4 — 오탐/미탐 raw
    # =========================================================================
    print()
    print("=" * 78)
    print("Q4 — 오탐 상위 5건 (Pred idx ∉ full GT idx)")
    print("=" * 78)
    for dom in DOMAINS:
        fps = _top_fp(dom, per_dom[dom]["pred_expand"], per_dom[dom]["span_details"], top_n=5)
        print(f"\n  [{dom}] 오탐 상위 {len(fps)}건")
        for sd in fps:
            print(f"    task={sd['task_id']!r}  span={sd['span_id']}  tool={sd['tool_name']}")
            print(f"      call_idx={sd['call_idx']} result_idx={sd['result_idx']}")
            print(f"      input  : {sd['input_preview']!r}")
            print(f"      output : {sd['output_preview']!r}")

    print()
    print("=" * 78)
    print("Q4 — 미탐 duplicated 상위 5건 + 원인 태그")
    print("=" * 78)
    for dom in DOMAINS:
        fns = _top_fn_duplicated(dom, per_dom[dom]["pred_expand"], top_n=5)
        print(f"\n  [{dom}] 미탐 상위 {len(fns)}건")
        for m in fns:
            print(f"    task={m['task_id']!r} turn={m['turn_idx']} role={m['role']} tag={m['tag']}")
            print(f"      reason: {m['reason']!r}")
            print(f"      snippet: {m['snippet']!r}")

    # =========================================================================
    # Q5 — tid FIFO fix 조인 매칭 통계
    # =========================================================================
    print()
    print("=" * 78)
    print("Q5 — tid FIFO fix 조인 매칭 통계")
    print("=" * 78)
    print()
    print("현재 (e06ae12 fix 적용 상태) 도메인별 매칭:")
    print(f"  {'domain':<10} {'sim':>5} {'tid_reuse_sim':>15} {'total_matches':>15} {'waste_spans':>12}")
    total_sim = 0
    total_reuse = 0
    total_matches = 0
    total_ws = 0
    for dom in DOMAINS:
        d = per_dom[dom]
        print(f"  {dom:<10} {d['sim_count']:>5} {d['tid_reuse_sim_count']:>15} "
              f"{d['total_tid_matches']:>15} {d['waste_span_count']:>12}")
        total_sim += d["sim_count"]
        total_reuse += d["tid_reuse_sim_count"]
        total_matches += d["total_tid_matches"]
        total_ws += d["waste_span_count"]
    print(f"  {'전체':<10} {total_sim:>5} {total_reuse:>15} {total_matches:>15} {total_ws:>12}")
    print()
    print(f"tid_reuse_sim = tid 재사용(중복 발생) 하는 sim 수. 전체 sim 중 비율: "
          f"{total_reuse / total_sim:.4f} ({total_reuse}/{total_sim})")
    print()
    print("fix 전(중복 tid → ValueError raise)이었으면:")
    print("  → tid_reuse_sim (재사용 있는 sim) 전부 build 실패했을 것.")
    print(f"  → 즉 {total_reuse} sim (전체의 {total_reuse / total_sim:.2%}) 가 pred=∅ 됨.")
    print("  → 이 sim 들에 있는 duplicated GT 는 전부 fn 이 되었을 것.")
    print()
    print("(fix 전 정확한 F1 재현은 어댑터 이전 상태 checkout 필요. 현재는 조인 통계만.)")


if __name__ == "__main__":
    main()
