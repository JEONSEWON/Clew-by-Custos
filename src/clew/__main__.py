"""boxdawn CLI entry point.

Usage:
    boxdawn analyze <trace.json> [--out report.md] [--json out.json] [--no-snippets]

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
      - Boxdawn Trace JSON (top-level dict with "trace_id" key) -> load_trace()
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
            # Boxdawn serialized Trace JSON
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
            f"Error: detect dependencies missing — pip install 'boxdawn[detect]'\n{e}",
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


def _submit_rule_url() -> str:
    """Where the close rule lives, as a URL rather than a repository path.

    A pip-install user has no docs/ tree, so pointing at one is pointing at
    nothing (tests/test_user_tools_config.py guards this).
    """
    from clew.submit import RULE_URL

    return RULE_URL


def _submit(args: argparse.Namespace) -> int:
    from datetime import datetime, timezone
    from pathlib import Path

    from clew import schedule, submit

    if args.install or args.uninstall or args.status:
        return _submit_schedule(args, schedule, submit)

    endpoint = args.endpoint or submit.DEFAULT_ENDPOINT

    # An explicit --root means "this folder, this key", which is the shape the
    # command had before per-project routing existed. Honour it verbatim
    # rather than routing around the operator.
    if args.root:
        return submit.run(
            root=Path(args.root), endpoint=endpoint, dry_run=args.dry_run,
            pace_seconds=args.pace, limit=args.limit,
        )

    try:
        targets = submit.load_targets()
    except ValueError as exc:
        print(exc)
        return 2

    since = submit.installed_at() if args.auto else None
    if args.auto and since is None:
        # Nothing registered the watermark, so there is no "from here on".
        # Sweeping the machine's history is what --install exists to prevent.
        print("not installed: run `boxdawn submit --install` first")
        return 2

    lines: list[str] = []

    def record(text):
        lines.append(str(text))
        print(text)

    code = submit.run_all(
        targets, endpoint=endpoint, dry_run=args.dry_run,
        pace_seconds=args.pace, limit=args.limit, since=since,
        out=record if args.auto else print,
    )

    if args.auto:
        # One line per run, whatever happened. A sweep that found nothing and a
        # scheduler that never fired are indistinguishable otherwise.
        summary = "; ".join(ln for ln in lines if ln.startswith(("done:", "nothing", "no key", "note:")))
        schedule.log_run(
            f"exit={code} targets={len(targets)} {summary or 'no output'}",
            submit.AUTO_LOG_PATH,
        )
    return code


def _submit_schedule(args: argparse.Namespace, schedule, submit) -> int:
    """--install / --uninstall / --status."""
    from datetime import datetime, timezone

    if args.status:
        registered = schedule.is_registered()
        where = {True: "registered", False: "not registered",
                 None: "unknown on this platform"}[registered]
        print(f"scheduler   : {where} ({schedule.TASK_NAME})")
        print(f"command     : {schedule.command_line()}")
        stamp = submit.installed_at()
        print(f"submits from: {stamp.isoformat() if stamp else '(never installed)'}")
        tail = schedule.tail_log(submit.AUTO_LOG_PATH)
        print("last runs   :" if tail else "last runs   : (none yet)")
        for line in tail:
            print(f"  {line}")
        return 0

    if args.uninstall:
        ok, message = schedule.uninstall()
        print(message)
        # The watermark is left in place on purpose: reinstalling later should
        # not become a licence to backfill everything since the first install.
        return 0 if ok or schedule.is_registered() is None else 1

    ok, message = schedule.install(args.every or schedule.DEFAULT_EVERY_MINUTES)
    print(message)
    if ok or schedule.is_registered() is None:
        state = submit.read_auto_state()
        if not state.get("installed_at"):
            state["installed_at"] = datetime.now(timezone.utc).isoformat()
            submit.write_auto_state(state)
            print(f"submits sessions that end after {state['installed_at']}")
            print("earlier sessions stay put — send them with `boxdawn submit`")
        else:
            print(f"watermark unchanged: {state['installed_at']}")
        return 0
    return 1


def _setup(args: argparse.Namespace) -> int:
    """Configure this machine so `submit` has a key and knows where to look."""
    from pathlib import Path

    from clew import setup, submit

    found = setup.discover(Path(args.root) if args.root else submit.DEFAULT_ROOT)

    if args.list or not args.key:
        if not found:
            print("no agent trace folders found under "
                  f"{args.root or submit.DEFAULT_ROOT}")
            return 1
        print(f"{'#':>2}  {'project':28s} {'sessions':>8}  last activity")
        for i, d in enumerate(found, 1):
            when = d.last_seen.strftime("%Y-%m-%d") if d.last_seen else "unknown"
            print(f"{i:2d}  {d.label[:28]:28s} {d.sessions:8d}  {when}")
        if not args.key:
            print()
            print("to configure one of these:")
            print("  boxdawn setup --key bdk_... --project <n>      # that project only")
            print("  boxdawn setup --key bdk_...                    # every folder, one key")
            print()
            print("one key per project keeps each codebase on its own baseline; the")
            print("alert rule compares a day against the previous day within one.")
        return 0

    problem = setup.key_shape_problem(args.key)
    if problem:
        print(f"that does not look like a submission key: {problem}")
        return 2

    if args.project is None:
        path = setup.write_credentials(args.key)
        print(f"wrote {path}")
        print(f"every folder under {submit.DEFAULT_ROOT} will be sent under this key.")
        if len(found) > 1:
            print(f"note: {len(found)} folders are there. Sent as one project, a day-over-day")
            print("      rate answers 'which project did I work on', not 'how wasteful was")
            print("      the work'. Use --project to keep them apart.")
    else:
        try:
            index = int(args.project)
        except ValueError:
            matches = [d for d in found if d.label == args.project]
            if len(matches) != 1:
                print(f"no single folder named {args.project!r} "
                      f"({len(matches)} matches) — run `boxdawn setup --list`")
                return 2
            chosen = matches[0]
        else:
            if not 1 <= index <= len(found):
                print(f"--project {index} is out of range 1..{len(found)}")
                return 2
            chosen = found[index - 1]
        path, action = setup.upsert_project(chosen.label, chosen.directory, args.key)
        print(f"{action} {chosen.label} in {path}")

    # Said plainly rather than implied: nothing here has spoken to the server.
    print()
    print("the key's shape is checked here; whether it is live and bound to a")
    print("project is answered by the server on the first submission.")
    print("next:  boxdawn submit --dry-run     # see what would be sent")
    print("       boxdawn submit --install     # then let it run hourly")
    return 0


def _estimate(args: argparse.Namespace) -> int:
    """Report what makes a trace expensive to analyze. No verdict.

    Analysis time does not follow file size. Measured on four Claude Code
    traces, it follows *cumulative context* -- the total input text across
    llm_calls -- at 368-440 s/GB locally and ~399 s/GB on the hosted runtime,
    while a 5.24 MB trace finished in 40 s and a 3.39 MB one took 85 s. So a
    caller deciding whether to send a trace somewhere needs the context figure,
    and a byte cap would refuse traces that work.

    Deliberately values only. Whether a number is "too big" depends on the
    ceiling of whichever surface is asking -- a browser upload where somebody is
    waiting, an unattended queue where nobody is -- and a verdict computed here
    would hide which ceiling it was measured against. The caller owns the
    threshold; this owns the measurement.

    Parsing is the whole cost of this command: 2.4-3.0% of a full analysis on
    the traces measured, 10.3 s on the heaviest.
    """
    import json as _json_out
    import time

    path = Path(args.trace_file)
    started = time.perf_counter()
    try:
        trace = _load_trace_auto(path)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    parse_seconds = time.perf_counter() - started

    from clew.metrics.waste_rate import _compute_total_input
    context_bytes, _ = _compute_total_input(trace)
    llm_calls = len(trace.metadata.get("llm_calls") or [])

    payload = {
        "trace_id": trace.trace_id,
        "file_bytes": path.stat().st_size,
        # The predictor. Named for what it is rather than "size", because the
        # two diverge and the wrong one is the intuitive one.
        "cumulative_context_bytes": context_bytes,
        "llm_calls": llm_calls,
        "spans": len(trace.spans),
        "parse_seconds": round(parse_seconds, 3),
    }

    if getattr(args, "json_out_stdout", False):
        print(_json_out.dumps(payload, indent=2))
        return 0

    gb = context_bytes / 1024 ** 3
    print(f"trace            {trace.trace_id}")
    print(f"file             {payload['file_bytes'] / 1024 / 1024:.2f} MB")
    print(f"llm calls        {llm_calls}")
    print(f"cumulative ctx   {gb:.3f} GB   <- what analysis time follows")
    print(f"parsed in        {parse_seconds:.1f} s")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="boxdawn", description="Boxdawn waste analyzer")
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

    s = sub.add_parser(
        "submit",
        help="send finished agent sessions to the analyzer",
        description=(
            "Uploads sessions that have been quiet long enough to call "
            "finished, once each. The rule that decides 'long enough' is "
            "preregistered: " + _submit_rule_url()
        ),
    )
    s.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "list what would be sent and send nothing. A first run is a "
            "backfill of every session on the machine, so look before you run it."
        ),
    )
    s.add_argument("--root", default=None, metavar="DIR",
                   help="trace directory (default: ~/.claude/projects)")
    s.add_argument("--endpoint", default=None, metavar="URL",
                   help="analyzer endpoint")
    s.add_argument("--limit", type=int, default=None, metavar="N",
                   help="send at most N this run")
    s.add_argument("--pace", type=float, default=2.0, metavar="SEC",
                   help="seconds between submissions (default: 2)")
    s.add_argument("--install", action="store_true",
                   help=(
                       "register the hourly sweep with the OS scheduler. Only "
                       "sessions that end after this moment are sent "
                       "automatically; anything older stays put."
                   ))
    s.add_argument("--uninstall", action="store_true",
                   help="remove the registered sweep")
    s.add_argument("--status", action="store_true",
                   help="show whether the sweep is registered and how it went")
    s.add_argument("--every", type=int, default=None, metavar="MIN",
                   help="minutes between sweeps for --install (default: 60)")
    s.add_argument("--auto", action="store_true",
                   help=argparse.SUPPRESS)

    st = sub.add_parser(
        "setup",
        help="point this machine at your Boxdawn project",
        description=(
            "Finds the agent trace folders on this machine, names them the way "
            "you would recognise them, and writes the key config so `submit` "
            "works. Run with no arguments to see what is here."
        ),
    )
    st.add_argument("--key", default=None, metavar="bdk_...",
                    help="submission key, issued on your project's key page")
    st.add_argument("--project", default=None, metavar="NAME|N",
                    help=(
                        "configure one folder only, by name or by its number in "
                        "--list. Omit to send every folder under one key."
                    ))
    st.add_argument("--list", action="store_true",
                    help="show the folders found and write nothing")
    st.add_argument("--root", default=None, metavar="DIR",
                    help="trace directory (default: ~/.claude/projects)")

    e = sub.add_parser(
        "estimate",
        help="report what makes a trace expensive to analyze",
        description=(
            "Prints the numbers that predict analysis cost and stops there. "
            "Analysis time follows cumulative context, not file size: a "
            "5.24 MB trace finished in 40 s while a 3.39 MB one took 85 s. "
            "No verdict is given, because how big is too big depends on the "
            "ceiling of whoever is asking."
        ),
    )
    e.add_argument("trace_file", help="path to a trace file")
    e.add_argument("--json", dest="json_out_stdout", action="store_true",
                   help="print JSON to stdout instead of a summary")

    args = parser.parse_args()
    if args.cmd == "analyze":
        sys.exit(_analyze(args))
    elif args.cmd == "submit":
        sys.exit(_submit(args))
    elif args.cmd == "setup":
        sys.exit(_setup(args))
    elif args.cmd == "estimate":
        sys.exit(_estimate(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
