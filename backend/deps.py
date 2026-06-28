"""FastAPI dependencies."""

from __future__ import annotations

from typing import Iterator

from fastapi import Depends
from sqlalchemy.orm import Session

from backend.db.session import get_db as _get_db


def get_db() -> Iterator[Session]:
    """Re-export the DB session dependency."""
    yield from _get_db()
