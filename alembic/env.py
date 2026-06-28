"""Alembic environment configuration.

Loads DB URL from app settings (so .env is respected) and imports models
from the backend package for autogenerate support.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make `backend` importable when running `alembic` from project root
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.config import get_settings  # noqa: E402
from backend.db.base import Base  # noqa: E402
from backend.db import models  # noqa: F401,E402  -- ensure models register

config = context.config

# Override sqlalchemy.url from app settings
settings = get_settings()
settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
config.set_main_option("sqlalchemy.url", settings.sqlite_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.sqlite_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
