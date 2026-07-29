"""src/clew/report/markdown.py - human-facing markdown report renderer."""

from __future__ import annotations

from datetime import datetime, timezone

from clew.cost.amplification import AmplificationEstimate, AmplificationEvent
from clew.detect.cascade import CascadeResult
from clew.model import Trace
from clew.report._enrich import EnrichedDetail, enrich
from clew.report._model import WasteDetail

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
) -> str:
    """CascadeResult + WasteDetail list -> markdown string.

    Per-pair rendering enriches with file_path/command, turn numbers,
    intervening-edit check, and pattern label.
    """
    lines: list[str] = []
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines.append("# Clew Waste Report")
    lines.append("")
    lines.append(f"- **trace_id**: `{trace.trace_id}`")
    lines.append(f"- **analyzed**: {now}")
    lines.append(f"- **detector params**: φ={_PHI}, N={_N}, model={_MODEL}")
    lines.append("")

    if not cr.wasteful:
        lines.append("## Result: no waste detected")
        lines.append("")
        lines.append("No wasteful patterns found (wasteful=False).")
        lines.append("")
        lines.append(_FOOTER)
        return "\n".join(lines)

    lines.append("## Result: WASTE DETECTED")
    lines.append("")
    lines.append(f"- **wasted spans**: {len(cr.waste_span_ids)}")

    # Enrich once — reused for category breakdown + per-pair rendering below.
    enrichment = enrich(trace, details)
    if enrichment.enriched:
        cat_counts: dict[str, int] = {}
        for ed in enrichment.enriched:
            cat_counts[ed.category] = cat_counts.get(ed.category, 0) + 1
        cat_line = ", ".join(
            f"{cat_counts.get(c, 0)} {c}"
            for c in ("error_repeat", "side_effect", "idempotent", "unclassified")
        )
        lines.append(f"- **category breakdown**: {cat_line}")

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

    lines.append(_POSSIBLE_CAUSES)
    lines.append(_CATEGORY_CAUSES)
    lines.append(_CATEGORY_NOTE)
    lines.append(_FOOTER)
    return "\n".join(lines)
