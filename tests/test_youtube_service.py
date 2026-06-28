"""Tests for the YouTube service: URL parsing + canonicalization."""

from __future__ import annotations

import pytest

from backend.core.exceptions import BadRequestError
from backend.services import youtube


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("http://m.youtube.com/watch?v=dQw4w9WgXcQ&t=42s", "dQw4w9WgXcQ"),
        ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),  # bare id
    ],
)
def test_extract_video_id_valid(url: str, expected: str) -> None:
    assert youtube.extract_video_id(url) == expected


@pytest.mark.parametrize("url", ["", "not-a-url", "https://example.com", "https://www.youtube.com/watch?v=short"])
def test_extract_video_id_invalid(url: str) -> None:
    with pytest.raises(BadRequestError):
        youtube.extract_video_id(url)


def test_canonical_url() -> None:
    assert youtube.canonical_url("dQw4w9WgXcQ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_canonical_url_rejects_invalid() -> None:
    with pytest.raises(BadRequestError):
        youtube.canonical_url("nope")
