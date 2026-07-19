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
