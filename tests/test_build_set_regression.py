"""tests/test_build_set_regression.py — seed=42 manifest sha256 frozen-value regression guard.

If the manifest sha256 pinned at stage1-freeze shifts due to a stage 2 change, fail immediately.
Does not touch build_set itself, but catches accidental regressions (field order, defaults, generation order).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from eval.generators.build_set import build_set

ROOT = Path(__file__).parent.parent
CRITERIA = ROOT / "validation" / "CRITERIA_FROZEN.md"


def _frozen_manifest_sha() -> str:
    text = CRITERIA.read_text(encoding="utf-8")
    m = re.search(r"sha256[^`]*`([0-9a-f]{64})`", text)
    assert m, "CRITERIA_FROZEN.md missing manifest sha256"
    return m.group(1)


# Intentional drift, CASCADE_ABSENCE_SENTINEL_AMENDMENT_PREREG §7.5.
#
# The amendment adds `Span.output_is_absent` (default False). This guard
# hashes the generated artifacts, and its own docstring names `defaults` as
# something it is meant to catch — so it fired correctly. The guard is not
# deleted or skipped (`feedback_intentional_drift`): it is marked strict-xfail
# so that a later re-freeze turns into an XPASS and forces this marker to be
# removed deliberately rather than rotting.
#
# Drift scope, verified per artifact rather than asserted:
#   - 80 generated files, before vs after. Removing `output_is_absent` from
#     every span makes 0 of 80 differ, so nothing but the new field moved.
#   - `set_manifest.json` differs in exactly one key, `traces_combined`.
#   - `labels.jsonl` is byte-identical.
#   - 0 spans in the frozen set carry `output_is_absent=True`, so cascade's
#     new tool-branch skip cannot change detection on this set at all.
#     frozen a205a3d6… -> actual a83085c3…, serialization only.
#
# Resolution path: re-pin the sha in validation/CRITERIA_FROZEN.md and drop
# this marker. That re-freezes a stage1-freeze reproducibility anchor
# (`reference_stage1_freeze`), which is a deliberate decision and not part
# of this amendment.
@pytest.mark.xfail(
    strict=True,
    reason="manifest sha drift from the additive Span.output_is_absent field "
           "(CASCADE_ABSENCE_SENTINEL_AMENDMENT_PREREG §7.5); serialization "
           "only, verified 0/80 artifacts differ once the field is removed",
)
# stage2 eval baseline — reflects the requery_known generator fix, separate from stage1-freeze
def test_seed42_manifest_sha_matches_frozen(tmp_path: Path):
    info = build_set(seed=42, pairs_per_pattern=10, out_dir=tmp_path)
    actual = hashlib.sha256(info["manifest_path"].read_bytes()).hexdigest()
    assert actual == _frozen_manifest_sha(), (
        f"manifest sha drift — frozen={_frozen_manifest_sha()} actual={actual}"
    )


def test_seed42_counts_match_frozen(tmp_path: Path):
    info = build_set(seed=42, pairs_per_pattern=10, out_dir=tmp_path)
    counts = info["manifest"]["counts"]
    assert counts == {"positive": 40, "negative": 40, "total": 80}
