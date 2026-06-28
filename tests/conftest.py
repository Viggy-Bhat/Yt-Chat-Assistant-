"""Pytest fixtures shared across the test suite."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def temp_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the app at a throwaway data dir so tests don't touch real state.

    Autouse so every test gets a clean isolated env. The tempdir is cleaned
    up at the end (with ignore_errors on Windows for stray chroma locks).
    """
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("CHROMA_PERSIST_DIR", os.path.join(tmp, "chroma"))
    monkeypatch.setenv("SQLITE_PATH", os.path.join(tmp, "app.db"))
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    # Clear lru_caches on settings + embedding service
    from backend.core.config import get_settings
    from backend.services.embeddings import get_embedding_service

    get_settings.cache_clear()
    get_embedding_service.cache_clear()
    # Re-create the engine pointing at the new temp DB
    import importlib
    from backend.db import session as db_session
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    new_engine = create_engine(
        get_settings().sqlite_url,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
        future=True,
    )
    db_session.engine = new_engine
    db_session.SessionLocal = sessionmaker(
        bind=new_engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        class_=__import__("sqlalchemy.orm", fromlist=["Session"]).Session,
    )
    # Also rebuild the deps module's reference
    from backend import deps
    importlib.reload(deps)

    # Create the schema on the temp DB
    from backend.db.base import Base
    from backend.db import models  # noqa: F401 -- register models
    Base.metadata.create_all(new_engine)
    yield
    get_settings.cache_clear()
    get_embedding_service.cache_clear()
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
