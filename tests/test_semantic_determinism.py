"""tests/test_semantic_determinism.py — embedding determinism + cache + no label access.

Real sentence-transformers models are heavy and network-dependent, so unit tests
monkeypatch Embedder._compute to a deterministic fake. Real-model determinism is
checked via reproducibility assertions when calibrate.py / evaluate.py runs.

(i)  Same text → same vector
(ii) Cache hit == cache miss result, bit-identical
(iii) Embedder instantiation + embed call does not touch label paths
"""

from __future__ import annotations

import builtins
import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from clew.detect.semantic import Embedder, _cache_key, cosine, is_semantic_duplicate


def _fake_compute(self: Embedder, text: str) -> list[float]:
    """First 16 bytes of text sha256 → normalized to 0–1 → 16-dim deterministic vector."""
    h = hashlib.sha256(text.encode("utf-8")).digest()[:16]
    return [b / 255.0 for b in h]


@pytest.fixture
def embedder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Embedder:
    monkeypatch.setattr(Embedder, "_compute", _fake_compute)
    return Embedder(model_name="fake-model", revision="fake-rev-0000", cache_dir=tmp_path)


def test_same_text_same_vector(embedder: Embedder):
    v1 = embedder.embed("hello world")
    v2 = embedder.embed("hello world")
    assert v1 == v2


def test_different_text_different_vector(embedder: Embedder):
    assert embedder.embed("hello") != embedder.embed("goodbye")


def test_cache_hit_equals_miss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """First call (runs _compute) vs second call (skips _compute) → same vector."""
    monkeypatch.setattr(Embedder, "_compute", _fake_compute)
    embedder = Embedder(model_name="m", revision="r-0000", cache_dir=tmp_path)
    miss_result = embedder.embed("payload")
    # Verify that _compute is not invoked on the second call
    call_count = {"n": 0}

    def tracking_compute(self: Embedder, text: str) -> list[float]:
        call_count["n"] += 1
        return _fake_compute(self, text)

    monkeypatch.setattr(Embedder, "_compute", tracking_compute)
    hit_result = embedder.embed("payload")
    assert hit_result == miss_result
    assert call_count["n"] == 0, "second call should hit cache, not invoke _compute"


def test_cache_key_includes_model_and_revision():
    k1 = _cache_key("model-a", "rev-1", "text")
    k2 = _cache_key("model-b", "rev-1", "text")
    k3 = _cache_key("model-a", "rev-2", "text")
    k4 = _cache_key("model-a", "rev-1", "different")
    assert len({k1, k2, k3, k4}) == 4


def test_embedder_requires_model_name_and_revision(tmp_path: Path):
    with pytest.raises(ValueError):
        Embedder(model_name="", revision="r", cache_dir=tmp_path)
    with pytest.raises(ValueError):
        Embedder(model_name="m", revision="", cache_dir=tmp_path)


def test_cosine_basics():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0  # zero-norm fallback


def test_cosine_length_mismatch_raises():
    with pytest.raises(ValueError):
        cosine([1.0], [1.0, 0.0])


def test_is_semantic_duplicate_threshold(embedder: Embedder):
    # Same text → cos=1.0 → passes any threshold
    assert is_semantic_duplicate("a", "a", embedder, phi=0.99) is True
    # Different text → cos < 1.0 → below threshold 1.0
    assert is_semantic_duplicate("a", "b", embedder, phi=1.0) is False


def test_embedder_no_label_path_access(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """No label paths are accessed during Embedder instantiation or embed."""
    monkeypatch.setattr(Embedder, "_compute", _fake_compute)
    opened: list[str] = []
    original = builtins.open

    def trace(path, *a, **kw):
        opened.append(str(path))
        return original(path, *a, **kw)

    with patch("builtins.open", trace):
        e = Embedder(model_name="m", revision="r-0000", cache_dir=tmp_path)
        e.embed("hello")

    leaks = ("eval/labels", "eval\\labels", "labels.jsonl")
    for p in opened:
        for lk in leaks:
            assert lk not in p, f"semantic opened leaked path: {p}"


def test_semantic_source_does_not_reference_labels():
    src = Path(__file__).parent.parent / "src" / "clew" / "detect" / "semantic.py"
    text = src.read_text(encoding="utf-8")
    assert "labels" not in text
    assert "eval/" not in text
