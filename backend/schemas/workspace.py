"""Pydantic schemas for workspaces."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


WorkspaceStatusLiteral = Literal["pending", "ingesting", "ready", "failed"]


class WorkspaceCreate(BaseModel):
    youtube_url: HttpUrl = Field(..., description="Full YouTube watch URL")


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    youtube_url: str
    video_id: str
    title: str
    channel: Optional[str] = None
    duration_s: Optional[int] = None
    thumbnail: Optional[str] = None
    status: WorkspaceStatusLiteral
    error: Optional[str] = None
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class WorkspaceList(BaseModel):
    items: list[WorkspaceOut]
    total: int
