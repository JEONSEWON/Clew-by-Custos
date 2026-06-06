"""tests/test_build_set.py — paired 라벨셋 빌더 검증."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.generators.build_set import build_set
from eval.generators.patterns import PATTERNS


@pytest.fixture
def small_set(tmp_path):
    return build_set(seed=42, pairs_per_pattern=2, out_dir=tmp_path)


def test_counts_match_pattern_distribution(small_set):
    m = small_set["manifest"]
    # 4 패턴 × 2 쌍 = 8 positive + 8 negative
    assert m["counts"]["positive"] == 8
    assert m["counts"]["negative"] == 8
    assert m["counts"]["total"] == 16
    assert sum(m["pattern_distribution"].values()) == 8
    for p in PATTERNS:
        assert m["pattern_distribution"][p] == 2


def test_trace_files_written(tmp_path, small_set):
    files = sorted((tmp_path / "traces").glob("*.json"))
    assert len(files) == 16
    # 파일명 = trace_id.json
    names = {f.stem for f in files}
    expected = {f"t-{i:04d}" for i in range(1, 17)}
    assert names == expected


def test_labels_match_traces(tmp_path, small_set):
    labels_path = tmp_path / "labels.jsonl"
    lines = [json.loads(l) for l in labels_path.read_text(encoding="utf-8").splitlines() if l]
    assert len(lines) == 16
    label_tids = {l["trace_id"] for l in lines}
    file_tids = {f.stem for f in (tmp_path / "traces").glob("*.json")}
    assert label_tids == file_tids


def test_label_record_shape(small_set, tmp_path):
    lines = [
        json.loads(l)
        for l in (tmp_path / "labels.jsonl").read_text(encoding="utf-8").splitlines()
        if l
    ]
    for rec in lines:
        assert set(rec.keys()) == {"trace_id", "class", "pattern", "waste_span_ids"}
        assert rec["class"] in ("positive", "negative")
        if rec["class"] == "negative":
            assert rec["pattern"] is None
            assert rec["waste_span_ids"] == []
        else:
            assert rec["pattern"] in PATTERNS
            assert len(rec["waste_span_ids"]) > 0


def test_pairs_have_matching_length(small_set):
    for pair in small_set["manifest"]["pairs"]:
        assert "positive_trace_id" in pair
        assert "negative_trace_id" in pair
        assert pair["pattern"] in PATTERNS
        assert pair["length"] > 0


def test_determinism_same_seed(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    info_a = build_set(seed=42, pairs_per_pattern=2, out_dir=a)
    info_b = build_set(seed=42, pairs_per_pattern=2, out_dir=b)
    # manifest sha256 동일
    assert info_a["manifest_sha256"] == info_b["manifest_sha256"]
    # labels.jsonl 바이트 단위 동일
    assert (a / "labels.jsonl").read_bytes() == (b / "labels.jsonl").read_bytes()
    # 모든 트레이스 파일 바이트 단위 동일
    files_a = sorted(p.name for p in (a / "traces").glob("*.json"))
    files_b = sorted(p.name for p in (b / "traces").glob("*.json"))
    assert files_a == files_b
    for name in files_a:
        assert (a / "traces" / name).read_bytes() == (b / "traces" / name).read_bytes()


def test_determinism_different_seeds_differ(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    info_a = build_set(seed=42, pairs_per_pattern=2, out_dir=a)
    info_b = build_set(seed=99, pairs_per_pattern=2, out_dir=b)
    assert info_a["manifest_sha256"] != info_b["manifest_sha256"]


def test_full_run_seed_42_pairs_10(tmp_path):
    """플랜 §3.2 — 운영 규모 (4 패턴 × 10쌍 = positive 40 + negative 40)."""
    info = build_set(seed=42, pairs_per_pattern=10, out_dir=tmp_path)
    m = info["manifest"]
    assert m["counts"] == {"positive": 40, "negative": 40, "total": 80}
    assert all(m["pattern_distribution"][p] == 10 for p in PATTERNS)
    files = list((tmp_path / "traces").glob("*.json"))
    assert len(files) == 80
