"""Workspace + chat message routes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from loguru import logger
from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.exceptions import ConflictError, NotFoundError
from backend.db.models import Message, MessageRole, Workspace, WorkspaceStatus
from backend.deps import get_db
from backend.schemas.message import (
    ChatResponse,
    MessageCreate,
    MessageList,
    MessageOut,
)
from backend.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceList,
    WorkspaceOut,
)
from backend.services import youtube
from backend.services.ingestion import (
    chunk_transcript,
    run_ingestion,
    vectorstore_service,
)
from backend.services.rag import (
    answer_question,
    deserialize_sources,
    serialize_sources,
)


router = APIRouter(prefix="/workspaces", tags=["workspaces"])


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ws_to_out(ws: Workspace) -> WorkspaceOut:
    return WorkspaceOut(
        id=UUID(ws.id),
        youtube_url=ws.youtube_url,
        video_id=ws.video_id,
        title=ws.title,
        channel=ws.channel,
        duration_s=ws.duration_s,
        thumbnail=ws.thumbnail,
        status=ws.status,  # type: ignore[arg-type]
        error=ws.error,
        chunk_count=ws.chunk_count,
        created_at=ws.created_at,
        updated_at=ws.updated_at,
    )


def _msg_to_out(msg: Message) -> MessageOut:
    return MessageOut(
        id=UUID(msg.id),
        role=msg.role,  # type: ignore[arg-type]
        content=msg.content,
        sources=deserialize_sources(msg.sources),
        created_at=msg.created_at,
    )


def _get_workspace_or_404(db: Session, workspace_id: UUID) -> Workspace:
    ws = db.query(Workspace).filter(Workspace.id == str(workspace_id)).first()
    if not ws:
        raise NotFoundError(f"Workspace {workspace_id} not found")
    return ws


# ---------------------------------------------------------------------------
# workspace routes
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=WorkspaceOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create a workspace from a YouTube URL (idempotent on URL).",
)
async def create_workspace(
    payload: WorkspaceCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> WorkspaceOut:
    url = str(payload.youtube_url)
    # Normalize to canonical watch URL via video_id extraction
    try:
        video_id = youtube.extract_video_id(url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    canonical = youtube.canonical_url(video_id)

    existing = (
        db.query(Workspace).filter(Workspace.youtube_url == canonical).first()
    )
    if existing:
        # Idempotent return. If it's currently failed, allow re-ingest.
        if existing.status == WorkspaceStatus.FAILED:
            existing.status = WorkspaceStatus.PENDING
            existing.error = None
            db.add(existing)
            db.commit()
            background_tasks.add_task(_safe_run_ingestion, existing.id)
        return _ws_to_out(existing)

    # Best-effort metadata pre-fetch; never block creation on this.
    title = ""
    channel = None
    thumbnail = None
    try:
        meta = await youtube.fetch_video_metadata(video_id)
        title = meta.title or video_id
        channel = meta.channel
        thumbnail = meta.thumbnail
    except Exception as e:
        logger.warning(f"oEmbed pre-fetch failed for {video_id}: {e}")
        title = video_id  # placeholder; will be updated if/when re-fetched

    ws = Workspace(
        youtube_url=canonical,
        video_id=video_id,
        title=title,
        channel=channel,
        thumbnail=thumbnail,
        status=WorkspaceStatus.PENDING,
    )
    db.add(ws)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Race lost -- another request created it. Return the winner.
        ws = db.query(Workspace).filter(Workspace.youtube_url == canonical).first()
        if not ws:
            raise ConflictError("Workspace creation raced; please retry")
    db.refresh(ws)

    background_tasks.add_task(_safe_run_ingestion, ws.id)
    return _ws_to_out(ws)


def _safe_run_ingestion(workspace_id: str) -> None:
    """Background task wrapper: re-opens a session, runs ingestion, logs errors."""
    from backend.db.session import SessionLocal
    from backend.services.ingestion import vectorstore_service as vs

    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        if not ws:
            logger.error(f"Background ingest: workspace {workspace_id} not found")
            return
        # We can't await in BackgroundTask -- but run_ingestion is currently
        # defined as async because of oEmbed. The oEmbed call is best-effort
        # and guarded by a try/except, so we can run it sync-ish via asyncio.
        import asyncio

        try:
            asyncio.run(run_ingestion(db, ws, vs))
        except Exception as e:
            logger.exception(f"Background ingest failed for {workspace_id}: {e}")
    finally:
        db.close()


@router.get(
    "",
    response_model=WorkspaceList,
    summary="List workspaces, most recent first.",
)
def list_workspaces(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> WorkspaceList:
    total = db.query(Workspace).count()
    rows = (
        db.query(Workspace)
        .order_by(desc(Workspace.created_at))
        .limit(limit)
        .offset(offset)
        .all()
    )
    return WorkspaceList(items=[_ws_to_out(r) for r in rows], total=total)


@router.get(
    "/by-url",
    response_model=WorkspaceOut,
    summary="Lookup a workspace by its YouTube URL.",
)
def get_workspace_by_url(
    url: str = Query(..., description="YouTube watch URL"),
    db: Session = Depends(get_db),
) -> WorkspaceOut:
    try:
        video_id = youtube.extract_video_id(url)
        canonical = youtube.canonical_url(video_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    ws = db.query(Workspace).filter(Workspace.youtube_url == canonical).first()
    if not ws:
        raise NotFoundError("No workspace for that URL")
    return _ws_to_out(ws)


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceOut,
    summary="Get a workspace by id.",
)
def get_workspace(
    workspace_id: UUID,
    db: Session = Depends(get_db),
) -> WorkspaceOut:
    return _ws_to_out(_get_workspace_or_404(db, workspace_id))


@router.delete(
    "/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a workspace, its messages, and its vector store.",
)
def delete_workspace(
    workspace_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    ws = _get_workspace_or_404(db, workspace_id)
    # Remove vector store first (durable side effect)
    vectorstore_service.delete_collection(ws.id)
    db.delete(ws)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# message routes
# ---------------------------------------------------------------------------


@router.get(
    "/{workspace_id}/messages",
    response_model=MessageList,
    summary="List messages for a workspace, chronological.",
)
def list_messages(
    workspace_id: UUID,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> MessageList:
    ws = _get_workspace_or_404(db, workspace_id)
    total = db.query(Message).filter(Message.workspace_id == ws.id).count()
    rows = (
        db.query(Message)
        .filter(Message.workspace_id == ws.id)
        .order_by(Message.created_at.asc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return MessageList(items=[_msg_to_out(r) for r in rows], total=total)


@router.post(
    "/{workspace_id}/messages",
    response_model=ChatResponse,
    summary="Send a user message; receive the assistant reply with sources.",
)
def post_message(
    workspace_id: UUID,
    payload: MessageCreate,
    db: Session = Depends(get_db),
) -> ChatResponse:
    ws = _get_workspace_or_404(db, workspace_id)
    if ws.status != WorkspaceStatus.READY:
        if ws.status in (WorkspaceStatus.PENDING, WorkspaceStatus.INGESTING):
            suffix = "Wait for ingestion to finish."
        else:
            suffix = f"Error: {ws.error or 'unknown'}"
        raise ConflictError(f"Workspace is not ready (status={ws.status}). {suffix}")

    user_msg = Message(
        workspace_id=ws.id,
        role=MessageRole.USER,
        content=payload.content.strip(),
    )
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    # Run RAG
    result = answer_question(db, ws, user_msg.content, vectorstore_service)

    assistant_msg = Message(
        workspace_id=ws.id,
        role=MessageRole.ASSISTANT,
        content=result.content,
        sources=serialize_sources(result.sources),
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        latency_ms=result.latency_ms,
    )
    db.add(assistant_msg)
    db.commit()
    db.refresh(assistant_msg)

    return ChatResponse(
        user_message=_msg_to_out(user_msg),
        assistant_message=_msg_to_out(assistant_msg),
    )
