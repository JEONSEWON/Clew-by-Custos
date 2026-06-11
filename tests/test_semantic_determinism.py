"""tests/test_semantic_determinism.py — 임베딩 결정론 + 캐시 + 라벨 미접근.

실제 sentence-transformers 모델은 무겁고 네트워크 의존이라 단위 테스트는
Embedder._compute 를 결정론 fake 로 monkeypatch 한다. 실제 모델 결정론은
calibrate.py / evaluate.py 실행 시 재현 단언으로 확인.

(i)  같은 텍스트 → 같은 벡터
(ii) 캐시 hit == 캐시 miss 결과 비트 동일
(iii) Embedder 인스턴스화 + embed 호출 시 라벨 경로 미접근
"""

from __future__ import annotations

import builtins
import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from clew.detect.semantic import Embedder, _cache_key, cosine, is_semantic_duplicate


def _fake_compute(self: Embedder, text: str) -> list[float]:
    """텍스트 sha256의 앞 16바이트 → 0~1 정규화 → 16차원 결정론 벡터."""
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
    """첫 호출(_compute 실행) vs 둘째 호출(_compute 미실행) → 동일 벡터."""
    monkeypatch.setattr(Embedder, "_compute", _fake_compute)
    embedder = Embedder(model_name="m", revision="r-0000", cache_dir=tmp_path)
    miss_result = embedder.embed("payload")
    # 두 번째 호출 시 _compute 가 호출되지 않음을 검증
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
    # 같은 텍스트 → cos=1.0 → 어느 임계든 통과
    assert is_semantic_duplicate("a", "a", embedder, phi=0.99) is True
    # 서로 다른 텍스트 → cos < 1.0 → 임계 1.0 미달
    assert is_semantic_duplicate("a", "b", embedder, phi=1.0) is False


def test_embedder_no_label_path_access(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Embedder 인스턴스화·embed 중 라벨 경로 미접근."""
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
