"""오탐 46건 전수 심층 분석 (Part 1).

각 fp 에 대해:
- (tool_name, input, output) 완전 동일 재호출인가? sha256 비교
- 그 재호출이 GT redundant_step_idx 의 다른 카테고리로 라벨됐나?
  (exploratory/abnormal/incorrect — duplicated 아닌 라벨)
- 어느 라벨에도 없는 순수 미라벨인가?
- 순수 미라벨 중 "동일 input + 동일 output + 창(N=2) 내 상태변화 없음" = 인간 놓침 후보

산출:
- 카테고리별 분류표
- 순수 미라벨 인간-놓침-후보 상위 5건 raw
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RB_ROOT = ROOT / "data/redundancy_bench/data/domain"
DOMAINS = ["airline", "retail", "telecom"]

MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
REV = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
CACHE_DIR = Path.home() / ".cache/clew/embeddings"
PHI = 0.514345
N = 2


def _sha(x: str) -> str:
    return hashlib.sha256(x.encode("utf-8")).hexdigest()[:12]


def _load_ann(dom: str):
    return json.load(open(RB_ROOT / dom / "annotation.json", encoding="utf-8"))


def _predict_domain(dom: str, embedder):
    from clew.detect.cascade import cascade
    from clew.ingest.redundancy_bench import iter_redundancy_bench_traces

    traces_path = RB_ROOT / dom / "final_traces.json"
    span_details: list[dict] = []
    trace_by_tid: dict[str, object] = {}

    for trace in iter_redundancy_bench_traces(traces_path):
        tid = trace.metadata.get("task_id")
        trace_by_tid[tid] = trace
        span_to_pair = trace.metadata.get("rb_span_to_turn_pair", {})
        try:
            cr = cascade(trace, embedder, n=N, phi=PHI)
        except Exception:
            continue
        span_by_id = {s.span_id: s for s in trace.spans}
        for span_id in cr.waste_span_ids:
            pair = span_to_pair.get(span_id)
            if pair is None:
                continue
            call_idx, result_idx = pair[0], pair[1]
            sp = span_by_id.get(span_id)
            if sp is None:
                continue
            span_details.append({
                "task_id": tid,
                "span_id": span_id,
                "tool_name": sp.agent_or_node_id,
                "call_idx": call_idx,
                "result_idx": result_idx,
                "input": sp.input_text,
                "output": sp.output_text,
            })
    return span_details, trace_by_tid


def _classify_fp(dom: str, span_details, trace_by_tid):
    """오탐 각 span 을 분류."""
    ann = _load_ann(dom)
    gt_full = {str(a["task_id"]): set(a.get("redundant_step_idx", [])) for a in ann}
    # per-tid per-idx type
    idx_type: dict[str, dict[int, str]] = {}
    for a in ann:
        tid = str(a["task_id"])
        types = a.get("redundant_step_type", [])
        idxs = a.get("redundant_step_idx", [])
        idx_type[tid] = {}
        for i, idx in enumerate(idxs):
            idx_type[tid][idx] = types[i] if i < len(types) else ""

    tr_all = json.load(open(RB_ROOT / dom / "final_traces.json", encoding="utf-8"))
    sim_by_tid = {s.get("task_id"): s for s in tr_all["simulations"]}

    classified: list[dict] = []
    for sd in span_details:
        tid = str(sd["task_id"])
        full_gt = gt_full.get(tid, set())
        # FP 판별: pair 확장 후 어느 idx 도 full_gt 에 없으면 fp
        if sd["call_idx"] in full_gt or sd["result_idx"] in full_gt:
            continue

        # 원본 재호출 탐색: 같은 sim 에서 이전에 동일 (tool_name, input) 이 있었나?
        sim = sim_by_tid.get(sd["task_id"])
        earlier_calls: list[dict] = []
        # 우리 어댑터가 만든 페어 순회
        trace = trace_by_tid.get(sd["task_id"])
        earlier_matches: list[dict] = []
        if trace is not None:
            span_to_pair = trace.metadata.get("rb_span_to_turn_pair", {})
            for other in trace.spans:
                if other.span_kind != "tool":
                    continue
                if other.span_id == sd["span_id"]:
                    continue
                other_pair = span_to_pair.get(other.span_id)
                if not other_pair:
                    continue
                other_call = other_pair[0]
                if other_call >= sd["call_idx"]:
                    continue
                if (other.agent_or_node_id == sd["tool_name"]
                        and other.input_text == sd["input"]):
                    earlier_matches.append({
                        "span_id": other.span_id,
                        "call_idx": other_call,
                        "result_idx": other_pair[1],
                        "output_equal": other.output_text == sd["output"],
                        "output_sha_eq": _sha(other.output_text) == _sha(sd["output"]),
                    })

        # GT 다른 라벨 여부
        other_label = None
        for i in (sd["call_idx"], sd["result_idx"]):
            lab = idx_type.get(tid, {}).get(i)
            if lab:
                other_label = lab
                break

        # 창(N=2) 내 상태 변화 검사: 이전 동일 호출과 우리 호출 사이 다른 tool call 이 있는가
        # (사이 다른 assistant/tool 이 있으면 상태변화 후보)
        between_actions: list[dict] = []
        if earlier_matches and sim is not None:
            latest_prior = max(earlier_matches, key=lambda e: e["result_idx"])
            prior_result_idx = latest_prior["result_idx"]
            for j in range(prior_result_idx + 1, sd["call_idx"]):
                msg = sim["messages"][j]
                if msg.get("role") == "assistant" and msg.get("tool_calls"):
                    between_actions.append({
                        "idx": j,
                        "role": "assistant",
                        "tool_call_names": [tc.get("name") for tc in msg.get("tool_calls", [])],
                    })
                elif msg.get("role") == "tool":
                    between_actions.append({
                        "idx": j,
                        "role": "tool",
                        "tool_name": msg.get("name"),
                        "requestor": msg.get("requestor"),
                    })

        classified.append({
            "domain": dom,
            "task_id": tid,
            "span_id": sd["span_id"],
            "tool_name": sd["tool_name"],
            "call_idx": sd["call_idx"],
            "result_idx": sd["result_idx"],
            "input_preview": sd["input"][:120],
            "output_preview": sd["output"][:120],
            "input_sha": _sha(sd["input"]),
            "output_sha": _sha(sd["output"]),
            "earlier_matches": earlier_matches,
            "other_label": other_label,
            "between_actions_count": len(between_actions),
            "between_actions_preview": between_actions[:3],
        })
    return classified


def main():
    from clew.detect.semantic import Embedder
    embedder = Embedder(model_name=MODEL, revision=REV, cache_dir=CACHE_DIR)

    all_classified: list[dict] = []
    for dom in DOMAINS:
        sd, trace_by_tid = _predict_domain(dom, embedder)
        cls = _classify_fp(dom, sd, trace_by_tid)
        all_classified.extend(cls)

    total_fp = len(all_classified)
    print("=" * 78)
    print(f"오탐(fp) 전수 = {total_fp}")
    print("=" * 78)

    # 분류 카운트
    same_io = [c for c in all_classified if any(m["output_equal"] for m in c["earlier_matches"])]
    diff_output = [c for c in all_classified if c["earlier_matches"] and not any(m["output_equal"] for m in c["earlier_matches"])]
    no_prior = [c for c in all_classified if not c["earlier_matches"]]
    labeled_other = [c for c in all_classified if c["other_label"]]
    pure_unlabeled = [c for c in all_classified if not c["other_label"]]

    # 인간 놓침 후보: 동일 input + 동일 output + 다른 라벨 없음 + 사이 상태변화 tool call 없음
    human_missed_candidates = [
        c for c in all_classified
        if any(m["output_equal"] for m in c["earlier_matches"])
        and not c["other_label"]
        and c["between_actions_count"] == 0
    ]

    print()
    print(f"  earlier match (동일 name+input 이전 존재):    {len(all_classified) - len(no_prior)}/{total_fp}")
    print(f"    - 동일 name+input+output (완전 재현):        {len(same_io)}/{total_fp}")
    print(f"    - 동일 name+input 이나 output 다름:          {len(diff_output)}/{total_fp}")
    print(f"  earlier match 없음:                          {len(no_prior)}/{total_fp}")
    print()
    print(f"  GT 다른 카테고리 라벨됨:                     {len(labeled_other)}/{total_fp}")
    if labeled_other:
        lc = Counter(c["other_label"] for c in labeled_other)
        for k, v in lc.items():
            print(f"    - {k}: {v}")
    print(f"  순수 미라벨 (어느 카테고리에도 없음):        {len(pure_unlabeled)}/{total_fp}")
    print()
    print(f"  인간 놓침 후보 (동일 io + 미라벨 + 창 내 상태변화 0): {len(human_missed_candidates)}/{total_fp}")

    print()
    print("=" * 78)
    print("도메인별 브레이크다운")
    print("=" * 78)
    print(f"  {'domain':<10} {'fp':>4} {'same_io':>8} {'diff_out':>9} {'no_prior':>9} "
          f"{'other_lab':>10} {'pure_unl':>9} {'human_miss':>11}")
    for dom in DOMAINS:
        sub = [c for c in all_classified if c["domain"] == dom]
        s_same = sum(1 for c in sub if any(m["output_equal"] for m in c["earlier_matches"]))
        s_diff = sum(1 for c in sub if c["earlier_matches"] and not any(m["output_equal"] for m in c["earlier_matches"]))
        s_no = sum(1 for c in sub if not c["earlier_matches"])
        s_lab = sum(1 for c in sub if c["other_label"])
        s_pure = sum(1 for c in sub if not c["other_label"])
        s_hm = sum(
            1 for c in sub
            if any(m["output_equal"] for m in c["earlier_matches"])
            and not c["other_label"]
            and c["between_actions_count"] == 0
        )
        print(f"  {dom:<10} {len(sub):>4} {s_same:>8} {s_diff:>9} {s_no:>9} "
              f"{s_lab:>10} {s_pure:>9} {s_hm:>11}")

    print()
    print("=" * 78)
    print("인간 놓침 후보 상위 5건 raw")
    print("=" * 78)
    for i, c in enumerate(human_missed_candidates[:5], 1):
        em = c["earlier_matches"][0] if c["earlier_matches"] else None
        print(f"\n  #{i} [{c['domain']}] task={c['task_id']!r}")
        print(f"      span={c['span_id']}  tool={c['tool_name']}")
        print(f"      call_idx={c['call_idx']}  result_idx={c['result_idx']}")
        print(f"      input_sha={c['input_sha']}  output_sha={c['output_sha']}")
        if em:
            print(f"      earlier: span={em['span_id']} call={em['call_idx']} "
                  f"result={em['result_idx']} output_equal={em['output_equal']}")
        print(f"      between_actions_count={c['between_actions_count']}")
        print(f"      input : {c['input_preview']!r}")
        print(f"      output: {c['output_preview']!r}")

    print()
    print("=" * 78)
    print("다른 라벨(non-duplicated) 로 라벨된 fp 상위 5건 raw")
    print("=" * 78)
    for i, c in enumerate(labeled_other[:5], 1):
        print(f"\n  #{i} [{c['domain']}] task={c['task_id']!r}  other_label={c['other_label']!r}")
        print(f"      span={c['span_id']}  tool={c['tool_name']}")
        print(f"      call_idx={c['call_idx']}  result_idx={c['result_idx']}")
        print(f"      input : {c['input_preview']!r}")
        print(f"      output: {c['output_preview']!r}")

    print()
    print("=" * 78)
    print("earlier match 없는 fp (완전히 새 호출인데 낭비로 오분류) 상위 5건")
    print("=" * 78)
    for i, c in enumerate(no_prior[:5], 1):
        print(f"\n  #{i} [{c['domain']}] task={c['task_id']!r}")
        print(f"      span={c['span_id']}  tool={c['tool_name']}")
        print(f"      call_idx={c['call_idx']}  result_idx={c['result_idx']}")
        print(f"      other_label={c['other_label']!r}")
        print(f"      input : {c['input_preview']!r}")
        print(f"      output: {c['output_preview']!r}")


if __name__ == "__main__":
    main()
