"""ORM models for workspaces and messages."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorkspaceStatus:
    PENDING = "pending"
    INGESTING = "ingesting"
    READY = "ready"
    FAILED = "failed"
    ALL = (PENDING, INGESTING, READY, FAILED)


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        Index("ix_workspaces_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    youtube_url: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    video_id: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    channel: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    duration_s: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    thumbnail: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=WorkspaceStatus.PENDING)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="workspace",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class MessageRole:
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    ALL = (USER, ASSISTANT, SYSTEM)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_messages_workspace_id"),
        Index("ix_messages_workspace_created", "workspace_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON-encoded list
    tokens_in: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="messages")
