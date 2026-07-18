"""Toolathlon 22모델 × 3런 전량 스캔.

기존 §23 어댑터 재사용 (수정 X). N=2 구조 게이트 + sha256 게이트.
CC-BY-4.0 데이터, 로컬 분석. 데이터 커밋 금지.

Step 1: HF 파일 목록 + 다운로드 상태 (별도 스크립트/셀에서 완료 가정)
Step 2: 전 파일 스캔 → 모델별·전체 요약
Step 3: 모델별 waste율 비교
Step 4: sha256 게이트 통과율 (모델별)
Step 5: tool 카테고리 분포 (전체 + 모델별)

Usage:
    python field_test/diagnostics/scan_toolathlon_17models.py data/toolathlon/hf
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

MODEL_EMBED = "paraphrase-multilingual-MiniLM-L12-v2"
REV = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
CACHE_DIR = Path.home() / ".cache/clew/embeddings"
PHI = 0.514345
N = 2

# analyze_toolathlon_waste.py 와 동일 세트 (재구현 X, 필요 시 복붙)
_READ_TOOLS = {
    "filesystem-read_file", "filesystem-list_directory", "filesystem-search_files",
    "github-get_file_contents", "github-list_commits", "github-get_issue",
    "pdf-tools-read_pdf_pages", "pdf-tools-get_pdf_info",
    "excel-read_data_from_excel",
    "snowflake-read_query",
    "k8s-kubectl_get",
    "google-cloud-bigquery_run_query",
    "google_sheet-get_sheet_data",
    "canvas-canvas_list_account_users", "canvas-canvas_list_quizzes",
    "canvas-canvas_list_courses",
    "yahoo-finance-get_historical_stock_prices",
    "local-web_search",
}
_WRITE_TOOLS = {
    "filesystem-write_file", "filesystem-create_directory", "filesystem-edit_file",
    "github-create_or_update_file", "github-delete_file", "github-create_issue",
    "snowflake-write_query",
    "google_sheet-update_cells",
    "google-cloud-logging_write_log",
    "excel-write_data_to_excel",
    "word-create_document", "word-add_paragraph", "word-format_text",
    "notion-API-patch-block-children",
    "canvas-canvas_create_course", "canvas-canvas_create_announcement",
    "canvas-canvas_update_course", "canvas-canvas_enroll_user",
    "canvas-canvas_create_conversation",
    "emails-send_email",
    "google_forms-create_form",
    "woocommerce-woo_products_update",
}
_EXECUTE_TOOLS = {"local-python-execute", "terminal-run_command"}


def _cat(name: str) -> str:
    if name in _READ_TOOLS: return "read"
    if name in _WRITE_TOOLS: return "write"
    if name in _EXECUTE_TOOLS: return "execute"
    if name.startswith("playwright"): return "browser"
    return "other"


def _model_key(fname: str) -> str:
    m = re.match(r"^(.+)_(\d+)\.jsonl$", fname)
    return m.group(1) if m else fname


def main() -> None:
    from clew.detect.cascade import cascade
    from clew.detect.semantic import Embedder
    from clew.detect.structural import find_candidates
    from clew.ingest.toolathlon import _build_trace_from_entry, _iter_raw_lines

    root = Path(sys.argv[1])
    files = sorted(root.glob("*.jsonl"))
    print(f"입력 디렉토리: {root}")
    print(f"파일 수: {len(files)}")
    print(f"φ={PHI}  N={N}  embed={MODEL_EMBED}@{REV[:7]}")
    print()

    t0 = time.perf_counter()
    embedder = Embedder(model_name=MODEL_EMBED, revision=REV, cache_dir=CACHE_DIR)

    # per-file records
    per_file: dict[str, dict] = {}
    parse_errors_all: list[tuple[str, int, str]] = []
    top_waste_traces: list[dict] = []  # for Step 3 highlight

    all_waste_items: list[dict] = []  # for Step 5

    for path in files:
        fname = path.name
        rec = {
            "file": fname,
            "traces": 0, "spans": 0, "tool_spans": 0,
            "cands": 0, "waste": 0, "waste_traces": 0,
            "eval_pass": 0, "eval_fail": 0, "eval_other": 0,
            "waste_by_eval": defaultdict(int),
            "traces_by_eval": defaultdict(int),
        }
        for lineno, entry in _iter_raw_lines(path):
            rec["traces"] += 1
            try:
                trace = _build_trace_from_entry(entry, lineno)
            except Exception as e:  # noqa: BLE001
                parse_errors_all.append((fname, lineno, f"[build] {type(e).__name__}: {e}"))
                continue
            try:
                cands = find_candidates(trace, N)
                res = cascade(trace, embedder, N, PHI)
            except Exception as e:  # noqa: BLE001
                parse_errors_all.append((fname, lineno, f"[detect] {type(e).__name__}: {e}"))
                continue
            rec["spans"] += len(trace.spans)
            rec["tool_spans"] += sum(1 for s in trace.spans if s.span_kind == "tool")
            rec["cands"] += len(cands)
            waste_set = set(res.waste_span_ids)
            rec["waste"] += len(waste_set)
            if waste_set:
                rec["waste_traces"] += 1
            ts = trace.metadata.get("task_status", {})
            ev = ts.get("evaluation") if isinstance(ts, dict) else None
            # evaluation 은 bool (True/False) 또는 문자열 ("pass"/"fail") 또는 None. raw 매핑.
            if ev is True or ev == "pass":
                ev_key = "pass"
            elif ev is False or ev == "fail":
                ev_key = "fail"
            else:
                ev_key = "other"
            rec[f"eval_{ev_key}"] += 1
            rec["traces_by_eval"][ev_key] += 1
            rec["waste_by_eval"][ev_key] += len(waste_set)
            if waste_set:
                top_waste_traces.append({
                    "file": fname,
                    "task": trace.metadata.get("task_name"),
                    "eval": ev,
                    "waste": len(waste_set),
                })
            # waste items for Step 5
            span_by_id = {s.span_id: s for s in trace.spans}
            for wid in waste_set:
                sp = span_by_id[wid]
                all_waste_items.append({
                    "file": fname,
                    "model": _model_key(fname),
                    "task": trace.metadata.get("task_name"),
                    "eval": ev,
                    "tool": sp.agent_or_node_id,
                    "input_head": sp.input_text[:80],
                    "output_head": sp.output_text[:120],
                })
        per_file[fname] = rec

    # ── Step 2. 파일별 raw ─────────────────────────────────────────────────
    print("=" * 78)
    print("Step 2. 파일별 스캔 raw")
    print("=" * 78)
    header = f"{'file':<40} {'trc':>4} {'span':>6} {'tool':>6} {'cnd':>5} {'wst':>5} {'wT':>4} {'ps':>4} {'fl':>4}"
    print(header)
    for fname in sorted(per_file):
        r = per_file[fname]
        print(f"{fname:<40} {r['traces']:>4} {r['spans']:>6} {r['tool_spans']:>6} "
              f"{r['cands']:>5} {r['waste']:>5} {r['waste_traces']:>4} "
              f"{r['eval_pass']:>4} {r['eval_fail']:>4}")

    # 전체
    tot = {k: 0 for k in ("traces","spans","tool_spans","cands","waste","waste_traces",
                          "eval_pass","eval_fail","eval_other")}
    for r in per_file.values():
        for k in tot:
            tot[k] += r[k]
    print()
    print(f"전체: traces={tot['traces']}  spans={tot['spans']}  tool_spans={tot['tool_spans']}")
    print(f"      cands={tot['cands']}  waste={tot['waste']}  waste_traces={tot['waste_traces']}")
    print(f"      eval pass={tot['eval_pass']}  fail={tot['eval_fail']}  other={tot['eval_other']}")

    print()
    print(f"파싱/탐지 실패 총합: {len(parse_errors_all)}")
    for fname, ln, err in parse_errors_all[:40]:
        print(f"  {fname} line#{ln}: {err}")

    # ── Step 3. 모델별 (파일 3개 aggregate) ───────────────────────────────
    print()
    print("=" * 78)
    print("Step 3. 모델별 waste율 (3런 aggregate)")
    print("=" * 78)
    per_model: dict[str, dict] = {}
    for fname, r in per_file.items():
        m = _model_key(fname)
        agg = per_model.setdefault(m, {
            "traces": 0, "spans": 0, "tool_spans": 0,
            "cands": 0, "waste": 0, "waste_traces": 0,
            "eval_pass": 0, "eval_fail": 0, "eval_other": 0,
            "waste_by_eval_pass": 0, "waste_by_eval_fail": 0,
            "traces_by_eval_pass": 0, "traces_by_eval_fail": 0,
        })
        agg["traces"] += r["traces"]
        agg["spans"] += r["spans"]
        agg["tool_spans"] += r["tool_spans"]
        agg["cands"] += r["cands"]
        agg["waste"] += r["waste"]
        agg["waste_traces"] += r["waste_traces"]
        agg["eval_pass"] += r["eval_pass"]
        agg["eval_fail"] += r["eval_fail"]
        agg["eval_other"] += r["eval_other"]
        agg["waste_by_eval_pass"] += r["waste_by_eval"].get("pass", 0)
        agg["waste_by_eval_fail"] += r["waste_by_eval"].get("fail", 0)
        agg["traces_by_eval_pass"] += r["traces_by_eval"].get("pass", 0)
        agg["traces_by_eval_fail"] += r["traces_by_eval"].get("fail", 0)

    hdr = (f"{'model':<28} {'trc':>4} {'cnd':>5} {'wst':>5} {'wT':>4} "
           f"{'w/trc':>6} {'w/1kt':>6} {'sha%':>6} {'wf/tf':>6} {'wp/tp':>6}")
    print(hdr)
    rows: list[tuple[str, float, dict]] = []
    for m in sorted(per_model):
        a = per_model[m]
        w_per_trace = a["waste"] / a["traces"] if a["traces"] else 0.0
        w_per_1k_tool = 1000 * a["waste"] / a["tool_spans"] if a["tool_spans"] else 0.0
        sha_rate = a["waste"] / a["cands"] if a["cands"] else 0.0
        wf_tf = a["waste_by_eval_fail"] / a["traces_by_eval_fail"] if a["traces_by_eval_fail"] else 0.0
        wp_tp = a["waste_by_eval_pass"] / a["traces_by_eval_pass"] if a["traces_by_eval_pass"] else 0.0
        rows.append((m, w_per_trace, a))
        print(f"{m:<28} {a['traces']:>4} {a['cands']:>5} {a['waste']:>5} {a['waste_traces']:>4} "
              f"{w_per_trace:>6.3f} {w_per_1k_tool:>6.2f} {sha_rate*100:>5.1f}% "
              f"{wf_tf:>6.3f} {wp_tp:>6.3f}")

    print()
    print("범례: w/trc = waste / trace, w/1kt = waste / 1000 tool_spans, "
          "sha% = waste/cands, wf/tf = waste/실패trace, wp/tp = waste/성공trace")

    # Top waste 트레이스
    print()
    print("=" * 78)
    print("waste 상위 트레이스 15")
    print("=" * 78)
    top = sorted(top_waste_traces, key=lambda x: -x["waste"])[:15]
    for r in top:
        print(f"  file={r['file']:<40} eval={str(r['eval']):>6}  waste={r['waste']:>3}  task={r['task']!r}")

    # ── Step 4. sha256 게이트 통과율 (모델별 요약) ─────────────────────────
    # Step 3 표에 sha% 이미 있음. 여기서는 empty-args waste 분포만 추가.
    print()
    print("=" * 78)
    print("Step 4. sha256 게이트 — 빈-인자 waste 분포 (모델별)")
    print("=" * 78)
    empty_by_model: dict[str, int] = defaultdict(int)
    nonempty_by_model: dict[str, int] = defaultdict(int)
    for w in all_waste_items:
        t = w["input_head"].strip()
        is_empty = t in ("", "{}") or (t.startswith("{") and t.endswith("}") and len(t) <= 6)
        if is_empty:
            empty_by_model[w["model"]] += 1
        else:
            nonempty_by_model[w["model"]] += 1
    print(f"{'model':<28} {'empty':>6} {'nonempty':>10}")
    for m in sorted(per_model):
        print(f"{m:<28} {empty_by_model.get(m, 0):>6} {nonempty_by_model.get(m, 0):>10}")

    # ── Step 5. tool 카테고리 (전체 + 모델별 read 계열 비율) ────────────
    print()
    print("=" * 78)
    print("Step 5. tool 카테고리 분포 (전 waste)")
    print("=" * 78)
    cat_ct = Counter(_cat(w["tool"]) for w in all_waste_items)
    print("[전체]")
    for c in ("read", "write", "browser", "execute", "other"):
        pct = 100 * cat_ct[c] / len(all_waste_items) if all_waste_items else 0
        print(f"  {c:8s} : {cat_ct[c]:>4}  ({pct:>5.1f}%)")

    print()
    print("[모델별 카테고리 분포]")
    print(f"{'model':<28} {'read':>4} {'write':>5} {'brws':>4} {'exec':>4} {'oth':>4}")
    for m in sorted(per_model):
        items = [w for w in all_waste_items if w["model"] == m]
        c = Counter(_cat(w["tool"]) for w in items)
        print(f"{m:<28} {c.get('read',0):>4} {c.get('write',0):>5} "
              f"{c.get('browser',0):>4} {c.get('execute',0):>4} {c.get('other',0):>4}")

    print()
    print("[tool 이름 top-20 (전 waste)]")
    tool_ct = Counter(w["tool"] for w in all_waste_items)
    for t, c in tool_ct.most_common(20):
        print(f"  {c:>4}  [{_cat(t):7s}]  {t}")

    print()
    print("=" * 78)
    print(f"wall time: {time.perf_counter() - t0:.1f}s")
    print("=" * 78)


if __name__ == "__main__":
    main()
