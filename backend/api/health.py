"""Liveness / readiness probe."""

from __future__ import annotations

from fastapi import APIRouter

from backend.core.config import get_settings


router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "version": "0.1.0",
        "model": settings.groq_model,
        "embedding_model": settings.embedding_model,
    }
