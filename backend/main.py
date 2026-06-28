"""FastAPI application entrypoint.

Wires up:
- Settings + logging
- CORS (for the Streamlit frontend)
- Exception handlers
- Routers under /api/v1
- Lifespan to pre-warm the embedding model
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from backend.api import health, workspaces
from backend.core.config import get_settings
from backend.core.exceptions import register_exception_handlers
from backend.core.logging import setup_logging
from backend.services.embeddings import get_embedding_service
from backend.services.ingestion import vectorstore_service


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    settings = get_settings()
    logger.info(
        f"Starting YouTube Chat API | model={settings.groq_model} | "
        f"embed={settings.embedding_model} | sqlite={settings.sqlite_path}"
    )
    # Pre-warm embedding model in a background thread so the first request
    # doesn't pay the cold-start cost.
    import asyncio

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: get_embedding_service(settings.embedding_model))
    # Touch vectorstore_service so chroma client is initialized
    _ = vectorstore_service
    logger.info("Startup complete.")
    yield
    logger.info("Shutdown complete.")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="YouTube Chat API",
        version="0.1.0",
        description=(
            "Chat with any YouTube video. POST a YouTube URL to create a "
            "workspace, then POST messages to that workspace to chat with the "
            "transcript-grounded assistant."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(workspaces.router, prefix="/api/v1")

    return app


app = create_app()
