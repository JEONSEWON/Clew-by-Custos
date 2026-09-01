"""src/clew/report/markdown.py - human-facing markdown report renderer."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from clew.cost.amplification import AmplificationEstimate, AmplificationEvent
from clew.detect.cascade import CascadeResult
from clew.detect.context_resend import ContextResendResult
from clew.detect.llm_judge import LLMJudgeResult
from clew.detect.redundant_read import RedundantReadResult
from clew.metrics.waste_rate import WasteRateMetric
from clew.model import Trace
from clew.report._enrich import (
    EnrichedDetail,
    IdBridgeCandidate,
    coverage_stats,
    enrich,
    scan_id_bridge_candidates,
)
from clew.report._model import TraceCostSummary, WasteDetail, build_cost_summary

if TYPE_CHECKING:
    from clew.config import ResolvedTools

_PHI = 0.514345
_N = 2
_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

_SNIPPET_LEN = 80

_FOOTER = (
    "---\n"
    "_Note: detection thresholds are frozen at synthetic values "
    "(phi=0.514345, N=2); real-trace evaluation is ongoing, but "
    "parameters have not been recalibrated. Borderline matches "
    "(cosine near phi) deserve human review. This applies to "
    "non-tool spans; tool spans use exact sha256 identity._\n\n"
    "_Cost is estimated saving potential, not measured: it assumes the "
    "wasted output is re-consumed each subsequent turn (structural "
    "assumption). Range spans cache-hit (lower) to cache-miss (upper) — two "
    "billing outcomes for the same tokens, not a ratio. Attribution uses "
    "per-model rates; a model the table does not carry resolves to the "
    "nearest named one where an alias exists, and falls back to Sonnet 4.5 "
    "otherwise. Only the fallback is reported as a substitution._"
)

_POSSIBLE_CAUSES = (
    "## Possible causes\n"
    "\n"
    "Repeated file re-reads commonly stem from one of:\n"
    "- the agent not retaining what it already read (no context caching)\n"
    "- prompts that re-trigger verification\n"
    "- context truncation dropping earlier reads\n"
    "\n"
    "This trace cannot isolate which. Inspect the agent's file-handling logic.\n"
    "For Bash requeries the state between calls is not directly observable from the "
    "trace; treat those as *state change uncertain*. The tool does not render a "
    "final waste verdict.\n"
)

_CATEGORY_CAUSES = (
    "## What each category typically points to\n"
    "\n"
    "These are common origins, not diagnoses. Detection is unchanged.\n"
    "\n"
    "- **error_repeat**: the agent received the same error response twice. "
    "Usually the tool arguments are wrong and the agent re-runs with the "
    "same arguments without addressing the error message.\n"
    "- **side_effect**: a state-changing tool was invoked twice with the "
    "same arguments. Beyond wasted tokens, real side effects (duplicate "
    "sends, duplicate creates, etc.) may have occurred. Confirm the "
    "operation is safe to run more than once.\n"
    "- **idempotent**: a read-only or declarative tool was called "
    "repeatedly. This category assumes the tool has no side effect, based "
    "on the tool name; whether that holds in your setup, and whether the "
    "underlying state truly did not change between the two calls, needs "
    "verification against your execution context.\n"
    "- **unclassified**: the tool's effect depends on the arguments passed "
    "(command text, code, query body), so the tool name alone cannot "
    "classify it. Human review needed.\n"
)

# ─── PREREG §3.1 (§9 revised) frozen wording — idempotent between_window ────
_BW_OBS_DECLARATIVE = (
    "Tool is declarative or idempotent by name; "
    "the interval between calls was not examined."
)
_BW_OBS_NO_CHANGE = "No state change was observed between the two calls."
_BW_OBS_TARGETED_WRITES = (
    "State-changing tools were invoked in the interval, targeting other "
    "resources; this reread's output is unchanged from the first call."
)
_BW_OBS_HIGH_VOLUME = (
    "State-changing tools were invoked across a long interval "
    "(≥ 20 tool spans between the two calls); this reread's output "
    "is unchanged from the first call."
)
_BW_JUDGE_DELEGATION = (
    "Whether these were wasted invocations is a user judgment; "
    "the tool records only the observation."
)
_BW_HEADER_NO_VERDICT = (
    "No verdict is rendered. Refer to context and judge whether each was intentional."
)

# ─── PREREG: docs/COVERAGE_TRANSPARENCY_PREREG.md §1.1 (frozen) ─────────────
# Two-line banner. Line A: always rendered (including waste-0). Line B:
# conditional on the report having at least one idempotent pair. The label
# narrowing (mapping-relative classification) is stated once in the README
# About section, not sprinkled through per-pair wording.
_COVERAGE_LINE_A = (
    "**Tool mapping coverage for this trace**: {recognized} of "
    "{unique_in_trace} tools recognized ({pct:.1%})."
)
_COVERAGE_LINE_B = (
    "**Idempotent pairs with unrecognized tool in interval**: "
    "{pairs_affected} of {idempotent_total}."
)
# docs/COVERAGE_BANNER_AMEND_PREREG.md §3.1 (N=5, occurrence-desc + alpha tie).
# Renders when unrecognized > 0, in both waste-0 and waste-detected branches
# (parallels Line A's early-render rule, §3.5). Full list lives in JSON
# coverage_stats.unrecognized_tool_names (§4 option B).
_COVERAGE_LINE_C_TOP_N = 5
_COVERAGE_LINE_C = (
    "**Unrecognized tools in this trace (top {n_shown})**: {names}{more}"
)


def _format_coverage_line_c(unrecognized_tool_names: list[str]) -> str | None:
    """Render Line C body; None when the list is empty."""
    total = len(unrecognized_tool_names)
    if total == 0:
        return None
    n_shown = min(_COVERAGE_LINE_C_TOP_N, total)
    shown = unrecognized_tool_names[:n_shown]
    more = f", … (+{total - n_shown} more)" if total > n_shown else ""
    return _COVERAGE_LINE_C.format(
        n_shown=n_shown,
        names=", ".join(shown),
        more=more,
    )


# Provenance line (rendered only when clew.yaml is loaded and has user tools).
# Format: "built-in: 12, user: 16, user-overriding-built-in: 12"
_COVERAGE_LINE_D = (
    "**Mapping source**: built-in: {built_in}, user: {user}, "
    "user-overriding-built-in: {override}."
)
# Q2 footnote (2026-07-31): rendered on the line right after Line D. One line,
# no elaboration in the banner. Detail belongs in the README.
_COVERAGE_PRECISION_FOOTNOTE = (
    "_Precision bounds were measured on built-in mappings; "
    "user-registered tools are unverified._"
)


def _format_coverage_provenance(cov: dict) -> list[str] | None:
    """Render Line D + precision footnote when clew.yaml provenance is present.

    Depends on coverage_stats emitting the 3-count keys (only when user tools
    were loaded — otherwise this function returns None and the banner is
    identical to before, preserving §3 gate parity.)
    """
    if "built_in_count" not in cov:
        return None
    return [
        _COVERAGE_LINE_D.format(
            built_in=cov["built_in_count"],
            user=cov["user_count"],
            override=cov["user_overriding_built_in_count"],
        ),
        _COVERAGE_PRECISION_FOOTNOTE,
    ]

# ─── PREREG docs/ID_BRIDGE_PRODUCTION_PREREG.md §1.4 (frozen) ───────────────
# "Duplicate creation check" section. Renders alongside — not in place of —
# cascade waste details. Word "provable" is intentionally absent (§0.2).
_DUPLICATE_CREATION_HEADER = "## Duplicate creation check"
_DUPLICATE_CREATION_INTRO = (
    "The waste detector above requires both responses to be byte-identical. "
    "That is the right test for reads: a re-read that returns the same "
    "content is a redundant call. For creation tools it is reversed: if a "
    "document really was created twice, the two responses carry different "
    "entity IDs, so the waste detector excludes them by construction. This "
    "section scans that excluded pool separately."
)
_ID_BRIDGE_VERDICT_DIFFER = (
    "Both calls returned entity IDs, and they differ: {origin_id} / {candidate_id}."
)
_ID_BRIDGE_VERDICT_SAME = (
    "Both calls returned the same entity ID: {origin_id}."
)
_ID_BRIDGE_VERDICT_NO_ID = (
    "This tool's response contains no entity ID; whether a second entity was "
    "created cannot be determined from the trace."
)


_CATEGORY_NOTE = (
    "## About categories\n"
    "\n"
    "The `[category]` tag on each waste pair is a **report-only annotation**: "
    "it does not affect what was flagged as waste. Detection is unchanged.\n"
    "\n"
    "- `error_repeat`: output matches an error pattern (same call repeated after failure)\n"
    "- `side_effect`: tool with known state-changing effect "
    "(e.g. `Edit`, `github-create_pull_request`)\n"
    "- `idempotent`: tool is read-only or declarative "
    "(e.g. `Read`, `filesystem-list_directory`); whether *this* re-run is actually "
    "wasted depends on user context (was the state truly unchanged?)\n"
    "- `unclassified`: tool name not in either mapping. Includes `Bash`, `PowerShell`, "
    "`local-python-execute`, `terminal-run_command`, and `bigquery_run_query`: their "
    "effect depends on the payload, not the tool name.\n"
    "\n"
    "The mapping is by tool name only, never inferred from name substrings.\n"
)


def _summary_duplicate_creation_line(candidates: list[IdBridgeCandidate]) -> list[str]:
    """One-line summary of duplicate creation results, for the top Result section.

    Rendered alongside the Waste-detection line, in both cascade branches, so
    the top banner never contradicts the "Duplicate creation check" section
    below. Framed as detection, not confirmed impact. differ/same/no_id are
    kept as three separate numbers (never collapsed to a single "waste-like"
    total).
    """
    if not candidates:
        return []
    differ = sum(1 for c in candidates if c.verdict == "differ")
    same = sum(1 for c in candidates if c.verdict == "same")
    no_id = sum(1 for c in candidates if c.verdict == "no_id")
    return [
        f"- **Duplicate creation check**: {len(candidates)} candidate pair(s): "
        f"{differ} with differing entity IDs, "
        f"{same} with the same entity ID, "
        f"{no_id} without extractable entity ID. "
        f"Detection, not confirmed impact. See section below."
    ]


def _render_id_bridge_section(candidates: list[IdBridgeCandidate]) -> list[str]:
    """Duplicate creation check section (PREREG §1.4).

    Renders header + intro + aggregate line + per-candidate list. When the
    pool is empty, renders header + intro + explicit "0 candidates" line
    (§1.6 decision 3 — checked but empty ≠ not checked).
    """
    lines: list[str] = [_DUPLICATE_CREATION_HEADER, "", _DUPLICATE_CREATION_INTRO, ""]
    if not candidates:
        lines.append("- **candidates**: 0 candidates found in this trace.")
        lines.append("")
        return lines
    differ = sum(1 for c in candidates if c.verdict == "differ")
    same = sum(1 for c in candidates if c.verdict == "same")
    no_id = sum(1 for c in candidates if c.verdict == "no_id")
    lines.append(f"- **candidates**: {len(candidates)} pairs total")
    lines.append(f"  - {differ} with different entity IDs")
    lines.append(f"  - {same} with the same entity ID")
    lines.append(f"  - {no_id} without extractable entity ID")
    # Phase 2 provenance split. Rendered only when a user-registered
    # candidate is present in the pool.
    user_present = any(c.source == "user" for c in candidates)
    if user_present:
        bi_differ = sum(1 for c in candidates if c.verdict == "differ" and c.source == "built-in")
        bi_same = sum(1 for c in candidates if c.verdict == "same" and c.source == "built-in")
        bi_no = sum(1 for c in candidates if c.verdict == "no_id" and c.source == "built-in")
        u_differ = differ - bi_differ
        u_same = same - bi_same
        u_no = no_id - bi_no
        bi_total = bi_differ + bi_same + bi_no
        u_total = u_differ + u_same + u_no
        lines.append(
            f"  - built-in: {bi_total} pairs "
            f"({bi_differ} differ, {bi_same} same, {bi_no} no_id)"
        )
        lines.append(
            f"  - user-registered: {u_total} pairs "
            f"({u_differ} differ, {u_same} same, {u_no} no_id)"
        )
        lines.append("")
        lines.append(
            "  _Precision bounds on the built-in mappings were measured on "
            "Toolathlon (28-30/30 hand-labeled per bucket, Clopper-Pearson "
            "lower ≈ 77.93%). User-registered mappings are unverified: the "
            "numbers above are the observed extraction result, not a "
            "validated precision claim._"
        )
    lines.append("")
    for i, cand in enumerate(candidates, 1):
        lines.append(f"### {i}. {cand.tool}")
        lines.append("")
        lines.append(f"- origin span `{cand.origin_span_id}` → candidate span `{cand.candidate_span_id}`")
        if cand.verdict == "differ":
            wording = _ID_BRIDGE_VERDICT_DIFFER.format(
                origin_id=cand.origin_id, candidate_id=cand.candidate_id,
            )
        elif cand.verdict == "same":
            wording = _ID_BRIDGE_VERDICT_SAME.format(origin_id=cand.origin_id)
        else:
            wording = _ID_BRIDGE_VERDICT_NO_ID
        lines.append(f"- {wording}")
        lines.append("")
    return lines


def _event_lookup(amp: AmplificationEstimate | None) -> dict[str, AmplificationEvent]:
    if amp is None:
        return {}
    return {ev.span_id: ev for ev in amp.events}


def _render_pair(idx: int, ed: EnrichedDetail, ev: AmplificationEvent | None) -> list[str]:
    c = ed.detail.candidate
    lines: list[str] = []
    label = ed.pattern_label
    tool = c.agent_or_node_id

    ot = ed.origin_turn
    ct = ed.candidate_turn
    tt = ed.total_turns
    turn_phrase = (
        f"turn {ot} → re-run at turn {ct}"
        + (f" (of {tt} total)" if tt is not None else "")
        if ot is not None and ct is not None
        else "(turn indices unavailable)"
    )

    target = f"`{ed.file_path}`" if ed.file_path else (
        f"command `{ed.command[:70]}{'…' if ed.command and len(ed.command) > 70 else ''}`"
        if ed.command else f"input `{ed.input_summary}`"
    )

    modif_line: str
    if ed.file_path is None:
        modif_line = "State between calls not directly observable (no file target): *state change uncertain*."
    elif ed.modified_in_between:
        modif_line = "**File was modified in between** (Write/Edit detected). May be a legitimate re-read."
    else:
        modif_line = "No modification of this file in between. Re-read output is unchanged."

    lines.append(f"### {idx}. [{ed.category}] {label}: {tool} on {target}")
    lines.append("")
    lines.append(f"- **turns**: {turn_phrase}")
    lines.append(f"- **cosine**: {ed.detail.cosine:.4f}")
    lines.append(f"- **state**: {modif_line}")
    if ed.between_window is not None:
        # PREREG §3.1 (§9) + extensions
        # (docs/GREYZONE_B21_EXTENSION_PREREG.md §1.2, GREYZONE_B23_EXTENSION_PREREG.md §1.2)
        # per-pair wording — 4 evidence-based buckets.
        if ed.between_window == "declarative":
            obs = _BW_OBS_DECLARATIVE
        elif ed.between_window in ("no_side_effect", "payload_dependent"):
            obs = _BW_OBS_NO_CHANGE
        elif ed.between_window == "targeted_writes":
            obs = _BW_OBS_TARGETED_WRITES
        else:  # high_volume
            obs = _BW_OBS_HIGH_VOLUME
        lines.append(f"- **between_window**: `{ed.between_window}`: {obs}")
    if ev is not None:
        lines.append(
            f"- **re-consumed across {ev.turns_after} subsequent turns** "
            f"(≈{ev.waste_tokens} tokens/turn"
            + (", approx" if ev.tokens_are_approx else "")
            + f" → {ev.amp_tokens} amplification tokens)"
        )
        lines.append(
            f"- **estimated cost impact**: ${ev.lower_usd:.6f} ~ ${ev.upper_usd:.6f} "
            f"(cache-hit to cache-miss)"
        )
    lines.append("")
    return lines


_LLM_JUDGE_HEADER = "## Semantic duplicates (LLM judge)"
_LLM_JUDGE_INTRO = (
    "Message chunk pairs judged semantically equivalent by an LLM judge, "
    "even though their bytes differ (so they were not caught by the "
    "deterministic context_resend detector). Judge verdicts are "
    "non-reproducible even at temperature=0. Treat as observation, "
    "not confirmed billing waste."
)


def _render_llm_judge_section(rr: LLMJudgeResult | None) -> list[str]:
    """LLM-as-judge Semantic Duplicate prereg §7 — dedicated section."""
    if rr is None or not rr.matches:
        return []
    lines: list[str] = [_LLM_JUDGE_HEADER, "", _LLM_JUDGE_INTRO, ""]
    lines.append(f"- **matches**: {len(rr.matches)} semantic duplicate pair(s)")
    lines.append(f"- **judge calls**: {rr.total_judge_calls}")
    lines.append(f"- **judge cost**: ${rr.total_judge_cost:.6f}")
    lines.append(
        f"- **estimated resent tokens**: {rr.total_semantic_resent_tokens} "
        f"(≈ downstream input token attribution of the paraphrase re-sends)"
    )
    lines.append(f"- **estimated resent cost**: ${rr.total_semantic_resent_cost:.6f}")
    if rr.matches:
        judge_model = rr.matches[0].judge_model
        lines.append(
            f"- **judge model**: `{judge_model}` · "
            "results non-reproducible (LLM-as-judge)"
        )
    lines.append("")
    top = sorted(rr.matches, key=lambda m: m.confidence, reverse=True)[:5]
    if top:
        lines.append("### Top offenders (by judge confidence)")
        lines.append("")
        for m in top:
            lines.append(
                f"- confidence {m.confidence:.2f}: "
                f"origin `{m.origin_llm_span_id}` vs candidate "
                f"`{m.candidate_llm_span_id}`: {m.reasoning}"
            )
        lines.append("")
    return lines


_REDUNDANT_READ_HEADER = "## Redundant reads"
_REDUNDANT_READ_INTRO = (
    "Tool spans where the same read tool was invoked on the same target "
    "within this trace, with no intervening write to that target and no "
    "Bash/PowerShell in between. `confirmed=True` means the two outputs "
    "were byte-identical; `confirmed=False` means the outputs differ (state "
    "may have changed via an unobserved path, user judgment)."
)


def _render_redundant_read_section(
    rr: RedundantReadResult | None,
) -> list[str]:
    """Redundant Read prereg §6 — dedicated markdown section."""
    if rr is None or not rr.events:
        return []
    lines: list[str] = [_REDUNDANT_READ_HEADER, "", _REDUNDANT_READ_INTRO, ""]
    lines.append(f"- **events**: {len(rr.events)} redundant read(s)")
    lines.append(
        f"- **waste tokens**: {rr.total_waste_tokens} "
        f"(≈ downstream input tokens that would be spent re-consuming these reads)"
    )
    lines.append(f"- **waste cost**: ${rr.total_waste_cost:.6f}")
    lines.append(f"- **cost accuracy**: `{rr.cost_accuracy_flag}`")
    lines.append("")
    top = sorted(rr.events, key=lambda e: e.waste_cost, reverse=True)[:5]
    if top:
        lines.append("### Top offenders (by waste cost)")
        lines.append("")
        for e in top:
            confirmed_marker = "✓" if e.confirmed else "?"
            lines.append(
                f"- {confirmed_marker} `{e.tool_name}` on `{e.target[:80]}`: "
                f"{e.waste_tokens} tokens, ${e.waste_cost:.6f}"
            )
        lines.append("")
    return lines


_COST_SUMMARY_HEADER = "## Cost summary"


def _render_cost_summary(summary: TraceCostSummary) -> list[str]:
    """Cost Attribution Completion prereg §5.2 — top-of-report cost block."""
    if summary.total_analyzed_cost == 0.0 and summary.total_waste_cost == 0.0:
        return []
    lines: list[str] = [_COST_SUMMARY_HEADER, ""]
    lines.append(f"- **Total analyzed**: ${summary.total_analyzed_cost:.6f}")
    lines.append(
        f"- **Total waste (detected)**: ${summary.total_waste_cost:.6f} "
        f"({summary.waste_ratio:.1%})"
    )
    lines.append(f"- **Cost accuracy**: `{summary.accuracy_flag}`")
    if summary.detector_breakdown:
        lines.append("")
        lines.append("Breakdown by detector:")
        for detector, cost in summary.detector_breakdown.items():
            lines.append(f"  - {detector}: ${cost:.6f}")
    lines.append("")
    return lines


_CONTEXT_RESEND_HEADER = "## Context resend"
_CONTEXT_RESEND_INTRO = (
    "Message chunks that appear in the input of two or more LLM calls within "
    "this trace, byte-exact by sha256. System-role chunks are exempt. First "
    "occurrence of each chunk is not counted (it is the necessary payload); "
    "occurrences from the second onward are recorded as resent."
)
_CONTEXT_RESEND_LEGACY_HINT = (
    "_Cost figures below are estimated: the ingest layer received only a "
    "single-rate cost table. Pass `input_cost_table` (and optionally "
    "`output_cost_table`) at ingest time for accurate per-side monetization._"
)


def _summary_context_resend_line(cr: ContextResendResult | None) -> list[str]:
    """One-line summary of context resend for the top Result banner."""
    if cr is None:
        return []
    if cr.total_llm_input_tokens == 0 and not cr.resent_events:
        return []
    denom = cr.total_llm_input_tokens
    ratio = (cr.resent_input_tokens / denom) if denom > 0 else 0.0
    return [
        f"- **Context resend**: {len(cr.resent_events)} resent chunk(s), "
        f"{cr.resent_input_tokens} of {cr.total_llm_input_tokens} input tokens "
        f"({ratio:.1%}). See section below."
    ]


def _render_context_resend_section(cr: ContextResendResult | None) -> list[str]:
    """Prereg §5-integrated markdown section. Empty list when nothing to render."""
    if cr is None:
        return []
    if cr.total_llm_input_tokens == 0 and not cr.resent_events:
        return []
    lines: list[str] = [_CONTEXT_RESEND_HEADER, "", _CONTEXT_RESEND_INTRO, ""]
    denom_toks = cr.total_llm_input_tokens
    denom_cost = cr.total_llm_input_cost
    ratio_toks = (cr.resent_input_tokens / denom_toks) if denom_toks > 0 else 0.0
    ratio_cost = (cr.resent_cost / denom_cost) if denom_cost > 0 else 0.0
    lines.append(f"- **events**: {len(cr.resent_events)} resent chunk occurrence(s)")
    lines.append(
        f"- **resent input tokens**: {cr.resent_input_tokens} of "
        f"{cr.total_llm_input_tokens} ({ratio_toks:.1%})"
    )
    lines.append(
        f"- **resent input cost**: ${cr.resent_cost:.6f} of "
        f"${cr.total_llm_input_cost:.6f} ({ratio_cost:.1%})"
    )
    lines.append(f"- **cost accuracy**: `{cr.cost_accuracy_flag}`")
    if cr.cost_accuracy_flag == "estimated":
        lines.append("")
        lines.append(_CONTEXT_RESEND_LEGACY_HINT)
    lines.append("")
    if cr.resent_events:
        # Aggregate by originating LLM span for a compact overview instead of
        # listing every event (a long trace may have thousands).
        by_span: dict[str, dict[str, int | float]] = {}
        for ev in cr.resent_events:
            slot = by_span.setdefault(
                ev.llm_span_id, {"count": 0, "toks": 0, "cost": 0.0}
            )
            slot["count"] += 1
            slot["toks"] += ev.resent_input_tokens
            slot["cost"] += ev.resent_cost
        lines.append("### Top offenders (by LLM call)")
        lines.append("")
        top = sorted(by_span.items(), key=lambda kv: kv[1]["cost"], reverse=True)[:5]
        for span_id, agg in top:
            lines.append(
                f"- span `{span_id}`: {agg['count']} resent chunks, "
                f"{agg['toks']} tokens, ${agg['cost']:.6f}"
            )
        lines.append("")
    return lines


def _waste_rate_line(wr: WasteRateMetric | None) -> str | None:
    """One-line Waste-rate summary (WASTE_RATE_METRIC_PREREG §6.1).

    Emits None when `wr` is None or the trace was excluded (no LLM input
    to divide against). Otherwise renders union WR_char always, and
    union WR_cost when defined.
    """
    if wr is None or wr.excluded_reason is not None or wr.union_wr_char is None:
        return None
    pct_char = f"{wr.union_wr_char * 100:.1f}%"
    if wr.union_wr_cost is None:
        return f"- **Waste rate (bytes)**: {pct_char} of input bytes flagged (union of 4 detectors)."
    pct_cost = f"{wr.union_wr_cost * 100:.1f}%"
    return (
        f"- **Waste rate**: {pct_char} of input bytes / {pct_cost} of input cost "
        f"flagged as waste (union of 4 detectors)."
    )


_NONTEXT_SHARE_FLOOR_PCT = 1.0


def _render_ingest_notes(trace: Trace) -> list[str]:
    """What the adapter dropped or rewrote before any detector ran.

    Silent when the trace file mapped cleanly — the section appearing at all
    is the signal. Every line answers the same question: is a number below
    computed on less, or on other, than what was in the file?
    """
    notes = trace.metadata.get("ingest_notes") or {}
    if not notes:
        return []

    items: list[str] = []

    n_orphan = notes.get("orphan_tool_use_skipped", 0)
    if n_orphan:
        plural = "" if n_orphan == 1 else "s"
        items.append(
            f"**{n_orphan} tool call{plural} dropped**: the call was made "
            f"but no result was recorded (a session that ended mid-call). "
            f"Nothing below counts it."
        )

    if notes.get("no_tool_use_recovery"):
        items.append(
            "**no tool call was paired**: this report covers the session "
            "envelope only, so a waste rate of 0 here means 'nothing to "
            "measure', not 'nothing wasted'."
        )

    unknown = notes.get("unknown_block_types") or {}
    if unknown:
        detail = ", ".join(f"`{k}` ×{v}" for k, v in sorted(unknown.items()))
        items.append(
            f"**content blocks of an unrecognized type were left out of span "
            f"creation**: {detail}."
        )

    nontext = notes.get("nontext_result_blocks") or {}
    n_chars = notes.get("nontext_result_chars", 0)
    total = sum(len(sp.output_text or "") for sp in trace.spans)
    pct = (n_chars / total * 100) if total else 0.0
    # Gated because a `tool_reference` block costs ~52 characters and appears
    # in most sessions: saying so on every report is how a reader learns to
    # skip the section. On 71 real Claude Code sessions the two populations
    # separate with nothing in between - 36 traces under 1%, 13 above 10%,
    # zero in the gap - so the cut sits in empty space rather than on a
    # judgement call. The JSON report carries the raw counts either way.
    if nontext and pct >= _NONTEXT_SHARE_FLOOR_PCT:
        detail = ", ".join(f"`{k}` ×{v}" for k, v in sorted(nontext.items()))
        share = f" ({pct:.1f}% of it)"
        items.append(
            f"**{n_chars:,} characters of the measured text{share} are "
            f"non-text tool results rendered as JSON**: {detail}. Byte-based "
            f"rates count those bytes, so a screenshot is measured at the "
            f"size of its encoding rather than what it shows."
        )

    if not items:
        return []

    lines = ["## What the numbers were computed on", ""]
    lines.extend(f"- {it}" for it in items)
    lines.append("")
    return lines


def render_markdown(
    trace: Trace,
    cr: CascadeResult,
    details: list[WasteDetail],
    *,
    no_snippets: bool = False,
    snippet_len: int = _SNIPPET_LEN,
    amplification: AmplificationEstimate | None = None,
    user_tools: "ResolvedTools | None" = None,
    context_resend: ContextResendResult | None = None,
    redundant_read: RedundantReadResult | None = None,
    llm_judge: LLMJudgeResult | None = None,
    waste_rate: WasteRateMetric | None = None,
) -> str:
    """CascadeResult + WasteDetail list -> markdown string.

    Per-pair rendering enriches with file_path/command, turn numbers,
    intervening-edit check, and pattern label.

    `user_tools` (optional): ResolvedTools from clew.yaml. When None,
    behavior is bit-identical to pre-clew.yaml releases (§3 gate).

    `context_resend` (optional): result from clew.detect.context_resend.
    When None or when the result has no events and no LLM input tokens,
    the section is omitted (pre-Context-Resend-prereg output preserved).

    `redundant_read` (optional): result from clew.detect.redundant_read.
    When None or when events list is empty, the section is omitted
    (pre-Redundant-Read-prereg output preserved).
    """
    lines: list[str] = []
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines.append("# Boxdawn Waste Report")
    lines.append("")
    lines.append(f"- **trace_id**: `{trace.trace_id}`")
    lines.append(f"- **analyzed**: {now}")
    lines.append(f"- **detector params**: φ={_PHI}, N={_N}, model={_MODEL}")
    lines.append("")

    lines.extend(_render_ingest_notes(trace))

    # Cost Attribution Completion prereg §5.2 — top-of-report cost summary.
    # Placed before existing content so pitch-critical dollar figures land
    # on-screen first.
    cost_summary = build_cost_summary(
        trace, cr, context_resend, redundant_read, llm_judge,
    )
    lines.extend(_render_cost_summary(cost_summary))

    # Enrich once. Used by (a) coverage banner in the waste-0 branch too,
    # (b) category breakdown / per-pair rendering below.
    enrichment = enrich(trace, details, user_tools)
    cov = coverage_stats(trace, enrichment.enriched, user_tools)
    id_bridge = scan_id_bridge_candidates(trace, user_tools)

    if not cr.wasteful:
        lines.append("## Result")
        lines.append("")
        lines.append("- **Waste detection (tool cascade)**: no waste detected (wasteful=False).")
        lines.extend(_summary_duplicate_creation_line(id_bridge))
        lines.extend(_summary_context_resend_line(context_resend))
        wr_line = _waste_rate_line(waste_rate)
        if wr_line is not None:
            lines.append(wr_line)
        lines.append("")
        # Coverage line A — ALWAYS rendered, including waste-0.
        # PREREG §1.1 Q2 rationale: a low-coverage user seeing "no waste"
        # alone reads it as "we're clean" while Boxdawn is blind to most of
        # their tool inventory. False reassurance is worse than false alarm.
        if cov["unique_tools_in_trace"] > 0:
            lines.append("- " + _COVERAGE_LINE_A.format(
                recognized=cov["recognized_tools"],
                unique_in_trace=cov["unique_tools_in_trace"],
                pct=cov["coverage_ratio"],
            ))
            provenance = _format_coverage_provenance(cov)
            if provenance is not None:
                for line in provenance:
                    lines.append("- " + line)
            line_c = _format_coverage_line_c(cov["unrecognized_tool_names"])
            if line_c is not None:
                lines.append("- " + line_c)
            lines.append("")
        # PREREG §1.6 decision 4 — Duplicate creation check must render even
        # when cascade waste is 0, otherwise a real duplicate creation is
        # hidden behind "no waste detected".
        if id_bridge:
            lines.extend(_render_id_bridge_section(id_bridge))
        # Context Resend section — same principle as duplicate creation check:
        # visible even in the waste-0 branch. LLM input resend can be present
        # without any tool-side cascade waste.
        lines.extend(_render_context_resend_section(context_resend))
        # Redundant Read section — additive, same waste-0 principle.
        lines.extend(_render_redundant_read_section(redundant_read))
        # LLM Judge section — opt-in extension of context resend.
        lines.extend(_render_llm_judge_section(llm_judge))
        lines.append(_FOOTER)
        return "\n".join(lines)

    lines.append("## Result")
    lines.append("")
    lines.append(f"- **Waste detection (tool cascade)**: {len(cr.waste_span_ids)} wasteful span(s).")
    lines.extend(_summary_duplicate_creation_line(id_bridge))
    lines.extend(_summary_context_resend_line(context_resend))
    wr_line = _waste_rate_line(waste_rate)
    if wr_line is not None:
        lines.append(wr_line)
    lines.append("")
    lines.append(f"- **wasted spans**: {len(cr.waste_span_ids)}")
    if enrichment.enriched:
        cat_counts: dict[str, int] = {}
        for ed in enrichment.enriched:
            cat_counts[ed.category] = cat_counts.get(ed.category, 0) + 1
        cat_line = ", ".join(
            f"{cat_counts.get(c, 0)} {c}"
            for c in ("error_repeat", "side_effect", "idempotent", "unclassified")
        )
        lines.append(f"- **category breakdown**: {cat_line}")

        # Coverage banner. PREREG §1.1 Q1 rationale: coverage relativity applies
        # to between_window only (category classification already handles unknown
        # tools honestly by routing them to `unclassified`). Placing this line at
        # the header level would over-signal that the whole report is uncertain,
        # training readers to ignore it. So the banner sits here — right before
        # the Redundant-invocation candidates section it actually qualifies.
        if cov["unique_tools_in_trace"] > 0:
            lines.append("- " + _COVERAGE_LINE_A.format(
                recognized=cov["recognized_tools"],
                unique_in_trace=cov["unique_tools_in_trace"],
                pct=cov["coverage_ratio"],
            ))
            provenance = _format_coverage_provenance(cov)
            if provenance is not None:
                for line in provenance:
                    lines.append("- " + line)
        # Coverage line B — only when there is at least one idempotent pair.
        # Zero-context number is confusing without pairs to point at.
        idem_count = cat_counts.get("idempotent", 0)
        if idem_count > 0:
            lines.append("- " + _COVERAGE_LINE_B.format(
                pairs_affected=cov["pairs_with_unrecognized_in_between"],
                idempotent_total=cov["idempotent_pairs_total"],
            ))
        line_c = _format_coverage_line_c(cov["unrecognized_tool_names"])
        if line_c is not None:
            lines.append("- " + line_c)

        # PREREG §2.2 / §3.1 (§9) + extensions
        # (docs/GREYZONE_B21_EXTENSION_PREREG.md §1.3, GREYZONE_B23_EXTENSION_PREREG.md §1.3)
        # 3 top-level tiers, 4 aggregate lines, ordered by evidence strength:
        #   indicated (no state change):
        #     by tool identity → declarative  (interval NOT examined)
        #     by interval scan → no_side_effect + payload_dependent  (interval examined)
        #   high_volume            → high_volume  (own tier — b23, 82.78% lower)
        #   writes to other targets → targeted_writes  (own tier, own evidence)
        # "not established" group removed (empty after b23).
        bw_counts: dict[str, int] = {}
        for ed in enrichment.enriched:
            if ed.category == "idempotent" and ed.between_window:
                bw_counts[ed.between_window] = bw_counts.get(ed.between_window, 0) + 1
        idem_total = cat_counts.get("idempotent", 0)
        if idem_total > 0:
            by_identity = bw_counts.get("declarative", 0)
            by_scan = (
                bw_counts.get("no_side_effect", 0)
                + bw_counts.get("payload_dependent", 0)
            )
            no_change_indicated = by_identity + by_scan
            high_volume_count = bw_counts.get("high_volume", 0)
            writes_other_targets = bw_counts.get("targeted_writes", 0)
            lines.append(
                f"- **Redundant-invocation candidates**: {idem_total} idempotent pairs. "
                f"{_BW_HEADER_NO_VERDICT}"
            )
            lines.append(
                f"  - idempotent {idem_total}: "
                f"{no_change_indicated} with no state change indicated, "
                f"{high_volume_count} with high tool volume, "
                f"{writes_other_targets} with writes to other targets"
            )
            lines.append(f"    - indicated, by tool identity: declarative {by_identity}")
            lines.append(
                f"    - indicated, by interval scan: "
                f"no_side_effect {bw_counts.get('no_side_effect', 0)}; "
                f"payload_dependent {bw_counts.get('payload_dependent', 0)}"
            )
            if high_volume_count > 0:
                lines.append(f"    - high_volume: {high_volume_count}")
                lines.append(
                    "      - Validated on Toolathlon: 29/30 hand-labeled TRUE "
                    "(95% two-sided Clopper-Pearson lower ≈ 82.78%). "
                    "One same-target repeated write observed."
                )
            if writes_other_targets > 0:
                lines.append(
                    f"    - writes to other targets: "
                    f"targeted_writes {writes_other_targets}"
                )
                lines.append(
                    "      - Validated on Toolathlon: 28/30 hand-labeled TRUE "
                    "(95% two-sided Clopper-Pearson lower ≈ 77.93%). "
                    "Two write-then-revert observed."
                )
            lines.append(f"  - _{_BW_JUDGE_DELEGATION}_")

    if amplification is not None and amplification.n_events > 0:
        lo = amplification.lower_usd
        up = amplification.upper_usd
        approx_note = " (some events use char/1.3 approximation)" if amplification.any_approx else ""
        lines.append(
            f"- **wasted output re-consumed across "
            f"{sum(ev.turns_after for ev in amplification.events)} subsequent turns** "
            f"in total (amplification tokens = {amplification.total_amp_tokens})"
        )
        lines.append(
            f"- **estimated cost impact**: ${lo:.6f} ~ ${up:.6f} "
            f"(cache-hit lower to cache-miss upper, estimated){approx_note}"
        )
        lines.append(
            f"- **events counted**: {amplification.n_events} "
            f"(skipped {amplification.n_skipped_prev_eq_next} prev==next retry, "
            f"{amplification.n_skipped_no_metadata} without metadata, "
            f"{amplification.n_skipped_error} error-response spans)"
        )
    elif amplification is not None:
        lines.append(
            f"- **estimated cost impact**: unknown "
            f"(no eligible events after skip: "
            f"{amplification.n_skipped_prev_eq_next} prev==next, "
            f"{amplification.n_skipped_no_metadata} no-metadata, "
            f"{amplification.n_skipped_error} error-response spans)"
        )
    else:
        lines.append("- **estimated cost impact**: unknown (adapter metadata unavailable)")

    lines.append("")

    lines.append("## Wasted Span Details")
    lines.append("")

    if enrichment.n_skipped_error > 0:
        lines.append(
            f"_Skipped **{enrichment.n_skipped_error}** error-response span(s) "
            f"(is_error=True tool_result, not waste; §29.2)._"
        )
        lines.append("")
    ev_lookup = _event_lookup(amplification)
    for i, ed in enumerate(enrichment.enriched, 1):
        ev = ev_lookup.get(ed.detail.candidate.span_id)
        lines.extend(_render_pair(i, ed, ev))

    if not no_snippets:
        lines.append("## Snippets")
        lines.append("")
        for i, wd in enumerate(details, 1):
            lines.append(f"**{i}. {wd.candidate.agent_or_node_id}** (repeat)")
            snip = wd.candidate.output_text[:snippet_len]
            lines.append(f"> {snip}")
            lines.append("")

    # PREREG §1.6 decision 2 — position between Wasted Span Details and
    # Possible causes. Reports discovery, not explanation.
    lines.extend(_render_id_bridge_section(id_bridge))

    # Context Resend section — sibling of the duplicate creation check.
    # Positioned right after the id_bridge section for the same reason: report
    # observations, not diagnoses.
    lines.extend(_render_context_resend_section(context_resend))

    # Redundant Read section — right after Context Resend, same principle.
    lines.extend(_render_redundant_read_section(redundant_read))

    # LLM Judge section — right after Redundant reads.
    lines.extend(_render_llm_judge_section(llm_judge))

    lines.append(_POSSIBLE_CAUSES)
    lines.append(_CATEGORY_CAUSES)
    lines.append(_CATEGORY_NOTE)
    lines.append(_FOOTER)
    return "\n".join(lines)
