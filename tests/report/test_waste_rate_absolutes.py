"""tests/report/test_waste_rate_absolutes.py — waste_rate block carries absolutes.

Storage-layer consumers aggregate many traces. Ratios cannot be aggregated (the
mean of per-trace ratios is not the ratio of the sums), and `union_wr_cost` was
not reversible because its denominator never left the block. Locks the presence
of numerator and denominator for both union ratios, and that they reproduce the
ratios the block already published.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from clew.detect.cascade import CascadeResult
from clew.metrics.waste_rate import DETECTOR_ORDER, PerDetectorMetric, WasteRateMetric
from clew.model import Span, Trace
from clew.report.json_report import render_json


def _metric(
    *,
    total_bytes: int = 1_000_000,
    total_cost: float = 2.5,
    union_bytes: int = 659_536,
    union_cost: float = 1.66524903,
) -> WasteRateMetric:
    return WasteRateMetric(
        trace_id="t1",
        total_input_bytes=total_bytes,
        total_input_cost=total_cost,
        per_detector={
            d: PerDetectorMetric(
                detector=d, waste_bytes=0, waste_cost=0.0, wr_char=0.0, wr_cost=0.0,
            )
            for d in DETECTOR_ORDER
        },
        union_waste_bytes=union_bytes,
        union_waste_cost=union_cost,
        union_wr_char=union_bytes / total_bytes,
        union_wr_cost=union_cost / total_cost,
    )


def _block(metric: WasteRateMetric) -> dict:
    root = Span(
        trace_id="t1",
        span_id="root",
        parent_span_id=None,
        agent_or_node_id="root",
        span_kind="chain",
        start_time=datetime(2026, 8, 24, tzinfo=timezone.utc),
        end_time=datetime(2026, 8, 24, tzinfo=timezone.utc),
        input_text="",
        output_text="[x]",
    )
    trace = Trace(trace_id="t1", spans=[root])
    cr = CascadeResult(trace_id="t1", wasteful=False)
    js = json.loads(render_json(trace, cr, details=[], waste_rate=metric))
    return js["waste_rate"]


def test_block_carries_both_numerators_and_both_denominators() -> None:
    wr = _block(_metric())

    assert wr["total_input_bytes"] == 1_000_000
    assert wr["total_input_cost"] == 2.5
    assert wr["union_waste_bytes"] == 659_536
    assert wr["union_waste_cost"] == 1.66524903


def test_absolutes_reproduce_the_published_ratios() -> None:
    wr = _block(_metric())

    assert wr["union_waste_bytes"] / wr["total_input_bytes"] == wr["union_wr_char"]
    assert round(wr["union_waste_cost"] / wr["total_input_cost"], 6) == wr["union_wr_cost"]


def test_cost_absolutes_keep_eight_digits() -> None:
    # Ratios round to 6 digits; costs elsewhere in the report carry 8. A cost
    # rounded to 6 loses the tail on sub-cent traces.
    wr = _block(_metric(union_cost=0.00000123, total_cost=0.00000456))

    assert wr["union_waste_cost"] == 0.00000123
    assert wr["total_input_cost"] == 0.00000456


# ── per-detector absolute cost: PER_DETECTOR_WASTE_COST_AMENDMENT_PREREG ────
#
# `waste_cost` was computed by the metric and dropped by the serializer. The
# drop propagated: the storage layer builds its rows from
# `cost_summary.detector_breakdown`, which has no arm for `duplicate_creation`,
# so that detector could not be stored and a dashboard could not show it.

def _metric_with_costs(costs: dict[str, float]) -> WasteRateMetric:
    """A metric whose per-detector costs are whatever the test needs."""
    m = _metric()
    m.per_detector = {
        d: PerDetectorMetric(
            detector=d,
            waste_bytes=0,
            waste_cost=costs.get(d, 0.0),
            wr_char=0.0,
            wr_cost=0.0,
        )
        for d in DETECTOR_ORDER
    }
    return m


def test_every_detector_carries_an_absolute_cost() -> None:  # P1
    """P1. Including `duplicate_creation`, which is the one the storage layer
    could never write a row for."""
    per = _block(_metric())["per_detector"]

    assert set(per) == set(DETECTOR_ORDER)
    for detector, values in per.items():
        assert "waste_cost" in values, f"{detector} has no absolute cost"


def test_the_cost_is_read_from_the_metric_not_recomputed() -> None:  # P2
    """P2. A recomputed cost is a second answer to a question already
    answered. Distinct values per detector, so a serializer that derived them
    from anything else — bytes, the ratio, the union — would disagree."""
    costs = {
        "repeat": 1.25,
        "context_resend": 0.00057018,
        "redundant_read": 12.5,
        "duplicate_creation": 0.5,
    }
    per = _block(_metric_with_costs(costs))["per_detector"]

    for detector, expected in costs.items():
        assert per[detector]["waste_cost"] == expected, detector


def test_a_zero_cost_is_a_float_not_an_int() -> None:
    """`round(0, 8)` returns the int `0`, which would make a zero-waste
    detector serialize as `0` while a non-zero one serializes as a float. A
    consumer type-checking the field would read the two differently."""
    per = _block(_metric_with_costs({"context_resend": 3.0}))["per_detector"]

    assert isinstance(per["repeat"]["waste_cost"], float)
    assert isinstance(per["context_resend"]["waste_cost"], float)


def test_the_cost_keeps_eight_digits() -> None:
    """Same rounding as `union_waste_cost` beside it, which is the same kind of
    quantity. `_wr_round` is for ratios in [0, 1] and would flatten this."""
    per = _block(_metric_with_costs({"context_resend": 1.234567891}))["per_detector"]

    assert per["context_resend"]["waste_cost"] == 1.23456789


def test_the_three_existing_keys_are_untouched() -> None:  # P3
    """P3. An additive field that moves something else is not additive."""
    per = _block(_metric())["per_detector"]

    for detector, values in per.items():
        assert set(values) == {"wr_char", "wr_cost", "waste_bytes", "waste_cost"}, (
            f"{detector} gained or lost a key beyond the one this adds"
        )
        assert values["wr_char"] == 0.0
        assert values["wr_cost"] == 0.0
        assert values["waste_bytes"] == 0


def test_the_rest_of_the_block_is_untouched() -> None:  # P3
    """The union figures and the denominators are what storage aggregates on.
    They are read by the rollup, so a change here moves published numbers."""
    block = _block(_metric())

    assert block["total_input_bytes"] == 1_000_000
    assert block["total_input_cost"] == 2.5
    assert block["union_waste_bytes"] == 659_536
    assert block["union_waste_cost"] == 1.66524903
    assert block["excluded_reason"] is None


def test_the_breakdown_did_not_gain_the_fourth_detector() -> None:  # P3
    """Deliberately not fixed there. `cost_summary.detector_breakdown` is what
    `total_waste_cost` sums, so adding `duplicate_creation` to it would change
    a published figure rather than expose a dropped one. The amendment §3 says
    the breakdown stays four-armed and the new field is read from `waste_rate`
    instead."""
    from clew.report._model import build_cost_summary

    root = Span(
        trace_id="t1", span_id="root", parent_span_id=None,
        agent_or_node_id="root", span_kind="chain",
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        input_text="", output_text="",
    )
    trace = Trace(trace_id="t1", spans=[root])
    summary = build_cost_summary(
        trace,
        cascade_result=CascadeResult(trace_id="t1", wasteful=False,
                                     waste_span_ids=[], waste_tokens=0,
                                     waste_cost=0.0),
        context_resend=None,
    )

    assert "duplicate_creation" not in summary.detector_breakdown
