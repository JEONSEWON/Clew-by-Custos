"""src/clew/report/json_report.py - machine-oriented JSON report renderer."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from clew.cost.amplification import AmplificationEstimate
from clew.detect.cascade import CascadeResult
from clew.model import Trace
from clew.report._enrich import coverage_stats, enrich, scan_id_bridge_candidates
from clew.report._model import WasteDetail

_PHI = 0.514345
_N = 2
_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

_SNIPPET_LEN = 80


def render_json(
    trace: Trace,
    cr: CascadeResult,
    details: list[WasteDetail],
    *,
    no_snippets: bool = False,
    snippet_len: int = _SNIPPET_LEN,
    amplification: AmplificationEstimate | None = None,
) -> str:
    """CascadeResult + WasteDetail list -> JSON string (indent=2).

    Snippet: output_text[:snippet_len] by default (excludes the key entirely if no_snippets=True).
    Includes frozen parameters (phi, N, model) at the report header.
    """
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    enrichment = enrich(trace, details)
    cov = coverage_stats(trace, enrichment.enriched)
    id_bridge = scan_id_bridge_candidates(trace)
    ev_by_sid = {ev.span_id: ev for ev in amplification.events} if amplification else {}

    waste_details_list = []
    for ed in enrichment.enriched:
        wd = ed.detail
        wt = wd.waste_tokens
        wc = wd.waste_cost
        entry: dict = {
            "origin_node": wd.origin.agent_or_node_id,
            "repeat_node": wd.candidate.agent_or_node_id,
            "cosine": round(wd.cosine, 6),
            "tokens_wasted": wt if wt is not None else "unknown",
            "cost_wasted": round(wc, 8) if wc is not None else "unknown",
            "pattern_label": ed.pattern_label,
            "file_path": ed.file_path,
            "command": ed.command,
            "origin_turn": ed.origin_turn,
            "candidate_turn": ed.candidate_turn,
            "total_turns": ed.total_turns,
            "modified_in_between": ed.modified_in_between,
            "state_change_uncertain": ed.state_change_uncertain,
            "category": ed.category,
        }
        # PREREG §0.4 backward compat: field present iff category == "idempotent".
        # Absent (not null) for other categories — old 4-label consumers unaffected.
        if ed.between_window is not None:
            entry["between_window"] = ed.between_window
        ev = ev_by_sid.get(wd.candidate.span_id)
        if ev is not None:
            entry["turns_after"] = ev.turns_after
            entry["amp_tokens"] = ev.amp_tokens
            entry["cost_lower_usd"] = round(ev.lower_usd, 8)
            entry["cost_upper_usd"] = round(ev.upper_usd, 8)
            entry["tokens_are_approx"] = ev.tokens_are_approx
        if not no_snippets:
            entry["snippet"] = wd.candidate.output_text[:snippet_len]
        waste_details_list.append(entry)

    total_tok = cr.waste_tokens if cr.waste_tokens > 0 else None
    total_cost = cr.waste_cost if cr.waste_cost > 0.0 else None

    amp_block: dict
    if amplification is not None:
        amp_block = {
            "cost_lower_usd": round(amplification.lower_usd, 8),
            "cost_upper_usd": round(amplification.upper_usd, 8),
            "amp_tokens": amplification.total_amp_tokens,
            "n_events": amplification.n_events,
            "n_skipped_prev_eq_next": amplification.n_skipped_prev_eq_next,
            "n_skipped_no_metadata": amplification.n_skipped_no_metadata,
            "n_skipped_error": amplification.n_skipped_error,
            "approx_events": amplification.approx_events,
            "model_key": amplification.model_key,
        }
    else:
        amp_block = {
            "cost_lower_usd": "unknown",
            "cost_upper_usd": "unknown",
            "amp_tokens": "unknown",
            "n_events": 0,
            "note": "adapter metadata unavailable (non-CC source)",
        }

    report: dict = {
        "trace_id": trace.trace_id,
        "analyzed": now,
        "detector_params": {
            "phi": _PHI,
            "n": _N,
            "model": _MODEL,
        },
        "wasteful": cr.wasteful,
        "waste_span_count": len(cr.waste_span_ids),
        "total_tokens_wasted": total_tok if total_tok is not None else "unknown",
        "total_cost_wasted": round(total_cost, 8) if total_cost is not None else "unknown",
        "amplification": amp_block,
        "n_skipped_error_details": enrichment.n_skipped_error,
        "category_counts": {
            c: sum(1 for ed in enrichment.enriched if ed.category == c)
            for c in ("error_repeat", "side_effect", "idempotent", "unclassified")
        },
        # PREREG §1.3 / §2.2 (§9): between_window sub-classification of idempotent.
        "between_window_counts": {
            k: sum(
                1 for ed in enrichment.enriched
                if ed.category == "idempotent" and ed.between_window == k
            )
            for k in ("declarative", "no_side_effect", "payload_dependent",
                      "targeted_writes", "high_volume")
        },
        # PREREG docs/COVERAGE_TRANSPARENCY_PREREG.md §1.2: tool-mapping
        # coverage metadata. Additive field — old consumers ignore it.
        "coverage_stats": cov,
        # PREREG docs/ID_BRIDGE_PRODUCTION_PREREG.md §1.7: same-input
        # side-effect pair scan with entity-ID extraction. Additive.
        "id_bridge_candidates": [
            {
                "origin_span_id": c.origin_span_id,
                "candidate_span_id": c.candidate_span_id,
                "tool": c.tool,
                "verdict": c.verdict,
                "origin_id": c.origin_id,
                "candidate_id": c.candidate_id,
            }
            for c in id_bridge
        ],
        "waste_details": waste_details_list,
        "note": (
            "Detection thresholds were calibrated on synthetic traces; "
            "real-trace calibration is in progress. Borderline matches "
            "(cosine near 0.51) deserve human review. Amplification cost "
            "is estimated saving potential (cache-hit lower to cache-miss upper), "
            "not measured — assumes wasted output is re-consumed each subsequent turn. "
            "Category labels are report-only annotations; detection is unchanged. "
            "Whether an idempotent re-run is truly waste depends on user context. "
            "between_window records how the interval was classified; "
            "no state-change verdict is rendered."
        ),
    }

    return json.dumps(report, ensure_ascii=False, indent=2)
