"""의미 중복 확인 (SPEC §8 2.2).

로컬 다국어 임베딩 모델 1개 + 결정론 + 캐시.

- 모델명 + revision (commit sha) 필수 인자: 빠뜨리면 TypeError 즉시 raise → 동결 강제.
- 캐시 키: sha256(model_name + revision + text). 같은 모델/리비전에서 같은 텍스트 → 같은 벡터.
- 모델 로딩은 lazy(첫 embed 호출 시). 테스트는 _compute 를 monkeypatch.

라벨 미참조. 평가/dev 디렉터리 어느 쪽도 읽지 않는다.
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
        # normalize_embeddings=True → fp32, l2-normalized → 결정론 + 코사인=내적
        vec = self._model.encode(text, normalize_embeddings=True, convert_to_numpy=True)
        return [float(x) for x in vec.tolist()]

    def _load_model(self) -> None:
        import torch  # type: ignore[import-not-found]
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

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
    """origin·candidate 출력의 코사인 ≥ φ 이면 의미 중복."""
    return cosine(embedder.embed(origin_text), embedder.embed(candidate_text)) >= phi
