"""ChromaDB vector store wrapper.

Design: one Chroma collection per workspace. This gives strong tenant
isolation, makes deletion a single ``delete_collection`` call, and lets
the per-workspace collection stay small enough for low-latency retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from loguru import logger

from backend.core.config import get_settings
from backend.services.embeddings import EmbeddingService


@dataclass
class RetrievedChunk:
    text: str
    start: float
    end: float
    score: Optional[float]  # distance (lower = closer); None when not available


class VectorStoreService:
    def __init__(self, embedding_service: EmbeddingService) -> None:
        settings = get_settings()
        settings.chroma_persist_dir.mkdir(parents=True, exist_ok=True)
        # PersistentClient survives restarts; settings stored alongside.
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        self._client = chromadb.PersistentClient(
            path=str(settings.chroma_persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=False),
        )
        self._embedding_service = embedding_service

    # ---- collection lifecycle ----

    def _collection_name(self, workspace_id: str) -> str:
        # Chroma collection names must match [a-zA-Z0-9_-]{3,63}.
        safe = "".join(c for c in workspace_id if c.isalnum() or c in ("_", "-"))
        return f"ws_{safe}"

    def get_or_create_collection(self, workspace_id: str):
        return self._client.get_or_create_collection(
            name=self._collection_name(workspace_id),
            metadata={"hnsw:space": "cosine"},
        )

    def delete_collection(self, workspace_id: str) -> None:
        name = self._collection_name(workspace_id)
        try:
            self._client.delete_collection(name)
        except Exception as e:  # collection may not exist
            logger.warning(f"Chroma delete_collection({name}) failed: {e}")

    def collection_exists(self, workspace_id: str) -> bool:
        try:
            self._client.get_collection(self._collection_name(workspace_id))
            return True
        except Exception:
            return False

    # ---- data operations ----

    def add_chunks(
        self,
        workspace_id: str,
        chunks: list[str],
        metadatas: list[dict],
        ids: list[str],
    ) -> None:
        if not chunks:
            return
        embeddings = self._embedding_service.embed_documents(chunks)
        coll = self.get_or_create_collection(workspace_id)
        coll.add(documents=chunks, embeddings=embeddings, metadatas=metadatas, ids=ids)

    def query(
        self,
        workspace_id: str,
        query_text: str,
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        if not self.collection_exists(workspace_id):
            return []
        coll = self.get_or_create_collection(workspace_id)
        query_embedding = self._embedding_service.embed_query(query_text)
        res = coll.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
        )
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        out: list[RetrievedChunk] = []
        for i, doc in enumerate(docs):
            meta = metas[i] if i < len(metas) else {}
            dist = dists[i] if i < len(dists) else None
            start = float(meta.get("start", 0.0))
            end = float(meta.get("end", start))
            out.append(RetrievedChunk(text=doc, start=start, end=end, score=dist))
        return out
