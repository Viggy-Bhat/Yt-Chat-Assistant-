"""YouTube URL parsing, metadata fetch, and transcript retrieval.

This module isolates all third-party YouTube concerns so the rest of the
app deals with clean dataclasses. It also enforces a canonical URL form
so that duplicate-detection (UNIQUE on ``youtube_url``) works correctly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import httpx
from loguru import logger
from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
)

from backend.core.exceptions import BadRequestError, YouTubeFetchError


# YouTube's 11-char video ID. We accept the common URL shapes.
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_URL_PATTERNS = [
    re.compile(r"https?://(?:www\.|m\.)?youtube\.com/watch\?v=([A-Za-z0-9_-]{11})"),
    re.compile(r"https?://youtu\.be/([A-Za-z0-9_-]{11})"),
    re.compile(r"https?://(?:www\.)?youtube\.com/embed/([A-Za-z0-9_-]{11})"),
    re.compile(r"https?://(?:www\.)?youtube\.com/shorts/([A-Za-z0-9_-]{11})"),
]


def extract_video_id(url: str) -> str:
    """Extract the 11-char YouTube video ID from a URL. Raises ``BadRequestError``."""
    if not url:
        raise BadRequestError("URL is empty")
    # Try the pattern list first (most reliable for full URLs)
    for pat in _URL_PATTERNS:
        m = pat.search(url)
        if m:
            return m.group(1)
    # Fallback: maybe someone pasted the bare 11-char ID
    if _VIDEO_ID_RE.match(url.strip()):
        return url.strip()
    raise BadRequestError(f"Could not extract a YouTube video ID from: {url}")


def canonical_url(video_id: str) -> str:
    """Build the canonical watch URL for a video ID."""
    if not _VIDEO_ID_RE.match(video_id):
        raise BadRequestError(f"Invalid video ID: {video_id}")
    return f"https://www.youtube.com/watch?v={video_id}"


@dataclass
class VideoMetadata:
    title: str
    channel: Optional[str]
    thumbnail: Optional[str]


@dataclass
class TranscriptSegment:
    text: str
    start: float
    duration: float

    @property
    def end(self) -> float:
        return self.start + self.duration


async def fetch_video_metadata(video_id: str, *, timeout: float = 8.0) -> VideoMetadata:
    """Fetch public metadata via YouTube's oEmbed endpoint (no API key required).

    oEmbed is unauthenticated and returns title, author_name, thumbnail_url.
    If a video is private, removed, or age-restricted the endpoint returns
    401/403/404 and we surface a friendly error.
    """
    url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
    except httpx.HTTPError as e:
        raise YouTubeFetchError(f"Network error contacting YouTube: {e}") from e

    if resp.status_code == 401 or resp.status_code == 403:
        raise YouTubeFetchError(
            "This video is private or age-restricted and cannot be accessed."
        )
    if resp.status_code == 404:
        raise YouTubeFetchError("Video not found. It may have been removed.")
    if resp.status_code >= 400:
        raise YouTubeFetchError(f"YouTube oEmbed returned HTTP {resp.status_code}")

    data = resp.json()
    return VideoMetadata(
        title=data.get("title", ""),
        channel=data.get("author_name"),
        thumbnail=data.get("thumbnail_url"),
    )


def fetch_transcript(video_id: str) -> list[TranscriptSegment]:
    """Fetch the transcript for a video.

    Uses the ``YouTubeTranscriptApi().fetch()`` API (youtube-transcript-api >= 1.0).
    Prefers English (manual or auto-generated) and falls back to whatever exists.

    Raises ``YouTubeFetchError`` if no transcript is available.
    """
    try:
        # Prefer English (manual or auto-generated).
        try:
            fetched = YouTubeTranscriptApi().fetch(
                video_id, languages=["en", "en-US", "a.en"]
            )
        except NoTranscriptFound:
            # Fall back to any transcript the video has.
            fetched = YouTubeTranscriptApi().fetch(video_id)
    except TranscriptsDisabled:
        raise YouTubeFetchError("Transcripts are disabled for this video.") from None
    except VideoUnavailable:
        raise YouTubeFetchError("This video is unavailable.") from None
    except NoTranscriptFound:
        raise YouTubeFetchError(
            "No transcript is available for this video (no manual or auto-generated captions)."
        ) from None
    except Exception as e:  # pragma: no cover -- defensive
        logger.exception(f"Unexpected transcript error for {video_id}: {e}")
        raise YouTubeFetchError(f"Failed to fetch transcript: {e}") from e

    out: list[TranscriptSegment] = []
    for s in fetched:
        # s is a FetchedTranscriptSnippet with .text, .start, .duration
        text = (getattr(s, "text", "") or "").replace("\n", " ").strip()
        if not text:
            continue
        out.append(
            TranscriptSegment(
                text=text,
                start=float(getattr(s, "start", 0.0) or 0.0),
                duration=float(getattr(s, "duration", 0.0) or 0.0),
            )
        )
    if not out:
        raise YouTubeFetchError("Transcript was empty after cleanup.")
    return out
