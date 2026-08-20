"""src/clew/report/_model.py - report-internal data model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from clew.cost.pricing import get_pricing
from clew.model import Span, Trace

if TYPE_CHECKING:
    from clew.detect.cascade import CascadeResult
    from clew.detect.context_resend import ContextResendResult
    from clew.detect.llm_judge import LLMJudgeResult
    from clew.detect.redundant_read import RedundantReadResult


CostAccuracy = Literal["accurate", "estimated"]


@dataclass
class TraceCostSummary:
    """Report-top aggregate cost view (Cost Attribution Completion prereg §5).

    Populated by report renderers from CascadeResult + ContextResendResult
    (and future detectors) plus trace.metadata["llm_calls"]. Backward compat:
    old renderers that ignore this field continue to work unchanged.
    """
    total_llm_input_cost: float = 0.0
    total_llm_output_cost: float = 0.0
    total_tool_cost: float = 0.0
    total_analyzed_cost: float = 0.0
    total_waste_cost: float = 0.0
    waste_ratio: float = 0.0
    accuracy_flag: CostAccuracy = "estimated"
    # Per-detector waste breakdown for the report's "Breakdown by detector"
    # line. Detector keys are stable identifiers used in the report template
    # (e.g., "provable_duplicate", "context_resend", "redundant_read").
    detector_breakdown: dict[str, float] = field(default_factory=dict)


@dataclass
class WasteDetail:
    """A single waste span pair.

    origin   : first-occurrence span (a legitimate single run - not waste).
    candidate: re-occurrence span (waste - target of token_count/cost_rate aggregation).
    cosine   : cosine similarity between the two output_texts.

    Cost calculation rule: sum only on the candidate side. Origin is excluded as a legitimate first execution.
    """

    origin: Span
    candidate: Span
    cosine: float

    @property
    def waste_tokens(self) -> int | None:
        return self.candidate.token_count

    @property
    def waste_cost(self) -> float | None:
        tc = self.candidate.token_count
        cr = self.candidate.cost_rate
        if tc is None or cr is None:
            return None
        return tc * cr


def _llm_call_input_cost(call: dict[str, Any]) -> tuple[float, bool]:
    """Return (input-side cost for this call in USD, was_accurate).

    was_accurate is True when tier-split fields or explicit input_cost_rate
    were used; False when we fell back to legacy or default pricing.
    """
    uncached = call.get("input_tokens_uncached")
    cache_read = call.get("input_tokens_cache_read")
    cache_write = call.get("input_tokens_cache_write")
    model = call.get("model")

    if uncached is not None or cache_read is not None or cache_write is not None:
        pricing = get_pricing(model) if model else get_pricing(None)
        u = int(uncached or 0)
        r = int(cache_read or 0)
        w = int(cache_write or 0)
        cost = (
            u * pricing.base_input_per_mtok
            + r * pricing.cache_read_per_mtok
            + w * pricing.cache_write_5m_per_mtok
        ) / 1_000_000.0
        return cost, True

    input_tokens = int(call.get("input_tokens") or 0)
    input_cost_rate = call.get("input_cost_rate")
    if input_cost_rate is not None:
        return input_tokens * float(input_cost_rate), True

    legacy = call.get("cost_rate_legacy")
    if legacy is not None:
        return input_tokens * float(legacy), False

    if model:
        pricing = get_pricing(model)
        return input_tokens * pricing.base_input_per_mtok / 1_000_000.0, False

    return 0.0, False


def _llm_call_output_cost(call: dict[str, Any]) -> float:
    """Return output-side cost for this call in USD (uses pricing.py by model)."""
    output_tokens = int(call.get("output_tokens") or 0)
    output_cost_rate = call.get("output_cost_rate")
    if output_cost_rate is not None:
        return output_tokens * float(output_cost_rate)
    model = call.get("model")
    if model:
        pricing = get_pricing(model)
        return output_tokens * pricing.output_per_mtok / 1_000_000.0
    return 0.0


def build_cost_summary(
    trace: Trace,
    cascade_result: "CascadeResult | None",
    context_resend: "ContextResendResult | None",
    redundant_read: "RedundantReadResult | None" = None,
    llm_judge: "LLMJudgeResult | None" = None,
) -> TraceCostSummary:
    """Assemble the report-top cost summary from detector results (prereg §5).

    - `total_llm_input_cost` sums per-call input costs (tier-aware when
      available) across `trace.metadata["llm_calls"]`.
    - `total_llm_output_cost` sums per-call output costs.
    - `total_tool_cost` is 0.0 in v1 (tool spans have no per-call pricing
      hooked to pricing.py). Placeholder for future work.
    - `total_analyzed_cost` = sum of the three above.
    - `total_waste_cost` = cascade waste_cost + context_resend resent_cost
      (both are dollar-denominated already). Redundant read placeholder
      when that detector lands.
    - `waste_ratio` = waste / analyzed when analyzed > 0.
    - `accuracy_flag` = "accurate" iff every LLM call had tier-split OR
      explicit input_cost_rate. Otherwise "estimated".
    """
    llm_calls = list(trace.metadata.get("llm_calls") or [])

    total_input_cost = 0.0
    total_output_cost = 0.0
    # prereg 5.1: "accurate" iff every LLM call had tier-split tokens. With
    # zero LLM calls that universal is vacuously true, so start True.
    # bool(llm_calls) made a tool-only trace report "estimated" while having
    # nothing to be inaccurate about, contradicting this function's own
    # docstring. Downgrades below still apply.
    all_accurate = True

    for call in llm_calls:
        in_cost, accurate = _llm_call_input_cost(call)
        total_input_cost += in_cost
        total_output_cost += _llm_call_output_cost(call)
        if not accurate:
            all_accurate = False

    breakdown: dict[str, float] = {}
    total_waste = 0.0
    if cascade_result is not None:
        breakdown["provable_duplicate"] = float(cascade_result.waste_cost)
        total_waste += float(cascade_result.waste_cost)
    if context_resend is not None:
        breakdown["context_resend"] = float(context_resend.resent_cost)
        total_waste += float(context_resend.resent_cost)
    if redundant_read is not None:
        breakdown["redundant_read"] = float(redundant_read.total_waste_cost)
        total_waste += float(redundant_read.total_waste_cost)
        if redundant_read.cost_accuracy_flag == "estimated":
            all_accurate = False
    if llm_judge is not None and llm_judge.matches:
        # LLM-judge Semantic Duplicate prereg §7: contributes to breakdown
        # AND downgrades accuracy_flag to "estimated" (LLM verdicts are
        # non-reproducible even at temperature=0).
        breakdown["semantic_duplicate"] = float(llm_judge.total_semantic_resent_cost)
        total_waste += float(llm_judge.total_semantic_resent_cost)
        all_accurate = False

    total_analyzed = total_input_cost + total_output_cost  # tool cost is 0 in v1
    waste_ratio = (total_waste / total_analyzed) if total_analyzed > 0 else 0.0

    return TraceCostSummary(
        total_llm_input_cost=total_input_cost,
        total_llm_output_cost=total_output_cost,
        total_tool_cost=0.0,
        total_analyzed_cost=total_analyzed,
        total_waste_cost=total_waste,
        waste_ratio=waste_ratio,
        accuracy_flag="accurate" if all_accurate else "estimated",
        detector_breakdown=breakdown,
    )
