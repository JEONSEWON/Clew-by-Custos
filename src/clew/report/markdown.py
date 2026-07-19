"""src/clew/report/markdown.py - human-facing markdown report renderer."""

from __future__ import annotations

from datetime import datetime, timezone

from clew.cost.amplification import AmplificationEstimate
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
    amplification: AmplificationEstimate | None = None,
) -> str:
    """CascadeResult + WasteDetail list -> markdown string.

    Snippet: output_text[:snippet_len] by default (omits the row entirely if no_snippets=True).
    Prints frozen parameters (phi, N, model) at the report header.
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
        "_Note: detection thresholds are frozen at synthetic values "
        "(phi=0.514345, N=2); real-trace evaluation is ongoing, but "
        "parameters have not been recalibrated. Borderline matches "
        "(cosine near phi) deserve human review — this applies to "
        "non-tool spans; tool spans use exact sha256 identity._\n\n"
        "_Cost is estimated saving potential, not measured — assumes the "
        "wasted output is re-consumed each subsequent turn (structural "
        "assumption). Range spans cache-hit (lower) to cache-miss (upper). "
        "Attribution assumes Sonnet pricing._"
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

    if amplification is not None and amplification.n_events > 0:
        lo = amplification.lower_usd
        up = amplification.upper_usd
        approx_note = " (some events use char/1.3 approximation)" if amplification.any_approx else ""
        lines.append(
            f"- **estimated amplification cost**: "
            f"${lo:.6f} ~ ${up:.6f} "
            f"(cache-hit to cache-miss bounds, estimated){approx_note}"
        )
        lines.append(
            f"- **amplification events**: {amplification.n_events} "
            f"(skipped {amplification.n_skipped_prev_eq_next} prev==next, "
            f"{amplification.n_skipped_no_metadata} no-metadata; "
            f"total amp tokens = {amplification.total_amp_tokens})"
        )
    elif amplification is not None:
        lines.append(
            f"- **estimated amplification cost**: unknown "
            f"(no eligible events after skip: "
            f"{amplification.n_skipped_prev_eq_next} prev==next, "
            f"{amplification.n_skipped_no_metadata} no-metadata)"
        )
    else:
        lines.append("- **estimated amplification cost**: unknown (adapter metadata unavailable)")

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
