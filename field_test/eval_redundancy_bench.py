"""field_test/eval_redundancy_bench.py — §24.7 RB 전량 평가.

규약 A (§24.3, pair expansion): 각 waste span_id → (call_idx, result_idx) 두 idx 확장 → Pred_set.
논문 evaluate.py 를 그대로 import 해서 evaluate_standard(airline/retail), evaluate_telecom_one_one 호출.

산출:
1) 도메인별 + 전체 step-level P/R/F1 (overall)
2) trajectory-level redundancy_detection_accuracy
3) **duplicated 전용 recall** (§24.4 정직성 — 우리 게이트 주 타겟)
4) 카테고리별 recall (exploratory/abnormal/incorrect 참고)
5) 오탐 상위 5건 (Pred - GT)
6) 미탐 duplicated 상위 5건 (GT_duplicated - Pred)
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

RB_ROOT = Path("data/redundancy_bench/data/domain")
LLM_JUDGE_DIR = Path("data/redundancy_bench/LLM_judge")
DOMAINS = ["airline", "retail", "telecom"]

# 게이트 (frozen)
MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
REV = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
CACHE_DIR = Path.home() / ".cache/clew/embeddings"
PHI = 0.514345
N = 2


def _load_evaluate_module():
    """RB 원본 evaluate.py 를 그대로 import (재구현 없음)."""
    sys.path.insert(0, str(LLM_JUDGE_DIR.resolve()))
    import evaluate as ev  # type: ignore
    return ev


def _load_annotation(dom: str):
    return json.load(open(RB_ROOT / dom / "annotation.json", encoding="utf-8"))


def _build_typed_gt(ann_items):
    """annotation → (gt_set, per_type_gt_sets).

    per_type_gt_sets: {type_name: set(idx)} — 특정 type 만의 idx 세트.
    """
    gt_set = set()
    per_type: dict[str, set] = defaultdict(set)
    for i, idx in enumerate(ann_items.get("redundant_step_idx", [])):
        gt_set.add(idx)
        types = ann_items.get("redundant_step_type", [])
        if i < len(types) and types[i]:
            per_type[types[i]].add(idx)
    return gt_set, per_type


def _predict_domain(dom: str, embedder):
    """도메인 하나에 대해 어댑터 → cascade → 규약 A pred dict."""
    from clew.detect.cascade import cascade
    from clew.ingest.redundancy_bench import iter_redundancy_bench_traces

    traces_path = RB_ROOT / dom / "final_traces.json"
    pred_by_task_id: dict[str, set] = {}
    # (task_id, span_id, tool_name, call_idx, result_idx, input, output, origin_output) 저장 for post-mortem
    span_details: list[dict] = []
    total_spans = 0
    waste_spans_total = 0

    build_errors: list[tuple[str, str]] = []

    for trace in iter_redundancy_bench_traces(traces_path):
        task_id = trace.metadata.get("task_id")
        span_to_pair = trace.metadata.get("rb_span_to_turn_pair", {})
        try:
            cr = cascade(trace, embedder, n=N, phi=PHI)
        except Exception as e:  # noqa: BLE001
            build_errors.append((task_id, f"{type(e).__name__}: {e}"))
            pred_by_task_id[task_id] = set()
            continue
        total_spans += sum(1 for s in trace.spans if s.span_kind == "tool")
        pred_set: set[int] = set()
        for span_id in cr.waste_span_ids:
            pair = span_to_pair.get(span_id)
            if pair is None:
                continue
            call_idx, result_idx = pair[0], pair[1]
            pred_set.add(call_idx)
            pred_set.add(result_idx)
            waste_spans_total += 1
            # detail: tool span object 찾기
            span_obj = next((s for s in trace.spans if s.span_id == span_id), None)
            if span_obj is not None:
                span_details.append({
                    "task_id": task_id,
                    "span_id": span_id,
                    "tool_name": span_obj.agent_or_node_id,
                    "call_idx": call_idx,
                    "result_idx": result_idx,
                    "input_preview": span_obj.input_text[:120],
                    "output_preview": span_obj.output_text[:120],
                })
        pred_by_task_id[task_id] = pred_set

    return pred_by_task_id, span_details, total_spans, waste_spans_total, build_errors


def _evaluate_airline_retail(ev, dom: str, pred_by_task_id):
    gt = ev.load_ground_truth_standard(str(RB_ROOT / dom / "annotation.json"))
    # pred 를 str key 로 (evaluate_standard 가 str key 기대. gt 도 str.)
    pred = {str(k): v for k, v in pred_by_task_id.items()}
    return ev.evaluate_standard(gt, pred)


def _evaluate_telecom(ev, pred_by_task_id):
    """telecom 은 enumerate-index 기반 evaluator. task_id → idx 매핑."""
    gt = ev.load_ground_truth_telecom_one_one(str(RB_ROOT / "telecom" / "annotation.json"))
    # gt: {idx: {'task_id': str, 'redundant_step_idx': set}}
    # pred: {idx: set}
    pred_idx_keyed: dict[int, set] = {}
    for idx, entry in gt.items():
        tid = entry["task_id"]
        pred_idx_keyed[idx] = pred_by_task_id.get(tid, set())
    return ev.evaluate_telecom_one_one(gt, pred_idx_keyed)


def _duplicated_only_stats(dom: str, pred_by_task_id):
    """§24.4: duplicated 전용 recall + 카테고리별 recall."""
    ann = _load_annotation(dom)
    per_cat_gt: dict[str, set] = defaultdict(set)  # type → all idx
    per_cat_hit: dict[str, set] = defaultdict(set)
    per_cat_taskscope: dict[str, dict[str, set]] = defaultdict(dict)  # type → {tid: idx_set}

    for a in ann:
        tid = str(a["task_id"])
        pred_set = pred_by_task_id.get(tid, set())
        idxs = a.get("redundant_step_idx", [])
        types = a.get("redundant_step_type", [])
        for i, idx in enumerate(idxs):
            t = types[i] if i < len(types) else ""
            if not t:
                continue
            per_cat_gt[t].add((tid, idx))
            if idx in pred_set:
                per_cat_hit[t].add((tid, idx))
    return per_cat_gt, per_cat_hit


def _find_top_fp(dom: str, pred_by_task_id, span_details: list[dict], top_n: int = 5) -> list[dict]:
    """오탐 상위: pred idx 인데 GT 에 없음. task 별로 그런 span 찾기."""
    ann = _load_annotation(dom)
    gt_by_tid = {str(a["task_id"]): set(a.get("redundant_step_idx", [])) for a in ann}
    fp_spans: list[dict] = []
    for sd in span_details:
        tid = str(sd["task_id"])
        gt = gt_by_tid.get(tid, set())
        # span 이 pair-expansion 후 GT 와 겹치지 않는 경우
        if sd["call_idx"] not in gt and sd["result_idx"] not in gt:
            fp_spans.append(sd)
    return fp_spans[:top_n]


def _find_top_fn_duplicated(dom: str, pred_by_task_id, top_n: int = 5) -> list[dict]:
    """미탐 duplicated: type='duplicated step' 이지만 우리가 예측 못 함."""
    ann = _load_annotation(dom)
    tr_all = json.load(open(RB_ROOT / dom / "final_traces.json", encoding="utf-8"))
    sim_by_tid = {s.get("task_id"): s for s in tr_all["simulations"]}
    misses: list[dict] = []
    for a in ann:
        tid = str(a["task_id"])
        pred_set = pred_by_task_id.get(tid, set())
        idxs = a.get("redundant_step_idx", [])
        types = a.get("redundant_step_type", [])
        for i, idx in enumerate(idxs):
            t = types[i] if i < len(types) else ""
            if t != "duplicated step":
                continue
            if idx not in pred_set:
                sim = sim_by_tid.get(tid)
                snippet = ""
                if sim and idx < len(sim["messages"]):
                    m = sim["messages"][idx]
                    snippet = str(m.get("content", ""))[:80].replace("\n", "\\n")
                misses.append({
                    "task_id": tid,
                    "turn_idx": idx,
                    "role": sim["messages"][idx].get("role") if sim else None,
                    "reason": (a.get("reason", []) or [""])[0][:120] if a.get("reason") else "",
                    "snippet": snippet,
                })
                if len(misses) >= top_n * 3:  # 여유
                    break
        if len(misses) >= top_n * 3:
            break
    return misses[:top_n]


def main() -> None:
    from clew.detect.semantic import Embedder

    ev = _load_evaluate_module()
    embedder = Embedder(model_name=MODEL, revision=REV, cache_dir=CACHE_DIR)

    print("=" * 78)
    print(f"§24.7 RedundancyBench 평가 (φ={PHI}, N={N}, model={MODEL}@{REV[:8]}, 규약 A)")
    print("=" * 78)

    # 도메인별 실행
    per_dom_results: dict = {}
    per_dom_pred: dict[str, dict] = {}
    per_dom_spans: dict[str, list] = {}
    per_dom_stats: dict[str, dict] = {}
    build_error_all = []

    for dom in DOMAINS:
        print(f"\n>>> 도메인: {dom}")
        pred_by_tid, spans, total_spans, waste_spans_total, build_errs = _predict_domain(dom, embedder)
        per_dom_pred[dom] = pred_by_tid
        per_dom_spans[dom] = spans
        per_dom_stats[dom] = {
            "total_spans": total_spans,
            "waste_spans": waste_spans_total,
            "build_errors": len(build_errs),
        }
        build_error_all.extend(build_errs)
        if dom == "telecom":
            result = _evaluate_telecom(ev, pred_by_tid)
        else:
            result = _evaluate_airline_retail(ev, dom, pred_by_tid)
        per_dom_results[dom] = result
        s = result["summary"]
        print(f"  total_spans={total_spans}, waste_spans={waste_spans_total}, build_errors={len(build_errs)}")
        print(f"  step-level: P={s['overall_precision']:.4f}  R={s['overall_recall']:.4f}  F1={s['overall_f1']:.4f}")
        print(f"    tp={s['total_tp']} fp={s['total_fp']} fn={s['total_fn']}")
        print(f"  trajectory-level accuracy: {s['redundancy_detection_accuracy']:.4f}")
        print(f"    both_red={s['both_redundant']} both_non_red={s['both_non_redundant']} "
              f"gt_only={s['gt_redundant_only']} pred_only={s['pred_redundant_only']}")

    if build_error_all:
        print(f"\n[build 실패 총 {len(build_error_all)}건]")
        for tid, err in build_error_all[:5]:
            print(f"  task={tid!r} → {err}")

    # 종합 (도메인 합산 tp/fp/fn 로 재계산)
    print()
    print("=" * 78)
    print("전체 (3 도메인 합산)")
    print("=" * 78)
    total_tp = sum(per_dom_results[d]["summary"]["total_tp"] for d in DOMAINS)
    total_fp = sum(per_dom_results[d]["summary"]["total_fp"] for d in DOMAINS)
    total_fn = sum(per_dom_results[d]["summary"]["total_fn"] for d in DOMAINS)
    total_tasks = sum(per_dom_results[d]["summary"]["total_tasks"] for d in DOMAINS)
    both_red = sum(per_dom_results[d]["summary"]["both_redundant"] for d in DOMAINS)
    both_non = sum(per_dom_results[d]["summary"]["both_non_redundant"] for d in DOMAINS)
    gt_only = sum(per_dom_results[d]["summary"]["gt_redundant_only"] for d in DOMAINS)
    pred_only = sum(per_dom_results[d]["summary"]["pred_redundant_only"] for d in DOMAINS)
    ov_P = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    ov_R = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    ov_F1 = 2 * ov_P * ov_R / (ov_P + ov_R) if (ov_P + ov_R) > 0 else 0.0
    traj_acc = (both_red + both_non) / total_tasks if total_tasks > 0 else 0.0
    total_waste_spans = sum(per_dom_stats[d]["waste_spans"] for d in DOMAINS)
    total_spans = sum(per_dom_stats[d]["total_spans"] for d in DOMAINS)
    print(f"  total_spans={total_spans}  waste_spans={total_waste_spans}")
    print(f"  step-level: P={ov_P:.4f}  R={ov_R:.4f}  F1={ov_F1:.4f}")
    print(f"    tp={total_tp} fp={total_fp} fn={total_fn}")
    print(f"  trajectory-level accuracy: {traj_acc:.4f}  ({both_red+both_non}/{total_tasks})")
    print(f"    both_red={both_red} both_non={both_non} gt_only={gt_only} pred_only={pred_only}")

    # duplicated 전용
    print()
    print("=" * 78)
    print("§24.4 카테고리별 recall (참고 — 전체 F1 은 아님)")
    print("=" * 78)
    all_cat_gt: dict[str, int] = defaultdict(int)
    all_cat_hit: dict[str, int] = defaultdict(int)
    for dom in DOMAINS:
        per_cat_gt, per_cat_hit = _duplicated_only_stats(dom, per_dom_pred[dom])
        for cat in per_cat_gt:
            all_cat_gt[cat] += len(per_cat_gt[cat])
            all_cat_hit[cat] += len(per_cat_hit[cat])
        print(f"\n  [{dom}]")
        for cat in ("duplicated step", "abnormal step", "exploratory step", "incorrect step"):
            gtc = len(per_cat_gt.get(cat, set()))
            hit = len(per_cat_hit.get(cat, set()))
            r = hit / gtc if gtc > 0 else 0.0
            print(f"    {cat:20s}  hit={hit:>4}/{gtc:<4}  recall={r:.4f}")

    print("\n  [전체 카테고리별 recall]")
    for cat in ("duplicated step", "abnormal step", "exploratory step", "incorrect step"):
        gtc = all_cat_gt[cat]
        hit = all_cat_hit[cat]
        r = hit / gtc if gtc > 0 else 0.0
        print(f"    {cat:20s}  hit={hit:>4}/{gtc:<5}  recall={r:.4f}")

    # 오탐/미탐 상위 5
    print()
    print("=" * 78)
    print("오탐 상위 (Pred 이지만 GT 에 없음) — 도메인별 최대 5건")
    print("=" * 78)
    for dom in DOMAINS:
        fps = _find_top_fp(dom, per_dom_pred[dom], per_dom_spans[dom], top_n=5)
        print(f"\n  [{dom}] 오탐 span 상위 {len(fps)}")
        for sd in fps:
            print(f"    task={sd['task_id']!r}  span={sd['span_id']}  tool={sd['tool_name']}")
            print(f"      call_idx={sd['call_idx']} result_idx={sd['result_idx']}")
            print(f"      input:  {sd['input_preview']!r}")
            print(f"      output: {sd['output_preview']!r}")

    print()
    print("=" * 78)
    print("미탐 duplicated 상위 (GT type='duplicated step' 이지만 pred X) — 도메인별 최대 5건")
    print("=" * 78)
    for dom in DOMAINS:
        misses = _find_top_fn_duplicated(dom, per_dom_pred[dom], top_n=5)
        print(f"\n  [{dom}] 미탐 상위 {len(misses)}")
        for m in misses:
            print(f"    task={m['task_id']!r} turn={m['turn_idx']} role={m['role']}")
            print(f"      reason: {m['reason']!r}")
            print(f"      snippet: {m['snippet']!r}")


if __name__ == "__main__":
    main()
