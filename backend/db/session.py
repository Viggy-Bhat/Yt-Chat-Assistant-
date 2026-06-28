"""Database engine + session factory.

Uses synchronous SQLAlchemy 2.0 with SQLite. FastAPI endpoints run in
``def`` (sync) style for simplicity at MVP scale; can be swapped to async
without changing call sites if needed.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.core.config import get_settings


_settings = get_settings()

# `check_same_thread=False` is required for SQLite when used across threads
# (FastAPI's threadpool). WAL mode gives us better concurrent reads.
engine = create_engine(
    _settings.sqlite_url,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
    future=True,
)


# Ensure parent dir exists
_settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)


SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a DB session and ensures cleanup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
