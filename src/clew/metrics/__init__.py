"""Session-level waste-rate metrics (spec: docs/WASTE_RATE_METRIC_PREREG.md)."""

from clew.metrics.waste_rate import (
    DETECTOR_ORDER,
    SDR_THRESHOLD,
    PerDetectorMetric,
    WasteRateMetric,
    compute_waste_rate,
)

__all__ = [
    "DETECTOR_ORDER",
    "SDR_THRESHOLD",
    "PerDetectorMetric",
    "WasteRateMetric",
    "compute_waste_rate",
]
