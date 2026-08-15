"""python -m clew - CLI entry point.

Usage:
    python -m clew analyze <trace.json> [--out report.md] [--json out.json] [--no-snippets]

Exit code: 0 for both waste-detected and no-waste. 1 for missing file, schema error, or other exceptions.
"""

from __future__ import annotations

import argparse
import json as _json
import sys
from pathlib import Path

from clew.cost.pricing import build_default_cost_tables


def _load_trace_auto(path: Path) -> "Trace":
    """Auto-detect file format and return a Trace.

    Supported:
      - Clew Trace JSON (top-level dict with "trace_id" key)   -> load_trace()
      - OTel SDK JSON array (top-level list, "context" key)    -> ingest_from_otel_json()
      - Claude Code JSONL (.jsonl, first line has "sessionId") -> ingest_claude_code_jsonl()
      - Toolathlon JSONL (.jsonl, first line has "modelname_run") -> ingest_toolathlon_jsonl()

    Explicit errors:
      - resource_spans/resourceSpans key -> Format B unsupported, provides conversion instructions
      - .jsonl but no marker matches -> log top-level keys + error
    """
    from clew.model import Trace  # noqa: F401 (type-only import avoidance)

    if path.suffix == ".jsonl":
        # Peek only the first parsable line -> pick adapter by marker (§23.4)
        first_obj: dict | None = None
        with path.open(encoding="utf-8") as f:
            for raw in f:
                s = raw.strip()
                if not s:
                    continue
                try:
                    parsed = _json.loads(s)
                except _json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:1: JSONL 첫 라인 파싱 실패 ({exc})") from exc
                if isinstance(parsed, dict):
                    first_obj = parsed
                break
        if first_obj is None:
            raise ValueError(f"{path}: 빈 JSONL 또는 첫 라인이 dict 아님")

        # Marker check - confirmed the two sets do not overlap (§23.4)
        cc_marker = "sessionId" in first_obj
        toolathlon_marker = (
            "modelname_run" in first_obj
            and "task_status" in first_obj
            and "messages" in first_obj
        )
        if cc_marker and toolathlon_marker:
            raise ValueError(
                f"{path}: JSONL 첫 라인에 CC(sessionId)와 Toolathlon(modelname_run+task_status+messages) "
                f"마커가 동시에 있음 — 형식 판별 불가"
            )
        if cc_marker:
            from clew.ingest.claude_code import ingest_claude_code_jsonl
            return ingest_claude_code_jsonl(
                path,
                input_cost_table=_INPUT_COST_TABLE,
                output_cost_table=_OUTPUT_COST_TABLE,
            )
        if toolathlon_marker:
            from clew.ingest.toolathlon import ingest_toolathlon_jsonl
            return ingest_toolathlon_jsonl(
                path,
                input_cost_table=_INPUT_COST_TABLE,
                output_cost_table=_OUTPUT_COST_TABLE,
            )
        raise ValueError(
            f"{path}: JSONL 형식 판별 실패 — 최상위 키 {list(first_obj.keys())[:8]}. "
            f"'sessionId' (CC) 또는 'modelname_run'+'task_status'+'messages' (Toolathlon) 필요."
        )

    text = path.read_text(encoding="utf-8").strip()
    try:
        obj = _json.loads(text)
    except _json.JSONDecodeError as exc:
        raise ValueError(f"JSON 파싱 실패: {exc}") from exc

    if isinstance(obj, dict):
        if "resource_spans" in obj or "resourceSpans" in obj:
            raise ValueError(
                "OTLP proto-JSON 형식(resource_spans)은 아직 미지원입니다.\n"
                "Format A(OTel SDK JSON 배열)로 변환 후 재시도하세요:\n"
                "  import json; from pathlib import Path\n"
                "  spans = exporter.get_finished_spans()\n"
                "  Path('trace.json').write_text(\n"
                "      json.dumps([json.loads(s.to_json()) for s in spans])\n"
                "  )"
            )
        # RedundancyBench marker (§24.2): top-level dict has tasks + simulations
        if "tasks" in obj and "simulations" in obj:
            from clew.ingest.redundancy_bench import ingest_redundancy_bench_json
            return ingest_redundancy_bench_json(path)
        if "trace_id" in obj and "spans" in obj:
            spans_list = obj.get("spans", [])
            first_span = spans_list[0] if spans_list and isinstance(spans_list[0], dict) else {}
            if "span_attributes" in first_span or "child_spans" in first_span:
                # Format C: OpenInference nested dict (TRAIL, etc.)
                from clew.ingest.otel_json import ingest_from_openinference_json
                return ingest_from_openinference_json(
                    path,
                    input_cost_table=_INPUT_COST_TABLE,
                    output_cost_table=_OUTPUT_COST_TABLE,
                )
            # Clew serialized Trace JSON
            from clew.io import load_trace
            return load_trace(path)
        raise ValueError(
            f"알 수 없는 JSON 형식 — 최상위 키: {list(obj.keys())[:5]}"
        )

    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and "context" in obj[0]:
            # Format A: OTel SDK JSON array
            from clew.ingest.otel_json import ingest_from_otel_json
            return ingest_from_otel_json(
                path,
                input_cost_table=_INPUT_COST_TABLE,
                output_cost_table=_OUTPUT_COST_TABLE,
            )
        if obj and isinstance(obj[0], dict) and "span_id" in obj[0]:
            # Format C flat: OpenInference flat array
            from clew.ingest.otel_json import ingest_from_openinference_json
            return ingest_from_openinference_json(
                path,
                input_cost_table=_INPUT_COST_TABLE,
                output_cost_table=_OUTPUT_COST_TABLE,
            )
        raise ValueError(
            "JSON 배열이지만 알 수 없는 형식입니다. "
            "각 스팬에 'context' 키(Format A) 또는 'span_id' 키(Format C)가 있어야 합니다."
        )

    raise ValueError(f"지원하지 않는 JSON 최상위 타입: {type(obj).__name__}")


_PHI = 0.514345
_N = 2
_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
_REV = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
_CACHE_DIR = Path.home() / ".cache" / "clew" / "embeddings"

# Auto-populated pricing tables — makes WR_cost / cost-attribution fire on
# default CLI runs. Diagnostic scripts build their own tables against the
# same source of truth (`src/clew/cost/pricing.py`).
_INPUT_COST_TABLE, _OUTPUT_COST_TABLE = build_default_cost_tables()


def _build_details(trace, cr, embedder):
    from clew.detect.semantic import cosine
    from clew.detect.structural import find_candidates
    from clew.report._model import WasteDetail

    waste_id_set = set(cr.waste_span_ids)
    pairs = find_candidates(trace, _N)
    best: dict[str, tuple] = {}
    for origin, candidate in pairs:
        if candidate.span_id not in waste_id_set:
            continue
        score = cosine(
            embedder.embed(origin.output_text),
            embedder.embed(candidate.output_text),
        )
        if candidate.span_id not in best or score > best[candidate.span_id][2]:
            best[candidate.span_id] = (origin, candidate, score)
    return [WasteDetail(o, c, sc) for o, c, sc in best.values()]


def _analyze(args: argparse.Namespace) -> int:
    trace_path = Path(args.trace_file)
    no_snippets: bool = args.no_snippets

    # File load
    if not trace_path.exists():
        print(f"Error: {trace_path} not found", file=sys.stderr)
        return 1
    try:
        trace = _load_trace_auto(trace_path)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Optional user tool config (clew.yaml). When neither --config nor a
    # discovered file exists, user_tools stays None and downstream behavior
    # is bit-identical to pre-clew.yaml releases (§3 gate).
    user_tools = None
    try:
        from clew.config import (  # noqa: PLC0415
            emit_load_warnings,
            find_clew_yaml,
            load_user_config,
            UserToolConfigError,
        )
        explicit = Path(args.config) if args.config else None
        yaml_path = find_clew_yaml(trace_path, explicit=explicit)
        if yaml_path is not None:
            user_tools = load_user_config(yaml_path)
            emit_load_warnings(user_tools)
    except UserToolConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except ImportError:
        # pyyaml missing while --config also missing: proceed with no config.
        # If --config was set, load_user_config would have raised.
        pass

    # Detector initialization
    try:
        from clew.detect.cascade import cascade
        from clew.detect.semantic import Embedder
    except ImportError as e:
        print(
            f"Error: detect dependencies missing — pip install 'clew[detect]'\n{e}",
            file=sys.stderr,
        )
        return 1

    embedder = Embedder(model_name=_MODEL, revision=_REV, cache_dir=_CACHE_DIR)
    cr = cascade(trace, embedder, n=_N, phi=_PHI)
    details = _build_details(trace, cr, embedder) if cr.wasteful else []

    # Amplification estimate (only meaningful when CC metadata is present).
    amp = None
    if cr.wasteful and "cc_usage_pair" in trace.metadata:
        from clew.cost.amplification import estimate_amplification
        amp = estimate_amplification(cr, trace)

    # Context Resend Detector (prereg §5). Runs whenever the trace carries an
    # `llm_calls` metadata block. Adapters that do not produce LLM spans
    # (Claude Code v1, Toolathlon) yield an empty list and the section is
    # skipped downstream.
    from clew.detect.context_resend import find_context_resend
    resend_result = find_context_resend(trace)

    # Redundant Read Detector (Redundant Read prereg §5). Runs on any trace
    # with tool spans. Empty result when no read tools or no repeats.
    from clew.detect.redundant_read import find_redundant_reads
    redundant_read_result = find_redundant_reads(trace, tools=user_tools)

    # LLM-as-judge Semantic Duplicate (Task #10 prereg §2). Opt-in ONLY.
    # Off by default; enabled iff --llm-judge OR CLEW_ENABLE_LLM_JUDGE=1.
    from clew.detect.llm_judge import find_llm_judge_semantic_duplicates
    llm_judge_result = find_llm_judge_semantic_duplicates(
        trace, enabled=args.llm_judge,
    )

    # Waste-rate metric (WASTE_RATE_METRIC_PREREG §6.1 report integration).
    # Additive summary field. Re-runs the 4 deterministic detectors internally
    # (~2× cascade cost); acceptable for per-session report generation.
    from clew.metrics.waste_rate import compute_waste_rate
    waste_rate_result = compute_waste_rate(
        trace, embedder=embedder, n=_N, phi=_PHI, tools=user_tools,
    )

    # Phase 2: user entity_id extraction ratios — one-shot stderr summary.
    # Only emitted when clew.yaml declared any entity_id path.
    if user_tools is not None and user_tools.has_user_entity_ids:
        from clew.report._enrich import (  # noqa: PLC0415
            compute_user_extraction_ratios,
            format_extraction_ratios,
            scan_id_bridge_candidates,
        )
        candidates_for_ratio = scan_id_bridge_candidates(trace, user_tools)
        ratios = compute_user_extraction_ratios(candidates_for_ratio)
        ratio_report = format_extraction_ratios(ratios)
        if ratio_report is not None:
            print(ratio_report, file=sys.stderr)

    # Markdown report
    from clew.report.markdown import render_markdown
    md = render_markdown(
        trace, cr, details,
        no_snippets=no_snippets, amplification=amp, user_tools=user_tools,
        context_resend=resend_result,
        redundant_read=redundant_read_result,
        llm_judge=llm_judge_result,
        waste_rate=waste_rate_result,
    )

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(md, encoding="utf-8")
        print(f"report written → {out_path}")
    else:
        print(md)

    # JSON report (optional)
    if args.json_out:
        from clew.report.json_report import render_json
        jstr = render_json(
            trace, cr, details,
            no_snippets=no_snippets, amplification=amp, user_tools=user_tools,
            context_resend=resend_result,
            redundant_read=redundant_read_result,
            llm_judge=llm_judge_result,
            waste_rate=waste_rate_result,
        )
        json_path = Path(args.json_out)
        json_path.write_text(jstr, encoding="utf-8")
        print(f"json report written → {json_path}")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="clew", description="Clew waste analyzer")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("analyze", help="analyze a trace file")
    p.add_argument("trace_file", help="path to trace.json")
    p.add_argument("--out", metavar="report.md", help="write markdown report to file")
    p.add_argument("--json", dest="json_out", metavar="out.json", help="write JSON report to file")
    p.add_argument("--no-snippets", action="store_true", help="exclude output_text snippets from report")
    p.add_argument(
        "--config",
        metavar="clew.yaml",
        default=None,
        help=(
            "path to user tool config (clew.yaml). "
            "Overrides trace-file walk-up and ~/.clew/config.yaml discovery."
        ),
    )
    p.add_argument(
        "--llm-judge",
        dest="llm_judge",
        action="store_true",
        default=None,
        help=(
            "enable LLM-as-judge semantic duplicate detection (opt-in). "
            "Requires ANTHROPIC_API_KEY env var. "
            "See docs/LLM_JUDGE_SEMANTIC_DUPLICATE_PREREG.md for details."
        ),
    )

    args = parser.parse_args()
    if args.cmd == "analyze":
        sys.exit(_analyze(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
