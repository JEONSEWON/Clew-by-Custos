"""src/clew/report/markdown.py - human-facing markdown report renderer."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from clew.cost.amplification import AmplificationEstimate, AmplificationEvent
from clew.detect.cascade import CascadeResult
from clew.model import Trace
from clew.report._enrich import (
    EnrichedDetail,
    IdBridgeCandidate,
    coverage_stats,
    enrich,
    scan_id_bridge_candidates,
)
from clew.report._model import WasteDetail

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
    "(cosine near phi) deserve human review — this applies to "
    "non-tool spans; tool spans use exact sha256 identity._\n\n"
    "_Cost is estimated saving potential, not measured — assumes the "
    "wasted output is re-consumed each subsequent turn (structural "
    "assumption). Range spans cache-hit (lower) to cache-miss (upper). "
    "Attribution assumes Sonnet pricing._"
)

_POSSIBLE_CAUSES = (
    "## Possible causes\n"
    "\n"
    "Repeated file re-reads commonly stem from one of:\n"
    "- the agent not retaining what it already read (no context caching)\n"
    "- prompts that re-trigger verification\n"
    "- context truncation dropping earlier reads\n"
    "\n"
    "This trace cannot isolate which — inspect the agent's file-handling logic.\n"
    "For Bash requeries the state between calls is not directly observable from the "
    "trace; treat those as *state change uncertain* — the tool does not render a "
    "final waste verdict.\n"
)

_CATEGORY_CAUSES = (
    "## What each category typically points to\n"
    "\n"
    "These are common origins — not diagnoses. Detection is unchanged.\n"
    "\n"
    "- **error_repeat** — the agent received the same error response twice. "
    "Usually the tool arguments are wrong and the agent re-runs with the "
    "same arguments without addressing the error message.\n"
    "- **side_effect** — a state-changing tool was invoked twice with the "
    "same arguments. Beyond wasted tokens, real side effects (duplicate "
    "sends, duplicate creates, etc.) may have occurred. Confirm the "
    "operation is safe to run more than once.\n"
    "- **idempotent** — a read-only or declarative tool was called "
    "repeatedly. This category assumes the tool has no side effect, based "
    "on the tool name; whether that holds in your setup, and whether the "
    "underlying state truly did not change between the two calls, needs "
    "verification against your execution context.\n"
    "- **unclassified** — the tool's effect depends on the arguments passed "
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
    "No verdict is rendered — refer to context and judge whether each was intentional."
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
    "That is the right test for reads — a re-read that returns the same "
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
    "The `[category]` tag on each waste pair is a **report-only annotation** — "
    "it does not affect what was flagged as waste. Detection is unchanged.\n"
    "\n"
    "- `error_repeat` — output matches an error pattern (same call repeated after failure)\n"
    "- `side_effect` — tool with known state-changing effect "
    "(e.g. `Edit`, `github-create_pull_request`)\n"
    "- `idempotent` — tool is read-only or declarative "
    "(e.g. `Read`, `filesystem-list_directory`); whether *this* re-run is actually "
    "wasted depends on user context (was the state truly unchanged?)\n"
    "- `unclassified` — tool name not in either mapping. Includes `Bash`, `PowerShell`, "
    "`local-python-execute`, `terminal-run_command`, and `bigquery_run_query`: their "
    "effect depends on the payload, not the tool name.\n"
    "\n"
    "The mapping is by tool name only — never inferred from name substrings.\n"
)


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
            "lower ≈ 77.93%). User-registered mappings are unverified — the "
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
    o, c = ed.detail.origin, ed.detail.candidate
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
        modif_line = "State between calls not directly observable (no file target) — *state change uncertain*."
    elif ed.modified_in_between:
        modif_line = "**File was modified in between** (Write/Edit detected) — may be a legitimate re-read."
    else:
        modif_line = "No modification of this file in between — re-read output is unchanged."

    lines.append(f"### {idx}. [{ed.category}] {label} — {tool} on {target}")
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
        lines.append(f"- **between_window**: `{ed.between_window}` — {obs}")
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


def render_markdown(
    trace: Trace,
    cr: CascadeResult,
    details: list[WasteDetail],
    *,
    no_snippets: bool = False,
    snippet_len: int = _SNIPPET_LEN,
    amplification: AmplificationEstimate | None = None,
    user_tools: "ResolvedTools | None" = None,
) -> str:
    """CascadeResult + WasteDetail list -> markdown string.

    Per-pair rendering enriches with file_path/command, turn numbers,
    intervening-edit check, and pattern label.

    `user_tools` (optional): ResolvedTools from clew.yaml. When None,
    behavior is bit-identical to pre-clew.yaml releases (§3 gate).
    """
    lines: list[str] = []
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines.append("# Clew Waste Report")
    lines.append("")
    lines.append(f"- **trace_id**: `{trace.trace_id}`")
    lines.append(f"- **analyzed**: {now}")
    lines.append(f"- **detector params**: φ={_PHI}, N={_N}, model={_MODEL}")
    lines.append("")

    # Enrich once. Used by (a) coverage banner in the waste-0 branch too,
    # (b) category breakdown / per-pair rendering below.
    enrichment = enrich(trace, details, user_tools)
    cov = coverage_stats(trace, enrichment.enriched, user_tools)
    id_bridge = scan_id_bridge_candidates(trace, user_tools)

    if not cr.wasteful:
        lines.append("## Result: no waste detected")
        lines.append("")
        lines.append("No wasteful patterns found (wasteful=False).")
        lines.append("")
        # Coverage line A — ALWAYS rendered, including waste-0.
        # PREREG §1.1 Q2 rationale: a low-coverage user seeing "no waste"
        # alone reads it as "we're clean" while Clew is blind to most of
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
        lines.append(_FOOTER)
        return "\n".join(lines)

    lines.append("## Result: WASTE DETECTED")
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
                f"  - idempotent {idem_total} — "
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
                    f"      - Validated on Toolathlon: 29/30 hand-labeled TRUE "
                    f"(95% two-sided Clopper-Pearson lower ≈ 82.78%). "
                    f"One same-target repeated write observed."
                )
            if writes_other_targets > 0:
                lines.append(
                    f"    - writes to other targets: "
                    f"targeted_writes {writes_other_targets}"
                )
                lines.append(
                    f"      - Validated on Toolathlon: 28/30 hand-labeled TRUE "
                    f"(95% two-sided Clopper-Pearson lower ≈ 77.93%). "
                    f"Two write-then-revert observed."
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
            f"(is_error=True tool_result — not waste; §29.2)._"
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

    lines.append(_POSSIBLE_CAUSES)
    lines.append(_CATEGORY_CAUSES)
    lines.append(_CATEGORY_NOTE)
    lines.append(_FOOTER)
    return "\n".join(lines)
