"""Tests for the transcript chunker."""

from __future__ import annotations

import pytest

from backend.core.exceptions import IngestionError
from backend.services.ingestion import chunk_transcript
from backend.services.youtube import TranscriptSegment


def _seg(text: str, start: float, dur: float = 1.0) -> TranscriptSegment:
    return TranscriptSegment(text=text, start=start, duration=dur)


def test_chunk_empty() -> None:
    assert chunk_transcript([], chunk_size=100, chunk_overlap=10) == []


def test_chunk_basic() -> None:
    segs = [_seg("hello world " * 20, 0.0)]
    chunks = chunk_transcript(segs, chunk_size=100, chunk_overlap=20)
    assert len(chunks) >= 1
    assert all(c.text for c in chunks)
    assert chunks[0].start == 0.0


def test_chunk_multiple_segments_preserves_timestamps() -> None:
    segs = [
        _seg("alpha " * 5, 0.0),
        _seg("beta " * 5, 5.0),
        _seg("gamma " * 5, 10.0),
    ]
    chunks = chunk_transcript(segs, chunk_size=30, chunk_overlap=5)
    # Each chunk should have a non-decreasing start time
    starts = [c.start for c in chunks]
    assert starts == sorted(starts)
    # Should be more than one chunk given small window
    assert len(chunks) >= 2


def test_chunk_overlap_too_large_raises() -> None:
    segs = [_seg("x", 0.0)]
    with pytest.raises(IngestionError):
        chunk_transcript(segs, chunk_size=10, chunk_overlap=10)
