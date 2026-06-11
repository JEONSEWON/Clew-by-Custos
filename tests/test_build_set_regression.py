"""tests/test_build_set_regression.py — seed=42 manifest sha256 동결값 회귀 보호.

stage1-freeze 시점 박힌 manifest sha256가 2단계 변경으로 흔들리면 즉시 fail.
build_set 자체에는 손대지 않지만, 우발적 회귀(필드 순서·기본값·생성 순서)를 잡는다.
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


# stage2 eval baseline — requery_known 생성기 수정 반영, stage1-freeze와 별개
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
