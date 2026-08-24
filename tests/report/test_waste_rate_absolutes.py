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
