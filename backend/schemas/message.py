"""Pydantic schemas for chat messages."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


RoleLiteral = Literal["user", "assistant"]


class SourceChunk(BaseModel):
    """A retrieved transcript chunk with timestamp info."""

    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    text: str
    score: Optional[float] = Field(default=None, description="Similarity score (lower = closer)")


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: RoleLiteral
    content: str
    sources: list[SourceChunk] = Field(default_factory=list)
    created_at: datetime


class MessageList(BaseModel):
    items: list[MessageOut]
    total: int


class ChatResponse(BaseModel):
    """Returned from POST /workspaces/{id}/messages."""

    user_message: MessageOut
    assistant_message: MessageOut
