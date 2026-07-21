"""Semantic duplicate check (SPEC §8 2.2).

One local multilingual embedding model + determinism + cache.

- model_name + revision (commit sha) are required arguments: omitting raises TypeError immediately -> enforces frozen state.
- Cache key: sha256(model_name + revision + text). Same text under same model/revision -> same vector.
- Model loading is lazy (on first embed call). Tests monkeypatch _compute.

No label references. Neither the evaluation nor dev directory is read.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path


def _cache_key(model_name: str, revision: str, text: str) -> str:
    payload = f"{model_name}|{revision}|{text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class _SqliteCache:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS embeddings (key TEXT PRIMARY KEY, vector TEXT NOT NULL)"
        )
        self._conn.commit()

    def get(self, key: str) -> list[float] | None:
        row = self._conn.execute(
            "SELECT vector FROM embeddings WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def put(self, key: str, vector: list[float]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO embeddings (key, vector) VALUES (?, ?)",
            (key, json.dumps(vector)),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


class Embedder:
    def __init__(self, model_name: str, revision: str, cache_dir: Path) -> None:
        if not model_name:
            raise ValueError("model_name required")
        if not revision:
            raise ValueError("revision required (40자 commit sha)")
        self.model_name = model_name
        self.revision = revision
        self.cache_dir = Path(cache_dir)
        self._cache = _SqliteCache(self.cache_dir / "embeddings.sqlite")
        self._model = None

    def embed(self, text: str) -> list[float]:
        key = _cache_key(self.model_name, self.revision, text)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        vector = self._compute(text)
        self._cache.put(key, vector)
        return vector

    def _compute(self, text: str) -> list[float]:
        if self._model is None:
            self._load_model()
        # normalize_embeddings=True -> fp32, l2-normalized -> determinism + cosine=dot product
        vec = self._model.encode(text, normalize_embeddings=True, convert_to_numpy=True)
        return [float(x) for x in vec.tolist()]

    def _load_model(self) -> None:
        try:
            import torch  # type: ignore[import-not-found]
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
        except ImportError as e:
            raise ImportError(
                "The semantic gate (cos >= phi) requires the [semantic] extra:\n"
                "  pip install 'clew-custos[semantic]'\n"
                "On Linux, avoid pulling the CUDA torch stack by installing CPU-only torch first:\n"
                "  pip install torch --index-url https://download.pytorch.org/whl/cpu\n"
                f"cause: {e}"
            ) from e

        torch.manual_seed(0)
        self._model = SentenceTransformer(self.model_name, revision=self.revision)
        self._model.eval()


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"vector length mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def is_semantic_duplicate(origin_text: str, candidate_text: str, embedder: Embedder, phi: float) -> bool:
    """Semantic duplicate if cosine of origin/candidate outputs >= phi."""
    return cosine(embedder.embed(origin_text), embedder.embed(candidate_text)) >= phi
