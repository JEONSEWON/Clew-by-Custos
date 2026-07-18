"""python -m clew — CLI 진입점.

사용:
    python -m clew analyze <trace.json> [--out report.md] [--json out.json] [--no-snippets]

종료코드: 낭비 탐지·미탐지 모두 0. 파일 없음·스키마 오류·기타 예외는 1.
"""

from __future__ import annotations

import argparse
import json as _json
import sys
from pathlib import Path


def _load_trace_auto(path: Path) -> "Trace":
    """파일 형식 자동 감지 후 Trace 반환.

    지원:
      - Clew Trace JSON (최상위 dict에 "trace_id" 키)     → load_trace()
      - OTel SDK JSON 배열 (최상위 list, "context" 키)     → ingest_from_otel_json()
      - Claude Code JSONL (.jsonl, 첫 줄 "sessionId")       → ingest_claude_code_jsonl()
      - Toolathlon JSONL (.jsonl, 첫 줄 "modelname_run")    → ingest_toolathlon_jsonl()

    명확한 에러:
      - resource_spans/resourceSpans 키 → Format B 미지원, 변환 방법 안내
      - .jsonl 이지만 어느 마커도 없음 → 최상위 키 로그 + 에러
    """
    from clew.model import Trace  # noqa: F401 (type-only import avoidance)

    if path.suffix == ".jsonl":
        # 첫 파싱 가능 라인만 peek → 마커로 어댑터 선택 (§23.4)
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

        # 마커 검사 — 두 셋은 겹치지 않음 확인됨 (§23.4)
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
            return ingest_claude_code_jsonl(path)
        if toolathlon_marker:
            from clew.ingest.toolathlon import ingest_toolathlon_jsonl
            return ingest_toolathlon_jsonl(path)
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
        # RedundancyBench 마커 (§24.2): 최상위 dict 에 tasks + simulations
        if "tasks" in obj and "simulations" in obj:
            from clew.ingest.redundancy_bench import ingest_redundancy_bench_json
            return ingest_redundancy_bench_json(path)
        if "trace_id" in obj and "spans" in obj:
            spans_list = obj.get("spans", [])
            first_span = spans_list[0] if spans_list and isinstance(spans_list[0], dict) else {}
            if "span_attributes" in first_span or "child_spans" in first_span:
                # Format C: OpenInference nested dict (TRAIL 등)
                from clew.ingest.otel_json import ingest_from_openinference_json
                return ingest_from_openinference_json(path)
            # Clew 직렬화 Trace JSON
            from clew.io import load_trace
            return load_trace(path)
        raise ValueError(
            f"알 수 없는 JSON 형식 — 최상위 키: {list(obj.keys())[:5]}"
        )

    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and "context" in obj[0]:
            # Format A: OTel SDK JSON 배열
            from clew.ingest.otel_json import ingest_from_otel_json
            return ingest_from_otel_json(path)
        if obj and isinstance(obj[0], dict) and "span_id" in obj[0]:
            # Format C flat: OpenInference flat 배열
            from clew.ingest.otel_json import ingest_from_openinference_json
            return ingest_from_openinference_json(path)
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

    # 파일 로드
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

    # 탐지기 초기화
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

    # 마크다운 리포트
    from clew.report.markdown import render_markdown
    md = render_markdown(trace, cr, details, no_snippets=no_snippets)

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(md, encoding="utf-8")
        print(f"report written → {out_path}")
    else:
        print(md)

    # JSON 리포트 (선택)
    if args.json_out:
        from clew.report.json_report import render_json
        jstr = render_json(trace, cr, details, no_snippets=no_snippets)
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

    args = parser.parse_args()
    if args.cmd == "analyze":
        sys.exit(_analyze(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
