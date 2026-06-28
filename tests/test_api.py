"""Smoke tests for the FastAPI app: health + workspace routes with mocked externals."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import create_app


def test_health() -> None:
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"


def test_create_workspace_invalid_url() -> None:
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/api/v1/workspaces", json={"youtube_url": "not-a-url"})
        # Pydantic HttpUrl validation -> 422
        assert r.status_code == 422


def test_get_workspace_by_url_404() -> None:
    app = create_app()
    with TestClient(app) as client:
        r = client.get(
            "/api/v1/workspaces/by-url",
            params={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        )
        assert r.status_code == 404


def test_list_workspaces_empty() -> None:
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/v1/workspaces")
        assert r.status_code == 200
        body = r.json()
        assert body["items"] == []
        assert body["total"] == 0
