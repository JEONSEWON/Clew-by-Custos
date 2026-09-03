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
from typing import TYPE_CHECKING

from clew.cost.pricing import build_default_cost_tables

if TYPE_CHECKING:
    # Annotation only. The runtime import stays inside the function so a CLI
    # invocation that never loads a trace does not pay for the model import.
    from clew.model import Trace


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
                f"마커가 동시에 있음. 형식 판별 불가"
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
            f"{path}: JSONL 형식 판별 실패. 최상위 키 {list(first_obj.keys())[:8]}. "
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
            f"알 수 없는 JSON 형식. 최상위 키: {list(obj.keys())[:5]}"
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
            f"Error: detect dependencies missing. Run: pip install 'boxdawn[detect]'\n{e}",
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

    # Verification axis (FM-3.2). Opt-in for the same reason as the judge
    # above: it spends the user's API key. One call, three outcomes, and a
    # failure exits 0 -- see the shipping prereg §7 P4.
    from clew.detect.llm_judge.verification_axis import find_verification_failure
    verification_result = find_verification_failure(
        trace, enabled=args.verification,
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
        verification=verification_result,
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
            verification=verification_result,
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


def _live_prereg_url() -> str:
    """Same reason as above, for the fast path's preregistration."""
    from clew.live import PREREG_URL

    return PREREG_URL


def _submit(args: argparse.Namespace) -> int:
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
        oversized = submit.refused_too_large(
            submit.load_ledger(), submit.server_limit())
        if oversized:
            print(f"too large   : {len(oversized)} refused by the server "
                  f"(largest {max(oversized.values()) / 1e6:.1f} MB), "
                  "not measured")
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
            print("earlier sessions stay put. Send them with `boxdawn submit`")
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
                      f"({len(matches)} matches). Run `boxdawn setup --list`")
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


def _watch_log_line(projects: int, tally: dict, drained, total: int) -> str:
    """The one line an unattended pass leaves behind.

    `pending` is here because a finding that could not be delivered has to be
    visible without anyone asking: the retry has no give-up counter, so the
    only thing separating "nothing to send" from "sending has been failing all
    day" is this number and the reason beside it (RETRY AMENDMENT §3). The
    reason is appended only when something is pending, so a quiet run stays one
    short line.
    """
    line = (f"projects={projects} live={tally['live']} "
            f"recorded={tally['recorded']} capped={tally['capped']} "
            f"sent={drained.delivered} pending={drained.pending}")
    if drained.pending:
        line += f" last={drained.last_reason or 'unknown'}"
    return line + f" findings={total} {tally['seconds']:.1f}s"


def _watch(args: argparse.Namespace) -> int:
    """Watch running sessions and record repeats locally. Sends nothing.

    LIVE_FAILURE_ALERT_PREREG §8 step 2: shadow first. Delivery is step 6 and
    a separate decision, so there is no endpoint and no key read here -- a
    watcher that could send is not in shadow mode, whatever its default says.
    """
    from datetime import datetime

    from clew import live, schedule
    from clew.detect.semantic import Embedder
    from clew.submit import load_targets

    if args.install or args.uninstall or args.status:
        return _watch_schedule(args, schedule, live)

    if args.root:
        targets = [("default", Path(args.root))]
    else:
        try:
            targets = [(t.project, t.root) for t in load_targets()]
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    missing = [str(root) for _, root in targets if not root.exists()]
    if missing:
        print(f"Error: no such trace directory: {', '.join(missing)}", file=sys.stderr)
        return 1

    embedder = Embedder(model_name=_MODEL, revision=_REV, cache_dir=_CACHE_DIR)

    # The user's own tool classifications, when they have declared any. A tool
    # they mark `read_only` becomes alertable; one they mark `side_effect`
    # stops being. IDEMPOTENT_TRIGGER_PREREG §2 -- the declaration they already
    # made is what decides, rather than a second list they never saw.
    user_tools = None
    try:
        from clew.config import find_clew_yaml, load_user_config  # noqa: PLC0415
        yaml_path = find_clew_yaml(Path.cwd())
        if yaml_path is not None:
            user_tools = load_user_config(yaml_path)
    except Exception:                                             # noqa: BLE001
        # A malformed or unreadable clew.yaml must not stop the watcher; the
        # built-in categories are a complete answer on their own. `analyze`
        # reports the error loudly, and that is the right place for it.
        user_tools = None

    # Delivery lives in its own module and is off unless asked. `live.py`
    # cannot reach the network at all -- a test parses its imports -- so
    # turning this on is a change here and never a change to the detector.
    from clew import live_send

    sending = live_send.enabled(args.send)

    def on_finding(f) -> None:
        # Records only. Delivery is `deliver` below, once per pass over the
        # ledger, so that a send which fails is simply still undelivered next
        # pass -- RETRY AMENDMENT §1.
        print(f"finding  {f.signal}  {Path(f.session).name}  "
              f"repeat at {f.occurred_at}  "
              f"({f.latency_seconds():.0f}s behind, {f.candidates_seen} candidates)")

    def deliver() -> None:
        out = live_send.drain(flag=args.send)
        if out.attempted or out.pending:
            print(f"         delivery: sent={out.delivered} "
                  f"pending={out.pending} {out.last_reason or '-'}")

    def on_sweep(project, result) -> None:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {project}: "
              f"{result.scanned} live · {result.recorded} recorded · "
              f"{result.suppressed_hourly} over the hourly cap · "
              f"{result.seconds:.1f}s")

    if args.auto:
        # One line per run, whatever happened -- the same reason `submit
        # --auto` writes one: a pass that found nothing and a task that never
        # fired are the same silence otherwise, and this one is expected to
        # find nothing on almost every run.
        tally = {"live": 0, "recorded": 0, "capped": 0, "seconds": 0.0}
        drained = live_send.DrainResult()

        def count(project, result):
            tally["live"] += result.scanned
            tally["recorded"] += result.recorded
            tally["capped"] += result.suppressed_hourly
            tally["seconds"] += result.seconds

        def deliver_once() -> None:
            nonlocal drained
            drained = live_send.drain(flag=args.send)

        live.watch(targets, embedder, n=_N, phi=_PHI,
                   poll_seconds=args.interval, once=True, on_sweep=count,
                   on_cycle=deliver_once, tools=user_tools)
        total = len(live.load_findings())
        schedule.log_run(
            _watch_log_line(len(targets), tally, drained, total),
            live.WATCH_LOG_PATH,
        )
        return 0

    if sending:
        print(f"recording to {live.FINDINGS_PATH} and telling the server about "
              f"each finding. Whether you get mail is the server's decision.")
    else:
        print(f"shadow mode: recording to {live.FINDINGS_PATH}, sending nothing")
    try:
        live.watch(
            targets, embedder, n=_N, phi=_PHI,
            poll_seconds=args.interval, once=args.once,
            on_finding=on_finding, on_sweep=on_sweep, on_cycle=deliver,
            tools=user_tools,
        )
    except KeyboardInterrupt:
        print("stopped")
    return 0


def _registration_note(task_args) -> str:
    """What the registration actually does, read off its own arguments.

    This sentence said "Nothing is sent, and there is no endpoint to send to
    yet" while `WATCH_ARGS` already carried `--send` and the endpoint was
    deployed. It was false because it was written by hand beside a constant that
    later changed, and it is the sentence somebody registering the task reads.
    Deriving it from the tuple means the claim cannot outlive the flag.
    """
    if "--send" in tuple(task_args):
        return ("registered with --send: every finding is offered to the "
                "server, which mails you only if your project is on its "
                "allow-list. Re-register without it to record only.")
    return "records findings locally and sends nothing."


def _findings_note(findings, task_args) -> str:
    """`N recorded, M delivered (mode)`.

    `M` was the literal `0` and the mode the literal `shadow`, which stopped
    being true twice over: findings now carry `delivered`, and the registration
    can send. Both halves are now read rather than asserted.
    """
    delivered = sum(1 for f in findings if f.delivered)
    mode = "sending" if "--send" in tuple(task_args) else "shadow"
    return f"{len(findings)} recorded, {delivered} delivered ({mode})"


def _watch_schedule(args: argparse.Namespace, schedule, live) -> int:
    """--install / --uninstall / --status for the fast path.

    A second registration beside the submission sweep, not a resident loop.
    `schedule.py` says why in its own first paragraph, and the watcher is the
    daemon that paragraph is about.
    """
    name = schedule.WATCH_TASK_NAME

    if args.status:
        registered = schedule.is_registered(name)
        where = {True: "registered", False: "not registered",
                 None: "unknown on this platform"}[registered]
        print(f"scheduler   : {where} ({name})")
        print(f"command     : {schedule.command_line(schedule.WATCH_ARGS)}")
        findings = live.load_findings()
        print(f"findings    : {_findings_note(findings, schedule.WATCH_ARGS)}")
        for f in findings[-5:]:
            print(f"  {f.occurred_at}  {Path(f.session).name[:8]}  "
                  f"{f.signal}  {f.latency_seconds():.0f}s behind")
        tail = schedule.tail_log(live.WATCH_LOG_PATH)
        print("last runs   :" if tail else "last runs   : (none yet)")
        for line in tail:
            print(f"  {line}")
        return 0

    if args.uninstall:
        ok, message = schedule.uninstall(name)
        print(message)
        return 0 if ok or schedule.is_registered(name) is None else 1

    every = args.every or schedule.WATCH_EVERY_MINUTES
    ok, message = schedule.install(
        every, task_name=name, task_args=schedule.WATCH_ARGS,
        # Minutes, not the sweep's hour: one hung scan under IgnoreNew silences
        # every trigger behind it, and at this cadence that is 60 of them.
        time_limit="PT10M",
    )
    print(message)
    if ok or schedule.is_registered(name) is None:
        print(_registration_note(schedule.WATCH_ARGS))
        return 0
    return 1


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
        "--verification",
        dest="verification",
        action="store_true",
        default=None,
        help=(
            "ask whether the session checked the code it changed (opt-in, "
            "FM-3.2). One call per trace to the Anthropic API with your "
            "ANTHROPIC_API_KEY; measured at $0.0046 and 1.8 s per session. "
            "Without a key the report says 'not judged' and the exit code is "
            "still 0. Precision on 40 hand-labelled sessions: 0.9286 "
            "without the request in the judge's view, 1.0000 with it "
            "(one session apart)."
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

    w = sub.add_parser(
        "watch",
        help="watch running sessions for a repeat, and record it locally",
        description=(
            "The fast path. The analyzer is already on this machine, so a "
            "repeated step is found while the session is still open instead of "
            "43 minutes after it closes. Findings are written to "
            "~/.clew/live_findings.json. Nothing leaves this machine unless "
            "you pass --send, and even then the server only mails projects on "
            "its allow-list. See "
            + _live_prereg_url()
        ),
    )
    w.add_argument("--root", default=None, metavar="DIR",
                   help="trace directory (default: the projects in ~/.clew/projects.yaml)")
    w.add_argument("--interval", type=int, default=60, metavar="SEC",
                   help=(
                       "seconds between polls (default: 60). A poll that takes "
                       "longer than a quarter of this stretches the wait, so a "
                       "large session cannot pin a core."
                   ))
    w.add_argument("--once", action="store_true",
                   help="one pass and exit")
    w.add_argument("--install", action="store_true",
                   help="register the watcher with the OS scheduler")
    w.add_argument("--uninstall", action="store_true",
                   help="remove the registered watcher")
    w.add_argument("--status", action="store_true",
                   help="show whether it is registered and what it has found")
    w.add_argument("--every", type=int, default=None, metavar="MIN",
                   help="minutes between passes for --install (default: 1)")
    w.add_argument("--send", action="store_true", default=None,
                   help=(
                       "tell the server about each finding so it can mail you "
                       "(opt-in). Off by default, and the server refuses "
                       "anyway unless your project is on its allow-list -- "
                       "the two halves fail closed independently. What crosses "
                       "the wire is a session key, a tool name and two counts: "
                       "never a trace, never a path."
                   ))
    w.add_argument("--auto", action="store_true",
                   help=argparse.SUPPRESS)

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
    elif args.cmd == "watch":
        sys.exit(_watch(args))
    elif args.cmd == "estimate":
        sys.exit(_estimate(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
