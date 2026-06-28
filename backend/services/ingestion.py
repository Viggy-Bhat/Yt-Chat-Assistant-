"""Ingestion pipeline: transcript → chunks → embeddings → Chroma upsert.

Pure functions for chunking; the run_ingest coroutine orchestrates the
full pipeline given a workspace ID and a YouTube video ID.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.exceptions import IngestionError
from backend.db.models import Workspace, WorkspaceStatus
from backend.services import youtube
from backend.services.embeddings import get_embedding_service
from backend.services.vectorstore import VectorStoreService


@dataclass
class Chunk:
    text: str
    start: float
    end: float
    index: int


def chunk_transcript(
    segments: list[youtube.TranscriptSegment],
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[Chunk]:
    """Sliding-window chunker that preserves approximate timestamp boundaries.

    The window advances in characters; for each window we record the
    ``min(start)`` of contributing segments as the chunk start time and
    ``max(end)`` as the chunk end time.
    """
    if not segments:
        return []
    if chunk_overlap >= chunk_size:
        raise IngestionError("chunk_overlap must be smaller than chunk_size")

    chunks: list[Chunk] = []
    n = len(segments)
    i = 0
    idx = 0
    while i < n:
        text_parts: list[str] = []
        char_len = 0
        j = i
        starts: list[float] = []
        ends: list[float] = []
        # Greedily extend the window until we exceed chunk_size.
        while j < n:
            seg = segments[j]
            piece = seg.text
            # Account for a separator space if we already have text.
            added = len(piece) + (1 if text_parts else 0)
            if char_len + added > chunk_size and text_parts:
                break
            text_parts.append(piece)
            char_len += added
            starts.append(seg.start)
            ends.append(seg.end)
            j += 1

        if not text_parts:
            # Defensive: a single segment larger than chunk_size -- take it whole.
            seg = segments[i]
            text_parts = [seg.text]
            starts = [seg.start]
            ends = [seg.end]
            j = i + 1

        chunk_text = " ".join(text_parts).strip()
        if chunk_text:
            chunks.append(
                Chunk(
                    text=chunk_text,
                    start=min(starts),
                    end=max(ends),
                    index=idx,
                )
            )
            idx += 1

        if j >= n:
            break

        # Step back by overlap in *characters* (approximate) to set the next start.
        target_char = max(0, char_len - chunk_overlap)
        walked = 0
        next_i = j
        for k in range(i, j):
            walked += len(segments[k].text) + 1
            if walked >= target_char:
                next_i = k + 1
                break
        # Ensure forward progress.
        if next_i <= i:
            next_i = i + 1
        i = next_i

    return chunks


async def run_ingestion(
    db: Session,
    workspace: Workspace,
    vectorstore: VectorStoreService,
) -> Workspace:
    """Execute the full ingestion pipeline for a workspace.

    Mutates the workspace row in-place and commits at the end. The caller
    is expected to have already created the row with status='pending'.
    """
    settings = get_settings()
    workspace.status = WorkspaceStatus.INGESTING
    workspace.error = None
    db.add(workspace)
    db.commit()

    try:
        # 1. Transcript
        logger.info(f"[{workspace.id}] Fetching transcript for {workspace.video_id}")
        segments = youtube.fetch_transcript(workspace.video_id)
        logger.info(f"[{workspace.id}] Got {len(segments)} transcript segments")

        # 2. Title (best-effort; may already be set from oEmbed pre-fetch)
        if not workspace.title:
            try:
                meta = await youtube.fetch_video_metadata(workspace.video_id)
                workspace.title = meta.title or workspace.video_id
                workspace.channel = workspace.channel or meta.channel
                workspace.thumbnail = workspace.thumbnail or meta.thumbnail
                db.add(workspace)
                db.commit()
            except Exception as e:  # non-fatal -- transcript is the real source of truth
                logger.warning(f"[{workspace.id}] oEmbed metadata fetch failed: {e}")

        # 3. Chunk
        chunks = chunk_transcript(
            segments,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        logger.info(f"[{workspace.id}] Produced {len(chunks)} chunks")

        # 4. Embed + upsert (batched by chroma)
        ids = [str(uuid.uuid4()) for _ in chunks]
        texts = [c.text for c in chunks]
        metadatas = [
            {"start": c.start, "end": c.end, "chunk_index": c.index}
            for c in chunks
        ]
        vectorstore.add_chunks(workspace.id, texts, metadatas, ids)

        # 5. Finalize
        workspace.chunk_count = len(chunks)
        workspace.status = WorkspaceStatus.READY
        db.add(workspace)
        db.commit()
        logger.info(f"[{workspace.id}] Ingestion complete: {len(chunks)} chunks")
        return workspace

    except youtube.YouTubeFetchError as e:
        workspace.status = WorkspaceStatus.FAILED
        workspace.error = str(e.message)
        db.add(workspace)
        db.commit()
        logger.warning(f"[{workspace.id}] Ingestion failed: {e.message}")
        raise

    except Exception as e:
        workspace.status = WorkspaceStatus.FAILED
        workspace.error = f"Ingestion error: {e}"
        db.add(workspace)
        db.commit()
        logger.exception(f"[{workspace.id}] Ingestion error")
        raise IngestionError(str(e)) from e


# ---- module-level helpers ----

_settings = get_settings()
_embedding_service = get_embedding_service(_settings.embedding_model)
vectorstore_service = VectorStoreService(_embedding_service)
