"""Embeddings service: lazy singleton wrapper around sentence-transformers.

Why local embeddings? They're free, fast, deterministic, and avoid a
second external API dependency. The model is loaded once at first use
and cached in-process.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from loguru import logger


class EmbeddingService:
    """Thin wrapper that exposes ``embed_documents`` and ``embed_query``."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading embedding model: {self.model_name}")
            # device='cpu' for portability; GPU auto-detected would be 'cuda' if available.
            self._model = SentenceTransformer(self.model_name, device="cpu")
            logger.info("Embedding model loaded.")
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        # normalize_embeddings=True pairs well with cosine similarity used by Chroma
        vectors = model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
            batch_size=32,
        )
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        model = self._load()
        vec = model.encode(
            [text],
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vec[0].tolist()

    @property
    def dimension(self) -> int:
        # all-MiniLM-L6-v2 produces 384-dim vectors
        model = self._load()
        return int(model.get_sentence_embedding_dimension())


@lru_cache(maxsize=1)
def get_embedding_service(model_name: str) -> EmbeddingService:
    return EmbeddingService(model_name=model_name)
