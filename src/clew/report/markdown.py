"""src/clew/report/markdown.py — 사람용 마크다운 리포트 렌더러."""

from __future__ import annotations

from datetime import datetime, timezone

from clew.detect.cascade import CascadeResult
from clew.model import Trace
from clew.report._model import WasteDetail

_PHI = 0.514345
_N = 2
_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

_SNIPPET_LEN = 80


def render_markdown(
    trace: Trace,
    cr: CascadeResult,
    details: list[WasteDetail],
    *,
    no_snippets: bool = False,
    snippet_len: int = _SNIPPET_LEN,
) -> str:
    """CascadeResult + WasteDetail 목록 → 마크다운 문자열.

    스니펫: output_text[:snippet_len] 기본 (no_snippets=True면 행 자체 생략).
    리포트 머리에 동결 파라미터(φ, N, 모델) 인쇄.
    """
    lines: list[str] = []
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines.append("# Clew Waste Report")
    lines.append("")
    lines.append(f"- **trace_id**: `{trace.trace_id}`")
    lines.append(f"- **analyzed**: {now}")
    lines.append(
        f"- **detector params**: φ={_PHI}, N={_N}, model={_MODEL}"
    )
    lines.append("")

    _FOOTER = (
        "---\n"
        "_Note: detection thresholds were calibrated on synthetic traces; "
        "real-trace calibration is in progress. Borderline matches "
        "(cosine near 0.51) deserve human review._"
    )

    if not cr.wasteful:
        lines.append("## Result: no waste detected")
        lines.append("")
        lines.append("No wasteful patterns found (wasteful=False).")
        lines.append("")
        lines.append(_FOOTER)
        return "\n".join(lines)

    total_tok = cr.waste_tokens if cr.waste_tokens > 0 else None
    total_cost = cr.waste_cost if cr.waste_cost > 0.0 else None
    tok_str = str(total_tok) if total_tok is not None else "unknown"
    cost_str = f"{total_cost:.6f}" if total_cost is not None else "unknown"

    lines.append("## Result: WASTE DETECTED")
    lines.append("")
    lines.append(f"- **wasted spans**: {len(cr.waste_span_ids)}")
    lines.append(f"- **estimated wasted tokens**: {tok_str}")
    lines.append(f"- **estimated wasted cost**: {cost_str}")
    lines.append("")

    lines.append("## Wasted Span Details")
    lines.append("")
    lines.append(
        "| origin_node | repeat_node | cosine | tokens (wasted) | cost (wasted) |"
    )
    lines.append(
        "|-------------|-------------|--------|-----------------|---------------|"
    )

    for wd in details:
        wt = str(wd.waste_tokens) if wd.waste_tokens is not None else "unknown"
        wc_val = wd.waste_cost
        wc = f"{wc_val:.6f}" if wc_val is not None else "unknown"
        lines.append(
            f"| {wd.origin.agent_or_node_id} "
            f"| {wd.candidate.agent_or_node_id} "
            f"| {wd.cosine:.4f} "
            f"| {wt} "
            f"| {wc} |"
        )

    if not no_snippets:
        lines.append("")
        lines.append("## Snippets")
        lines.append("")
        for i, wd in enumerate(details, 1):
            lines.append(f"**{i}. {wd.candidate.agent_or_node_id}** (repeat)")
            snip = wd.candidate.output_text[:snippet_len]
            lines.append(f"> {snip}")
            lines.append("")

    lines.append(_FOOTER)
    return "\n".join(lines)
