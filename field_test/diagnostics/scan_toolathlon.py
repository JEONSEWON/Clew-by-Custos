"""field_test/diagnostics/scan_toolathlon.py

Toolathlon 108 트레이스 전량 스캔. §23.7 결과 산출용.

- iter_toolathlon_traces 로 전 라인 Trace 화 → find_candidates(N=2), cascade(φ, N)
- 예측 (§23.5) vs 실측 비교. 결론 없음, raw 만.
- 진단 스크립트 커밋 금지 규칙 준수 (docs 결과만 §23.7 로 기록).

Usage:
    python field_test/diagnostics/scan_toolathlon.py data/toolathlon/claude-4.5-sonnet-0929_1.jsonl
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
REV = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
CACHE_DIR = Path.home() / ".cache/clew/embeddings"
PHI = 0.514345
N = 2


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> None:
    from clew.detect.cascade import cascade
    from clew.detect.semantic import Embedder
    from clew.detect.structural import find_candidates
    # 어댑터 내부 헬퍼 사용 — 스캔은 라인별 예외를 잡아야 108개 중 1개 실패로 전체 멈추면 안 됨.
    # (§21.4 은 어댑터 계약; 여기 상위 스캔은 명시적으로 라인별 회복.)
    from clew.ingest.toolathlon import _build_trace_from_entry, _iter_raw_lines

    path = Path(sys.argv[1])
    print(f"입력: {path}")
    print(f"φ={PHI}  N={N}  model={MODEL}@{REV[:7]}")
    print()

    t0 = time.perf_counter()
    embedder = Embedder(model_name=MODEL, revision=REV, cache_dir=CACHE_DIR)

    per_trace = []
    parse_errors: list[tuple[int, str]] = []

    tid = 0
    for lineno, entry in _iter_raw_lines(path):
        tid += 1
        try:
            trace = _build_trace_from_entry(entry, lineno)
        except Exception as e:  # noqa: BLE001
            parse_errors.append((lineno, f"[build] {type(e).__name__}: {e}"))
            continue
        try:
            cands = find_candidates(trace, N)
            res = cascade(trace, embedder, N, PHI)
            per_trace.append({
                "idx": tid,
                "trace_id": trace.trace_id,
                "task_name": trace.metadata.get("task_name"),
                "task_status": trace.metadata.get("task_status", {}),
                "spans": len(trace.spans),
                "tool_spans": sum(1 for s in trace.spans if s.span_kind == "tool"),
                "cands": cands,
                "waste_ids": list(res.waste_span_ids),
                "trace": trace,
            })
        except Exception as e:  # noqa: BLE001
            parse_errors.append((lineno, f"[detect] {type(e).__name__}: {e}"))

    print("=" * 78)
    print("Step A. 로드 요약")
    print("=" * 78)
    print(f"총 트레이스 (파일 라인 수): {tid}")
    print(f"성공적으로 cascade 실행    : {len(per_trace)}")
    print(f"cascade 중 예외            : {len(parse_errors)}")
    for i, err in parse_errors[:20]:
        print(f"  line#{i}: {err}")

    # task_status.evaluation 분포
    eval_dist: dict[str, int] = {}
    for r in per_trace:
        ev = r["task_status"].get("evaluation") if isinstance(r["task_status"], dict) else None
        eval_dist[str(ev)] = eval_dist.get(str(ev), 0) + 1
    print(f"\ntask_status.evaluation 분포:")
    for k, v in sorted(eval_dist.items()):
        print(f"  {k!r}: {v}")

    tot_spans = sum(r["spans"] for r in per_trace)
    tot_tool = sum(r["tool_spans"] for r in per_trace)
    tot_cands = sum(len(r["cands"]) for r in per_trace)
    tot_waste = sum(len(r["waste_ids"]) for r in per_trace)

    # --- Step B ---
    print()
    print("=" * 78)
    print("Step B. 전 트레이스 요약")
    print("=" * 78)
    print(f"총 spans        : {tot_spans}")
    print(f"총 tool spans   : {tot_tool}")
    print(f"총 repeat 후보 (구조 게이트 N=2): {tot_cands}")
    print(f"총 waste (sha256 게이트 통과)  : {tot_waste}")

    # --- Step C — 예측 (§23.5) vs 실측 ---
    print()
    print("=" * 78)
    print("Step C. §23.5 예측 vs 실측")
    print("=" * 78)
    print(f"  repeat 후보           : 예측 150-177   실측 {tot_cands}")
    print(f"  sha256 게이트 통과     : 예측 25-35     실측 {tot_waste}")
    print(f"  waste 최종            : 예측 25-35     실측 {tot_waste}")

    # --- Step D — waste > 0 트레이스 상세 (top 부터) ---
    print()
    print("=" * 78)
    print("Step D. waste > 0 트레이스")
    print("=" * 78)
    hit = [r for r in per_trace if r["waste_ids"]]
    hit_sorted = sorted(hit, key=lambda r: len(r["waste_ids"]), reverse=True)
    print(f"waste > 0 트레이스 수: {len(hit)}")

    for r in hit_sorted[:20]:
        n_w = len(r["waste_ids"])
        ev = r["task_status"].get("evaluation") if isinstance(r["task_status"], dict) else None
        print(f"\n--- trace_id={r['trace_id'][:20]}  task={r['task_name']!r}  eval={ev!r}  waste={n_w} ---")
        trace = r["trace"]
        waste_id_set = set(r["waste_ids"])
        for o, c in r["cands"]:
            if c.span_id not in waste_id_set:
                continue
            oh = _sha256(o.output_text)
            ch = _sha256(c.output_text)
            # args head 80
            args_head = c.input_text[:80]
            out_head = c.output_text[:120].replace("\n", "\\n")
            print(f"  waste: {c.agent_or_node_id!r}")
            print(f"    args head80 : {args_head!r}")
            print(f"    out  head120: {out_head!r}")
            print(f"    sha256 origin: {oh}")
            print(f"    sha256 cand  : {ch}")
            print(f"    equal        : {oh == ch}")

    # --- Step E — args='' 카운트 (playwright next_span 등) ---
    print()
    print("=" * 78)
    print("Step E. waste 중 args='' 또는 args='{}' 분포")
    print("=" * 78)
    empty_args_waste: dict[tuple[str, str], int] = {}
    nonempty_args_waste: dict[str, int] = {}
    for r in per_trace:
        waste_id_set = set(r["waste_ids"])
        for _o, c in r["cands"]:
            if c.span_id not in waste_id_set:
                continue
            args_norm = c.input_text.strip()
            if args_norm in ("", "{}"):
                key = (c.agent_or_node_id, args_norm)
                empty_args_waste[key] = empty_args_waste.get(key, 0) + 1
            else:
                nonempty_args_waste[c.agent_or_node_id] = nonempty_args_waste.get(c.agent_or_node_id, 0) + 1
    empty_sum = sum(empty_args_waste.values())
    nonempty_sum = sum(nonempty_args_waste.values())
    print(f"waste 중 args=''/'{{}}' 건수 : {empty_sum}")
    for (tool, args), cnt in sorted(empty_args_waste.items(), key=lambda kv: -kv[1]):
        print(f"    - {tool!r}  args={args!r}  count={cnt}")
    print(f"\nwaste 중 args 있음        : {nonempty_sum}")
    for tool, cnt in sorted(nonempty_args_waste.items(), key=lambda kv: -kv[1])[:15]:
        print(f"    - {tool!r}  count={cnt}")

    # --- Step F — evaluation 별 waste 분포 ---
    print()
    print("=" * 78)
    print("Step F. evaluation 별 waste 분포")
    print("=" * 78)
    per_eval: dict[str, dict] = {}
    for r in per_trace:
        ev = r["task_status"].get("evaluation") if isinstance(r["task_status"], dict) else None
        b = per_eval.setdefault(str(ev), {"traces": 0, "cands": 0, "waste": 0, "waste_traces": 0})
        b["traces"] += 1
        b["cands"] += len(r["cands"])
        b["waste"] += len(r["waste_ids"])
        if r["waste_ids"]:
            b["waste_traces"] += 1
    for ev, b in sorted(per_eval.items()):
        print(f"  eval={ev!r:>10}  traces={b['traces']:>4}  cands={b['cands']:>4}  "
              f"waste={b['waste']:>4}  waste_traces={b['waste_traces']:>4}")

    elapsed = time.perf_counter() - t0
    print()
    print("=" * 78)
    print(f"wall time: {elapsed:.1f}s")
    print("=" * 78)


if __name__ == "__main__":
    main()
