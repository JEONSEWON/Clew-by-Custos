"""src/clew/report/json_report.py - machine-oriented JSON report renderer."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from clew.cost.amplification import AmplificationEstimate
from clew.detect.cascade import CascadeResult
from clew.detect.context_resend import ContextResendResult
from clew.model import Trace
from clew.report._enrich import coverage_stats, enrich, scan_id_bridge_candidates
from clew.report._model import WasteDetail

if TYPE_CHECKING:
    from clew.config import ResolvedTools

_PHI = 0.514345
_N = 2
_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

_SNIPPET_LEN = 80


def _user_tools_block(tools: "ResolvedTools | None") -> dict | None:
    """§2.5 audit block for JSON reports. None when clew.yaml not loaded."""
    if tools is None or not tools.has_user_tools:
        return None
    return {
        "user_names": sorted(tools.user_names),
        "override_names": sorted(tools.override_names),
        "overrides": [
            {"tool": name, "built_in": built_in, "user": user_cat}
            for name, built_in, user_cat in tools.override_details
        ],
    }


def _context_resend_block(cr: ContextResendResult | None) -> dict | None:
    """Context Resend Detector JSON block (prereg §5/§6).

    Returns None when the detector wasn't run (context_resend is None) or ran
    on a trace with no LLM calls (total_llm_input_tokens == 0 and no events).
    Backward compat: old consumers see no new keys unless the detector was
    invoked with meaningful data.
    """
    if cr is None:
        return None
    if cr.total_llm_input_tokens == 0 and not cr.resent_events:
        return None
    denom_tokens = cr.total_llm_input_tokens
    denom_cost = cr.total_llm_input_cost
    ratio_tokens = (cr.resent_input_tokens / denom_tokens) if denom_tokens > 0 else 0.0
    ratio_cost = (cr.resent_cost / denom_cost) if denom_cost > 0 else 0.0
    return {
        "resent_input_tokens": cr.resent_input_tokens,
        "resent_cost": round(cr.resent_cost, 8),
        "total_llm_input_tokens": cr.total_llm_input_tokens,
        "total_llm_input_cost": round(cr.total_llm_input_cost, 8),
        "resent_tokens_ratio": round(ratio_tokens, 6),
        "resent_cost_ratio": round(ratio_cost, 6),
        "cost_accuracy_flag": cr.cost_accuracy_flag,
        "n_events": len(cr.resent_events),
        "events": [
            {
                "llm_span_id": ev.llm_span_id,
                "origin_llm_span_id": ev.origin_llm_span_id,
                "chunk_hash": ev.chunk_hash,
                "chunk_role": ev.chunk_role,
                "resent_input_tokens": ev.resent_input_tokens,
                "resent_cost": round(ev.resent_cost, 8),
            }
            for ev in cr.resent_events
        ],
    }


def render_json(
    trace: Trace,
    cr: CascadeResult,
    details: list[WasteDetail],
    *,
    no_snippets: bool = False,
    snippet_len: int = _SNIPPET_LEN,
    amplification: AmplificationEstimate | None = None,
    user_tools: "ResolvedTools | None" = None,
    context_resend: ContextResendResult | None = None,
) -> str:
    """CascadeResult + WasteDetail list -> JSON string (indent=2).

    Snippet: output_text[:snippet_len] by default (excludes the key entirely if no_snippets=True).
    Includes frozen parameters (phi, N, model) at the report header.

    `user_tools` (optional): ResolvedTools from clew.yaml. When None,
    output is bit-identical to pre-clew.yaml releases (§3 gate).

    `context_resend` (optional): result from clew.detect.context_resend.
    When None or when the result carries no events, the "context_resend"
    JSON block is omitted entirely (pre-Context-Resend-prereg output shape
    preserved).
    """
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    enrichment = enrich(trace, details, user_tools)
    cov = coverage_stats(trace, enrichment.enriched, user_tools)
    id_bridge = scan_id_bridge_candidates(trace, user_tools)
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
                "source": c.source,
            }
            for c in id_bridge
        ],
        "waste_details": waste_details_list,
        "user_tools_applied": _user_tools_block(user_tools),
        "context_resend": _context_resend_block(context_resend),
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
