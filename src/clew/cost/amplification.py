"""Amplification cost estimator (post-detection layer).

Given a CascadeResult + Trace, estimate the potential $ impact of each waste
span assuming the wasted tool_result content is re-consumed on every
subsequent assistant turn.

Formula per waste span:
    amp_tokens_i = waste_tokens_i * turns_after_i
    lower_i      = amp_tokens_i * cache_read_price
    upper_i      = amp_tokens_i * base_input_price

Where:
    waste_tokens_i = trace.metadata["cc_usage_pair"][sid]["next"]["cache_creation_input_tokens"]
                     (falls back to len(output_text)/1.3 if usage missing → approx flag)
    turns_after_i  = cc_total_turns - cc_turn_index[sid]

prev==next filter:
    Recon (2026-07-19) showed 94.3% of hypothesis failures are duplicate/retry
    usage where prev==next. Those events are excluded from amplification.

Range interpretation:
    lower = cache hit for every re-consumption (optimistic).
    upper = full base_input every re-consumption (pessimistic / no cache).
    Real cost lies in between; exact split not observable from Anthropic usage.
"""
from __future__ import annotations

from dataclasses import dataclass

from clew.cost.pricing import ModelPricing, get_pricing
from clew.detect.cascade import CascadeResult
from clew.model import Trace

_CHAR_PER_TOKEN = 1.3


@dataclass
class AmplificationEvent:
    span_id: str
    waste_tokens: int
    turns_after: int
    amp_tokens: int
    lower_usd: float
    upper_usd: float
    tokens_are_approx: bool


@dataclass
class AmplificationEstimate:
    lower_usd: float
    upper_usd: float
    total_amp_tokens: int
    n_events: int
    n_skipped_prev_eq_next: int
    n_skipped_no_metadata: int
    n_skipped_error: int  # §29.2 tool-error gate — is_error tool_result spans excluded
    approx_events: int
    events: list[AmplificationEvent]
    model_key: str

    @property
    def any_approx(self) -> bool:
        return self.approx_events > 0


def _prev_equals_next(prev: dict | None, nxt: dict | None) -> bool:
    if prev is None or nxt is None:
        return False
    return (
        prev.get("cache_read_input_tokens") == nxt.get("cache_read_input_tokens")
        and prev.get("cache_creation_input_tokens") == nxt.get("cache_creation_input_tokens")
    )


def _waste_tokens_from_pair(pair: dict | None) -> int | None:
    if not isinstance(pair, dict):
        return None
    nxt = pair.get("next")
    if not isinstance(nxt, dict):
        return None
    v = nxt.get("cache_creation_input_tokens")
    if isinstance(v, int) and v > 0:
        return v
    return None


def estimate_amplification(
    cr: CascadeResult,
    trace: Trace,
    *,
    model_key: str | None = None,
) -> AmplificationEstimate:
    pricing: ModelPricing = get_pricing(model_key)

    turn_index: dict[str, int] = trace.metadata.get("cc_turn_index") or {}
    usage_pair: dict[str, dict] = trace.metadata.get("cc_usage_pair") or {}
    total_turns: int = int(trace.metadata.get("cc_total_turns") or 0)
    error_ids: set[str] = set(trace.metadata.get("error_span_ids") or [])

    spans_by_id = {s.span_id: s for s in trace.spans}

    events: list[AmplificationEvent] = []
    n_skip_pne = 0
    n_skip_meta = 0
    n_skip_err = 0
    n_approx = 0
    total_amp_tokens = 0
    total_lower = 0.0
    total_upper = 0.0

    for sid in cr.waste_span_ids:
        # §29.2 tool-error gate: is_error tool_result spans are infrastructure noise,
        # not amplification. Skip with explicit count (no silent drop).
        if sid in error_ids:
            n_skip_err += 1
            continue

        pair = usage_pair.get(sid)
        if pair is None:
            n_skip_meta += 1
            continue

        if _prev_equals_next(pair.get("prev"), pair.get("next")):
            n_skip_pne += 1
            continue

        wt = _waste_tokens_from_pair(pair)
        approx = False
        if wt is None:
            s = spans_by_id.get(sid)
            if s is None or not s.output_text:
                n_skip_meta += 1
                continue
            wt = max(1, int(len(s.output_text) / _CHAR_PER_TOKEN))
            approx = True

        k = turn_index.get(sid)
        if k is None or total_turns <= 0:
            n_skip_meta += 1
            continue
        turns_after = total_turns - k
        if turns_after <= 0:
            continue

        amp = wt * turns_after
        lo = pricing.cache_read_cost(amp)
        up = pricing.base_input_cost(amp)

        events.append(AmplificationEvent(
            span_id=sid,
            waste_tokens=wt,
            turns_after=turns_after,
            amp_tokens=amp,
            lower_usd=lo,
            upper_usd=up,
            tokens_are_approx=approx,
        ))
        total_amp_tokens += amp
        total_lower += lo
        total_upper += up
        if approx:
            n_approx += 1

    return AmplificationEstimate(
        lower_usd=total_lower,
        upper_usd=total_upper,
        total_amp_tokens=total_amp_tokens,
        n_events=len(events),
        n_skipped_prev_eq_next=n_skip_pne,
        n_skipped_no_metadata=n_skip_meta,
        n_skipped_error=n_skip_err,
        approx_events=n_approx,
        events=events,
        model_key=model_key or "sonnet-4.5",
    )
