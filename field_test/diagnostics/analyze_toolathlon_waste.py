"""field_test/diagnostics/analyze_toolathlon_waste.py

Toolathlon 108 스캔 → waste 28건의 구성 분석.
Q1 빈 인자 vs 실질 인자
Q2 실질 인자 waste 상세
Q3 tool 종류별 분포
Q4 성공/실패 트레이스별 waste 성격

규율: 정의/코드/게이트 무수정. raw 만. 결론 금지.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
REV = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
CACHE_DIR = Path.home() / ".cache/clew/embeddings"
PHI = 0.514345
N = 2


# tool prefix → category
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

_EXECUTE_TOOLS = {
    "local-python-execute",
    "terminal-run_command",
}


def _classify_tool(name: str) -> str:
    if name in _READ_TOOLS:
        return "read"
    if name in _WRITE_TOOLS:
        return "write"
    if name in _EXECUTE_TOOLS:
        return "execute"
    if name.startswith("playwright"):
        return "browser"
    return "other"


def _is_empty_args(input_text: str) -> tuple[bool, str]:
    """빈-인자 판정. raw 판단.

    빈으로 볼 케이스:
      - ""
      - "{}"
      - json.loads 결과가 빈 dict 인 정규화된 문자열
    실질 인자로 볼 케이스:
      - 값 하나라도 있음
    반환: (is_empty, reason)
    """
    t = input_text.strip()
    if t == "":
        return True, "empty-string"
    if t == "{}":
        return True, "empty-object"
    try:
        obj = json.loads(t)
    except Exception:  # noqa: BLE001
        return False, "unparsable-nonempty"
    if isinstance(obj, dict) and len(obj) == 0:
        return True, "empty-object-parsed"
    if isinstance(obj, dict):
        # 값이 전부 "" 인 경우 (예: {"args": ""})
        if all(v == "" for v in obj.values()):
            return True, f"all-empty-values ({list(obj.keys())})"
    if isinstance(obj, list) and len(obj) == 0:
        return True, "empty-list"
    return False, "has-content"


def _find_error_marker(text: str) -> str | None:
    """output 에 에러 문자열 존재하나 (raw 검사, 판단 아님)."""
    low = text.lower()
    markers = ["error:", "\"error\"", "traceback", "exception:", "failed:", "denied"]
    for m in markers:
        if m in low:
            return m
    return None


def main() -> None:
    from clew.detect.cascade import cascade
    from clew.detect.semantic import Embedder
    from clew.detect.structural import find_candidates
    from clew.ingest.toolathlon import _build_trace_from_entry, _iter_raw_lines

    path = Path(sys.argv[1])
    print(f"입력: {path}")
    print(f"φ={PHI}  N={N}")
    print()

    embedder = Embedder(model_name=MODEL, revision=REV, cache_dir=CACHE_DIR)

    # 트레이스별 waste 수집
    waste_items: list[dict] = []
    build_errs: list[tuple[int, str]] = []
    for lineno, entry in _iter_raw_lines(path):
        try:
            trace = _build_trace_from_entry(entry, lineno)
        except Exception as e:  # noqa: BLE001
            build_errs.append((lineno, f"{type(e).__name__}: {e}"))
            continue
        cands = find_candidates(trace, N)
        res = cascade(trace, embedder, N, PHI)
        waste_set = set(res.waste_span_ids)
        task_name = trace.metadata.get("task_name")
        task_status = trace.metadata.get("task_status", {})
        ev = task_status.get("evaluation") if isinstance(task_status, dict) else None
        for o, c in cands:
            if c.span_id not in waste_set:
                continue
            waste_items.append({
                "task": task_name,
                "eval": ev,
                "trace_id": trace.trace_id,
                "tool": c.agent_or_node_id,
                "input": c.input_text,
                "output": c.output_text,
                "origin_input": o.input_text,
                "origin_output": o.output_text,
            })

    print(f"waste 총 건수: {len(waste_items)}")
    print(f"build 실패: {len(build_errs)}")
    for ln, err in build_errs:
        print(f"  line#{ln}: {err}")
    print()

    # ─── Q1 ─────────────────────────────────────────────────────────────
    print("=" * 78)
    print("Q1  빈 인자 vs 실질 인자")
    print("=" * 78)
    empty_items: list[dict] = []
    real_items: list[dict] = []
    for w in waste_items:
        is_empty, reason = _is_empty_args(w["input"])
        w["_empty_flag"] = is_empty
        w["_empty_reason"] = reason
        (empty_items if is_empty else real_items).append(w)
    print(f"빈-인자 waste     : {len(empty_items)}")
    print(f"실질-인자 waste   : {len(real_items)}")
    print()
    print("[빈-인자 waste 나열 — tool, reason, task]")
    for w in empty_items:
        print(f"  tool={w['tool']!r:60}  reason={w['_empty_reason']!r:26}  task={w['task']!r}")
    print()
    print("[빈-인자 tool name 분포]")
    empty_tool_ct: dict[str, int] = {}
    for w in empty_items:
        empty_tool_ct[w["tool"]] = empty_tool_ct.get(w["tool"], 0) + 1
    for t, c in sorted(empty_tool_ct.items(), key=lambda kv: -kv[1]):
        print(f"  {c:>3}  {t}")

    # ─── Q2 ─────────────────────────────────────────────────────────────
    print()
    print("=" * 78)
    print("Q2  실질-인자 waste 상세")
    print("=" * 78)
    for i, w in enumerate(real_items, 1):
        print(f"\n[Q2-#{i}]  task={w['task']!r}  eval={w['eval']!r}")
        print(f"  trace_id  : {w['trace_id']}")
        print(f"  tool      : {w['tool']}")
        # input 앞 120
        inp = w["input"].replace("\n", "\\n")
        out = w["output"].replace("\n", "\\n")
        print(f"  input[:120]: {inp[:120]!r}")
        print(f"  output[:120]: {out[:120]!r}")
        # 재호출 원인 힌트 (추정)
        cat = _classify_tool(w["tool"])
        # 원인 후보 (raw 힌트)
        if cat == "read":
            hint = "같은 파일/쿼리를 두 번 읽음 (사이에 편집 없다면 requery_known)"
        elif cat == "write":
            hint = "같은 쓰기 재시도"
        elif cat == "browser":
            hint = "브라우저 상태 재확인 (navigate, wait, type 반복)"
        elif cat == "execute":
            hint = "같은 명령 재실행"
        else:
            hint = "기타"
        err = _find_error_marker(w["output"])
        print(f"  category  : {cat}")
        print(f"  error_marker(output): {err!r}")
        print(f"  hint(추정) : {hint}")

    # ─── Q3 ─────────────────────────────────────────────────────────────
    print()
    print("=" * 78)
    print("Q3  tool 종류별 waste 분포 (전체 28건)")
    print("=" * 78)
    cat_ct: dict[str, int] = {}
    tool_ct: dict[str, int] = {}
    for w in waste_items:
        c = _classify_tool(w["tool"])
        cat_ct[c] = cat_ct.get(c, 0) + 1
        tool_ct[w["tool"]] = tool_ct.get(w["tool"], 0) + 1
    print("[카테고리]")
    for c in ("read", "write", "browser", "execute", "other"):
        print(f"  {c:8s} : {cat_ct.get(c, 0)}")
    print()
    print("[tool 이름별]")
    for t, c in sorted(tool_ct.items(), key=lambda kv: -kv[1]):
        cat = _classify_tool(t)
        print(f"  {c:>3}  [{cat:7s}]  {t}")

    # ─── Q4 ─────────────────────────────────────────────────────────────
    print()
    print("=" * 78)
    print("Q4  성공 vs 실패 트레이스의 waste 성격")
    print("=" * 78)
    by_eval: dict[str, list[dict]] = {}
    for w in waste_items:
        by_eval.setdefault(str(w["eval"]), []).append(w)
    for ev, items in sorted(by_eval.items()):
        print(f"\n--- eval={ev!r}  waste={len(items)} ---")
        # tool category 분포
        c_ct: dict[str, int] = {}
        err_ct = 0
        for w in items:
            c_ct[_classify_tool(w["tool"])] = c_ct.get(_classify_tool(w["tool"]), 0) + 1
            if _find_error_marker(w["output"]):
                err_ct += 1
        print("  카테고리 분포:")
        for c in ("read", "write", "browser", "execute", "other"):
            print(f"    {c:8s} : {c_ct.get(c, 0)}")
        print(f"  output 에 에러 문자열 있는 waste: {err_ct} / {len(items)}")
        print("  waste 상세 (task, tool, output 앞 100 + error marker):")
        for w in items:
            err = _find_error_marker(w["output"])
            out = w["output"].replace("\n", "\\n")[:100]
            print(f"    task={w['task']!r:38} tool={w['tool']!r:52} err={err!r:12} out={out!r}")


if __name__ == "__main__":
    main()
