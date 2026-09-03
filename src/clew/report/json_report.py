"""src/clew/report/json_report.py - machine-oriented JSON report renderer."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from clew.cost.amplification import AmplificationEstimate
from clew.detect.cascade import CascadeResult
from clew.detect.context_resend import ContextResendResult
from clew.detect.llm_judge import LLMJudgeResult
from clew.detect.redundant_read import RedundantReadResult
from clew.metrics.waste_rate import DETECTOR_ORDER, WasteRateMetric
from clew.model import Trace
from clew.report._enrich import coverage_stats, enrich, scan_id_bridge_candidates
from clew.report._model import WasteDetail, build_cost_summary

if TYPE_CHECKING:
    from clew.detect.llm_judge.verification_axis import VerificationAxisResult
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


def _llm_judge_block(rr: LLMJudgeResult | None) -> dict | None:
    """LLM-as-judge Semantic Duplicate block (prereg §7).

    None when detector wasn't enabled or produced zero matches. When
    the detector was enabled but returned zero matches, we still emit
    the block (n_matches=0) so machine consumers can distinguish
    "not run" from "ran, found nothing".
    """
    if rr is None:
        return None
    if not rr.enabled and not rr.matches:
        return None
    return {
        "enabled": rr.enabled,
        "n_matches": len(rr.matches),
        "total_judge_calls": rr.total_judge_calls,
        "total_judge_cost": round(rr.total_judge_cost, 8),
        "total_semantic_resent_tokens": rr.total_semantic_resent_tokens,
        "total_semantic_resent_cost": round(rr.total_semantic_resent_cost, 8),
        "matches": [
            {
                "kind": m.kind,
                "chunk_a_hash": m.chunk_a_hash,
                "chunk_b_hash": m.chunk_b_hash,
                "origin_llm_span_id": m.origin_llm_span_id,
                "candidate_llm_span_id": m.candidate_llm_span_id,
                "equivalent": m.equivalent,
                "confidence": round(m.confidence, 4),
                "reasoning": m.reasoning,
                "judge_model": m.judge_model,
                "judge_cost": round(m.judge_cost, 8),
            }
            for m in rr.matches
        ],
    }


def _redundant_read_block(rr: RedundantReadResult | None) -> dict | None:
    """Redundant Read Detector JSON block (prereg §6).

    None when detector wasn't run or produced zero events. Backward compat:
    old consumers see no new keys unless meaningful data present.
    """
    if rr is None or not rr.events:
        return None
    return {
        "n_events": len(rr.events),
        "total_waste_tokens": rr.total_waste_tokens,
        "total_waste_cost": round(rr.total_waste_cost, 8),
        "cost_accuracy_flag": rr.cost_accuracy_flag,
        "events": [
            {
                "read_span_id": e.read_span_id,
                "origin_read_span_id": e.origin_read_span_id,
                "tool_name": e.tool_name,
                "target": e.target,
                "waste_tokens": e.waste_tokens,
                "waste_cost": round(e.waste_cost, 8),
                "confirmed": e.confirmed,
            }
            for e in rr.events
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


def _wr_round(v: float | None, digits: int = 6) -> float | None:
    return None if v is None else round(v, digits)


def _waste_rate_block(wr: WasteRateMetric | None) -> dict | None:
    """WASTE_RATE_METRIC_PREREG §6.1 JSON field."""
    if wr is None:
        return None
    return {
        "excluded_reason": wr.excluded_reason,
        "total_input_bytes": wr.total_input_bytes,
        # Numerator and denominator of both union ratios, emitted alongside the
        # ratios themselves. A consumer aggregating many traces cannot use the
        # ratios: the mean of per-trace ratios is not the ratio of the sums, and
        # `union_wr_cost` could not be un-divided here because its denominator
        # (`total_input_cost`) was not in the block.
        # `cost_summary.total_waste_cost` is not a substitute for
        # `union_waste_cost`: that one sums the detector breakdown, this one is a
        # span-level union with a DETECTOR_ORDER tie-break plus context_resend's
        # chunk cost (metrics/waste_rate.py). Different provenance, so a
        # consumer must not read one for the other even when they coincide.
        "total_input_cost": round(wr.total_input_cost, 8),
        "union_waste_bytes": wr.union_waste_bytes,
        "union_waste_cost": round(wr.union_waste_cost, 8),
        "union_wr_char": _wr_round(wr.union_wr_char),
        "union_wr_cost": _wr_round(wr.union_wr_cost),
        # `waste_cost` is here because it was computed and then dropped, and
        # the drop propagated: the storage layer builds its per-detector rows
        # from `cost_summary.detector_breakdown`, which has no arm for
        # `duplicate_creation`, so that detector could not be stored and a
        # dashboard could not show it (PER_DETECTOR_WASTE_COST_AMENDMENT_PREREG
        # §0). Read from the metric, never recomputed -- a second computation
        # would be a second answer to a question already answered.
        #
        # ★ It buys no larger number. Tool-side cost is structurally zero on
        # Claude Code traces (tool spans carry no token count and no rate), so
        # every one of these is 0.0 on that corpus -- measured 0.0 on 15 of 15,
        # for `repeat` and `redundant_read` as well. What it buys is that a
        # measured zero stops being indistinguishable from nothing stored.
        #
        # Rounded to 8 places like `union_waste_cost` above -- the same kind of
        # quantity -- rather than with `_wr_round`, which exists for ratios in
        # [0, 1].
        #
        # `float()` first, so the type is stable. `round(0, 8)` returns the int
        # `0`, and a zero-waste detector would serialize as `0` while a
        # non-zero one serializes as a float.
        #
        # ★ 2026-09-03: the source of that int was found and fixed at the
        # metric (`sum(..., 0.0)` on an empty per-span dict returned the int
        # `0`), so `PerDetectorMetric.waste_cost` now matches its `float`
        # annotation. This `float()` is kept as the boundary belt: it is the
        # only place that decides what goes on the wire, and a future change
        # reintroducing an int upstream would otherwise change these bytes
        # silently.
        #
        # 🔴 An earlier note here said `union_waste_cost` has "that same
        # wobble". It does not, and never did: `span_cost` is seeded `0.0`
        # (metrics/waste_rate.py), so the sum is a float on every path.
        # Measured 2026-09-03 -- `0.0`, type float, on a zero-waste trace.
        "per_detector": {
            d: {"wr_char": _wr_round(wr.per_detector[d].wr_char),
                "wr_cost": _wr_round(wr.per_detector[d].wr_cost),
                "waste_bytes": wr.per_detector[d].waste_bytes,
                "waste_cost": round(float(wr.per_detector[d].waste_cost), 8)}
            for d in DETECTOR_ORDER
        },
    }


def _verification_block(vr: "VerificationAxisResult | None") -> dict:
    """The three outcomes, kept apart in the machine-readable form too.

    `finding` and `not_judged_reason` are separate keys rather than one status
    string, so a consumer cannot accidentally read "could not tell" as "no".
    That collapse is what the killed rule did, at precision 0.3250.
    """
    if vr is None or not vr.enabled:
        return {"enabled": False}
    return {
        "enabled": True,
        "judged": vr.judged,
        "finding": vr.finding if vr.judged else None,
        "not_judged_reason": vr.not_judged_reason,
        "evidence": vr.evidence or None,
        "confidence": round(vr.confidence, 4) if vr.judged else None,
        "judge_calls": vr.calls,
        "judge_cost_usd": round(vr.cost_usd, 8),
        "note": (
            "LLM judgement, non-reproducible even at temperature=0. "
            "Enters no cost figure and no waste rate."
        ),
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
    redundant_read: RedundantReadResult | None = None,
    llm_judge: LLMJudgeResult | None = None,
    waste_rate: WasteRateMetric | None = None,
    verification: "VerificationAxisResult | None" = None,
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
    # When the trace itself ran, as opposed to when we analyzed it. Storage
    # consumers bucket time series on this when present; without it a batch of
    # old traces analyzed today all land on today. Span.start_time is validated
    # tz-aware (model.py), and Trace requires >= 1 span, so min() is safe.
    trace_started = (
        min(s.start_time for s in trace.spans)
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    enrichment = enrich(trace, details, user_tools)
    cov = coverage_stats(trace, enrichment.enriched, user_tools)
    id_bridge = scan_id_bridge_candidates(trace, user_tools)
    # Cost Attribution Completion prereg §5.3 — top-level cost_summary block.
    cost_summary = build_cost_summary(
        trace, cr, context_resend, redundant_read, llm_judge,
    )
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
        "trace_started": trace_started,
        "cost_summary": {
            "total_llm_input_cost": round(cost_summary.total_llm_input_cost, 8),
            "total_llm_output_cost": round(cost_summary.total_llm_output_cost, 8),
            "total_tool_cost": round(cost_summary.total_tool_cost, 8),
            "total_analyzed_cost": round(cost_summary.total_analyzed_cost, 8),
            "total_waste_cost": round(cost_summary.total_waste_cost, 8),
            "waste_ratio": round(cost_summary.waste_ratio, 6),
            "accuracy_flag": cost_summary.accuracy_flag,
            # Separate from accuracy_flag on purpose: that field answers
            # "were the token tiers complete", this one answers "was the
            # rate real". A consumer needs both and they can disagree.
            "rate_from_table": cost_summary.rate_from_table,
            "unpriced_models": list(cost_summary.unpriced_models),
            "detector_breakdown": {
                k: round(v, 8) for k, v in cost_summary.detector_breakdown.items()
            },
        },
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
        # What the adapter dropped or rewrote before any detector ran.
        # Absent when the trace file mapped cleanly, so its presence is
        # the signal. Detector-level skips live under "amplification".
        "ingest_notes": trace.metadata.get("ingest_notes") or {},
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
        "redundant_read": _redundant_read_block(redundant_read),
        "llm_judge": _llm_judge_block(llm_judge),
        "waste_rate": _waste_rate_block(waste_rate),
        "verification": _verification_block(verification),
        "note": (
            "Detection thresholds were calibrated on synthetic traces; "
            "real-trace calibration is in progress. Borderline matches "
            "(cosine near 0.51) deserve human review. Amplification cost "
            "is estimated saving potential (cache-hit lower to cache-miss upper), "
            "not measured: it assumes wasted output is re-consumed each subsequent turn. "
            "Category labels are report-only annotations; detection is unchanged. "
            "Whether an idempotent re-run is truly waste depends on user context. "
            "between_window records how the interval was classified; "
            "no state-change verdict is rendered."
        ),
    }

    return json.dumps(report, ensure_ascii=False, indent=2)
