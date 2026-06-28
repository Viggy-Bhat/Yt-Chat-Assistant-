"""RAG chain: retrieve chunks, build prompt, call Groq, return answer + sources.

This is the core of the chat experience. We use LangChain's LCEL to keep
the chain composable and easy to swap (different LLM, different retriever,
streaming later, etc.).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_groq import ChatGroq
from loguru import logger
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.exceptions import LLMError
from backend.db.models import Message, MessageRole, Workspace
from backend.schemas.message import SourceChunk
from backend.services.vectorstore import RetrievedChunk, VectorStoreService


SYSTEM_PROMPT = """You are a precise, helpful assistant that answers questions about a YouTube video.

You have access to the video's transcript, broken into time-stamped chunks below.
Follow these rules strictly:

1. Answer ONLY using information from the transcript context. Do not use outside knowledge.
2. If the answer is not in the context, say: "I couldn't find that in the video's transcript."
3. When relevant, cite timestamps in this format: [mm:ss] or [h:mm:ss].
4. Be concise but complete. Use the same language as the user's question.
5. Do not invent quotes, names, or facts.

Transcript context (time-stamped chunks):
{context}
"""


@dataclass
class ChatResult:
    content: str
    sources: list[SourceChunk]
    tokens_in: Optional[int]
    tokens_out: Optional[int]
    latency_ms: int


def _format_timestamp(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _format_context(chunks: list[RetrievedChunk]) -> str:
    """Format retrieved chunks into a readable context block."""
    if not chunks:
        return "(no relevant context found)"
    settings = get_settings()
    pieces: list[str] = []
    used = 0
    for c in chunks:
        ts = _format_timestamp(c.start)
        line = f"[{ts}] {c.text}"
        if used + len(line) > settings.max_context_chars:
            break
        pieces.append(line)
        used += len(line) + 1
    return "\n".join(pieces)


def _load_history(db: Session, workspace_id: str, window: int) -> list[BaseMessage]:
    """Load the most recent N messages (excluding system) for a workspace."""
    rows = (
        db.query(Message)
        .filter(Message.workspace_id == workspace_id)
        .filter(Message.role.in_([MessageRole.USER, MessageRole.ASSISTANT]))
        .order_by(Message.created_at.desc())
        .limit(window)
        .all()
    )
    rows.reverse()  # chronological
    out: list[BaseMessage] = []
    for r in rows:
        if r.role == MessageRole.USER:
            out.append(HumanMessage(content=r.content))
        elif r.role == MessageRole.ASSISTANT:
            out.append(AIMessage(content=r.content))
    return out


def _sources_to_schema(chunks: list[RetrievedChunk]) -> list[SourceChunk]:
    return [
        SourceChunk(
            start=c.start,
            end=c.end,
            text=c.text,
            score=c.score,
        )
        for c in chunks
    ]


def _extract_usage(response: AIMessage) -> tuple[Optional[int], Optional[int]]:
    """Pull token usage from a LangChain AIMessage response_metadata when present."""
    meta = response.response_metadata or {}
    usage = meta.get("token_usage") or meta.get("usage") or {}
    tin = usage.get("prompt_tokens") or usage.get("input_tokens")
    tout = usage.get("completion_tokens") or usage.get("output_tokens")
    return tin, tout


def build_chain():
    """Build the LCEL RAG chain. We build context dynamically outside the chain."""
    settings = get_settings()
    llm = ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=settings.groq_temperature,
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{question}"),
        ]
    )
    return prompt | llm


def answer_question(
    db: Session,
    workspace: Workspace,
    user_message: str,
    vectorstore: VectorStoreService,
) -> ChatResult:
    """Run the full RAG flow for a single user message.

    Returns the assistant answer, the sources used, and timing info.
    """
    settings = get_settings()
    history = _load_history(db, workspace.id, settings.chat_history_window)
    chunks = vectorstore.query(workspace.id, user_message, top_k=settings.retrieval_top_k)
    context = _format_context(chunks)
    chain = build_chain()

    t0 = time.perf_counter()
    try:
        response: AIMessage = chain.invoke(
            {"context": context, "history": history, "question": user_message}
        )
    except Exception as e:
        logger.exception(f"Groq call failed: {e}")
        raise LLMError(f"LLM call failed: {e}") from e
    latency_ms = int((time.perf_counter() - t0) * 1000)

    content = response.content if isinstance(response.content, str) else str(response.content)
    tokens_in, tokens_out = _extract_usage(response)

    return ChatResult(
        content=content,
        sources=_sources_to_schema(chunks),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
    )


def serialize_sources(sources: list[SourceChunk]) -> str:
    """JSON-encode sources for storage in the messages.sources TEXT column."""
    return json.dumps([s.model_dump() for s in sources], ensure_ascii=False)


def deserialize_sources(raw: Optional[str]) -> list[SourceChunk]:
    if not raw:
        return []
    try:
        items = json.loads(raw)
        return [SourceChunk.model_validate(item) for item in items]
    except Exception:
        return []
