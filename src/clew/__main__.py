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

    명확한 에러:
      - resource_spans/resourceSpans 키 → Format B 미지원, 변환 방법 안내
    """
    from clew.model import Trace  # noqa: F401 (type-only import avoidance)

    text = path.read_text(encoding="utf-8").strip()
    try:
        obj = _json.loads(text)
    except _json.JSONDecodeError as exc:
        raise ValueError(f"JSON 파싱 실패: {exc}") from exc

    if isinstance(obj, dict):
        if "trace_id" in obj:
            from clew.io import load_trace
            return load_trace(path)
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
        raise ValueError(
            f"알 수 없는 JSON 형식 — 최상위 키: {list(obj.keys())[:5]}"
        )

    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and "context" in obj[0]:
            from clew.ingest.otel_json import ingest_from_otel_json
            return ingest_from_otel_json(path)
        raise ValueError(
            "JSON 배열이지만 OTel SDK JSON 형식이 아닙니다. "
            "각 스팬에 'context' 키가 있어야 합니다."
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
