"""Streamlit frontend for YouTube Chat.

Design notes (per frontend-design principles):
- Distinctive dark aesthetic -- not the default Streamlit look.
- Custom CSS for typography, message bubbles, sidebar, status pills.
- Tight visual hierarchy: sidebar (workspaces) -> header (video) -> chat -> input.
- Generous spacing, high contrast, accent color for primary actions.

Run:  streamlit run frontend/streamlit_app.py
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
import streamlit as st


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000/api/v1")
REQUEST_TIMEOUT = 30.0
POLL_INTERVAL_S = 2.0


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------


class APIError(Exception):
    pass


def _request(method: str, path: str, **kwargs: Any) -> dict[str, Any] | list[Any]:
    url = f"{API_BASE_URL}{path}"
    try:
        resp = httpx.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
    except httpx.HTTPError as e:
        raise APIError(f"Network error: {e}") from e
    if resp.status_code >= 400:
        detail = resp.text
        try:
            detail = resp.json().get("error", {}).get("message", resp.text)
        except Exception:
            pass
        raise APIError(f"[{resp.status_code}] {detail}")
    if resp.status_code == 204 or not resp.content:
        return {}
    return resp.json()


def list_workspaces() -> list[dict[str, Any]]:
    data = _request("GET", "/workspaces?limit=100")
    return data.get("items", []) if isinstance(data, dict) else []  # type: ignore[return-value]


def get_workspace(workspace_id: str) -> dict[str, Any]:
    return _request("GET", f"/workspaces/{workspace_id}")  # type: ignore[return-value]


def create_workspace(url: str) -> dict[str, Any]:
    return _request("POST", "/workspaces", json={"youtube_url": url})  # type: ignore[return-value]


def get_workspace_by_url(url: str) -> dict[str, Any] | None:
    try:
        return _request("GET", "/workspaces/by-url", params={"url": url})  # type: ignore[return-value]
    except APIError as e:
        if "404" in str(e) or "not found" in str(e).lower():
            return None
        raise


def delete_workspace(workspace_id: str) -> None:
    _request("DELETE", f"/workspaces/{workspace_id}")


def list_messages(workspace_id: str) -> list[dict[str, Any]]:
    data = _request("GET", f"/workspaces/{workspace_id}/messages?limit=500")
    return data.get("items", []) if isinstance(data, dict) else []  # type: ignore[return-value]


def send_message(workspace_id: str, content: str) -> dict[str, Any]:
    return _request("POST", f"/workspaces/{workspace_id}/messages", json={"content": content})  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
    --bg-0: #0a0b0f;
    --bg-1: #11131a;
    --bg-2: #181b25;
    --bg-3: #222633;
    --border: #2a2f3e;
    --text-0: #f5f6fa;
    --text-1: #b8bcc8;
    --text-2: #6f7689;
    --accent: #7c5cff;
    --accent-2: #5a8cff;
    --success: #34d399;
    --warn: #fbbf24;
    --danger: #f87171;
    --shadow: 0 8px 24px rgba(0,0,0,0.4);
}

html, body, [class*="css"]  {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}

.stApp {
    background: linear-gradient(180deg, var(--bg-0) 0%, var(--bg-1) 100%) !important;
    color: var(--text-0);
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: var(--bg-1) !important;
    border-right: 1px solid var(--border);
}
section[data-testid="stSidebar"] * {
    color: var(--text-0) !important;
}

/* Headers */
h1, h2, h3 {
    color: var(--text-0) !important;
    font-weight: 600 !important;
    letter-spacing: -0.01em;
}

/* Buttons */
.stButton > button {
    background: var(--bg-2) !important;
    color: var(--text-0) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    padding: 0.55rem 1rem !important;
    font-weight: 500 !important;
    transition: all 0.15s ease !important;
}
.stButton > button:hover {
    background: var(--bg-3) !important;
    border-color: var(--accent) !important;
    transform: translateY(-1px);
}
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, var(--accent) 0%, var(--accent-2) 100%) !important;
    border: none !important;
    color: white !important;
}

/* Input */
.stTextInput input, .stChatInput textarea, .stChatInput input {
    background: var(--bg-2) !important;
    color: var(--text-0) !important;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
    font-size: 0.95rem !important;
}
.stTextInput input:focus, .stChatInput textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px rgba(124,92,255,0.15) !important;
}

/* Hide default decorations */
#MainMenu, footer, header[data-testid="stHeader"] {
    visibility: hidden;
}

/* Custom components */
.ws-card {
    padding: 0.85rem 0.95rem;
    margin: 0.4rem 0;
    background: var(--bg-2);
    border: 1px solid var(--border);
    border-radius: 12px;
    cursor: pointer;
    transition: all 0.15s ease;
}
.ws-card:hover {
    background: var(--bg-3);
    border-color: var(--accent);
    transform: translateX(2px);
}
.ws-card.active {
    background: linear-gradient(135deg, rgba(124,92,255,0.15), rgba(90,140,255,0.08));
    border-color: var(--accent);
}
.ws-card .title {
    font-size: 0.88rem;
    font-weight: 600;
    color: var(--text-0);
    margin: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
}
.ws-card .meta {
    font-size: 0.72rem;
    color: var(--text-2);
    margin-top: 0.2rem;
}

.status-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.2rem 0.65rem;
    border-radius: 999px;
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}
.status-pending  { background: rgba(251,191,36,0.12); color: var(--warn); }
.status-ingesting{ background: rgba(124,92,255,0.15); color: var(--accent); }
.status-ready    { background: rgba(52,211,153,0.12); color: var(--success); }
.status-failed   { background: rgba(248,113,113,0.12); color: var(--danger); }
.status-pill::before {
    content: '';
    width: 6px; height: 6px;
    border-radius: 50%;
    background: currentColor;
}
.status-ingesting::before { animation: pulse 1.2s ease-in-out infinite; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }

.video-header {
    display: flex;
    gap: 1rem;
    padding: 1rem 1.25rem;
    background: var(--bg-2);
    border: 1px solid var(--border);
    border-radius: 16px;
    margin-bottom: 1.25rem;
    align-items: center;
}
.video-header img {
    width: 120px;
    height: 68px;
    object-fit: cover;
    border-radius: 8px;
    flex-shrink: 0;
}
.video-header .vtitle {
    font-size: 1.05rem;
    font-weight: 600;
    color: var(--text-0);
    margin: 0 0 0.2rem 0;
}
.video-header .vchannel {
    font-size: 0.82rem;
    color: var(--text-1);
    margin: 0;
}

.empty-hero {
    text-align: center;
    padding: 5rem 2rem 3rem;
}
.empty-hero h1 {
    font-size: 2.4rem !important;
    font-weight: 700 !important;
    background: linear-gradient(135deg, #fff 0%, var(--accent-2) 60%, var(--accent) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 0.5rem;
}
.empty-hero p {
    color: var(--text-1);
    font-size: 1.05rem;
    max-width: 520px;
    margin: 0 auto;
}

.source-card {
    background: var(--bg-3);
    border: 1px solid var(--border);
    border-left: 3px solid var(--accent);
    border-radius: 8px;
    padding: 0.65rem 0.85rem;
    margin: 0.4rem 0;
    font-size: 0.85rem;
    color: var(--text-1);
    line-height: 1.5;
}
.source-card .ts {
    font-family: 'JetBrains Mono', monospace;
    color: var(--accent);
    font-weight: 600;
    font-size: 0.78rem;
    margin-right: 0.4rem;
}

.brand {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.5rem 0 1.25rem;
    font-weight: 700;
    font-size: 1.15rem;
    color: var(--text-0);
}
.brand-mark {
    width: 32px; height: 32px;
    background: linear-gradient(135deg, var(--accent), var(--accent-2));
    border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    color: white; font-size: 1rem;
}
.subtle { color: var(--text-2); font-size: 0.78rem; }
.error-box {
    background: rgba(248,113,113,0.1);
    border: 1px solid rgba(248,113,113,0.3);
    color: var(--danger);
    padding: 0.75rem 1rem;
    border-radius: 10px;
    font-size: 0.88rem;
    margin: 0.5rem 0;
}
</style>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def status_pill(status: str) -> str:
    label = {"pending": "Pending", "ingesting": "Indexing", "ready": "Ready", "failed": "Failed"}.get(status, status)
    return f'<span class="status-pill status-{status}">{label}</span>'


def format_timestamp(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def time_ago(dt_str: str) -> str:
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        delta = datetime.now(dt.tzinfo) - dt
        s = int(delta.total_seconds())
        if s < 60: return "just now"
        if s < 3600: return f"{s//60}m ago"
        if s < 86400: return f"{s//3600}h ago"
        return f"{s//86400}d ago"
    except Exception:
        return ""


def render_video_header(ws: dict[str, Any]) -> None:
    title = ws.get("title") or "Untitled video"
    channel = ws.get("channel") or "Unknown channel"
    thumb = ws.get("thumbnail") or ""
    img_html = f'<img src="{thumb}" alt="thumbnail">' if thumb else '<div style="width:120px;height:68px;background:var(--bg-3);border-radius:8px;"></div>'
    st.markdown(
        f"""
        <div class="video-header">
            {img_html}
            <div style="flex:1;min-width:0;">
                <p class="vtitle">{title}</p>
                <p class="vchannel">{channel} &middot; {status_pill(ws.get('status','pending'))}</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sources(sources: list[dict[str, Any]]) -> None:
    if not sources:
        return
    with st.expander(f"Sources ({len(sources)})", expanded=False):
        for s in sources:
            ts = format_timestamp(s.get("start", 0))
            text = (s.get("text") or "").strip()
            st.markdown(
                f'<div class="source-card"><span class="ts">{ts}</span>{text}</div>',
                unsafe_allow_html=True,
            )


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def init_state() -> None:
    if "active_workspace_id" not in st.session_state:
        st.session_state.active_workspace_id = None
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "last_loaded_for" not in st.session_state:
        st.session_state.last_loaded_for = None
    if "error" not in st.session_state:
        st.session_state.error = None


def load_workspace_view(workspace_id: str) -> None:
    """Fetch workspace + messages; populate state."""
    if st.session_state.last_loaded_for == workspace_id:
        return
    try:
        ws = get_workspace(workspace_id)
        msgs = list_messages(workspace_id)
    except APIError as e:
        st.session_state.error = str(e)
        return
    st.session_state.active_workspace_id = workspace_id
    st.session_state.active_workspace = ws
    st.session_state.messages = msgs
    st.session_state.last_loaded_for = workspace_id
    st.session_state.error = None


def refresh_active_workspace() -> None:
    """Polled by the UI to update ingestion status."""
    wid = st.session_state.active_workspace_id
    if not wid:
        return
    try:
        ws = get_workspace(wid)
    except APIError:
        return
    st.session_state.active_workspace = ws


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown(
            '<div class="brand"><div class="brand-mark">▶</div><div>YT Chat</div></div>',
            unsafe_allow_html=True,
        )

        # ---- New chat input (Enter submits via st.form) ----
        with st.form(key="new_chat_form", clear_on_submit=True):
            new_url = st.text_input(
                "YouTube URL",
                placeholder="https://www.youtube.com/watch?v=...",
                label_visibility="collapsed",
                key="new_url_input",
            )
            submitted = st.form_submit_button(
                "+ New chat", use_container_width=True, type="primary"
            )

        if submitted:
            url = (new_url or "").strip()
            if not url:
                st.session_state.error = "Please paste a YouTube URL first."
            else:
                handle_new_url(url)

        if st.session_state.error and not st.session_state.get("active_workspace_id"):
            st.markdown(
                f'<div class="error-box">{st.session_state.error}</div>',
                unsafe_allow_html=True,
            )

        st.button(
            "Refresh workspaces",
            use_container_width=True,
            on_click=lambda: st.session_state.update(last_loaded_for=None),
        )

        st.markdown("---")
        st.markdown("**Your workspaces**")

        try:
            workspaces = list_workspaces()
        except APIError as e:
            st.markdown(
                f'<div class="error-box">Cannot reach API: {e}</div>',
                unsafe_allow_html=True,
            )
            workspaces = []

        if not workspaces:
            st.markdown(
                '<p class="subtle">No workspaces yet. Paste a YouTube URL above and press Enter to start.</p>',
                unsafe_allow_html=True,
            )
            return

        for ws in workspaces:
            title = ws.get("title") or "Untitled"
            status = ws.get("status", "pending")
            updated = time_ago(ws.get("updated_at", ""))
            active = st.session_state.active_workspace_id == ws.get("id")
            cls = "ws-card active" if active else "ws-card"
            st.markdown(
                f"""
                <div class="{cls}">
                    <p class="title">{title}</p>
                    <p class="meta">{status_pill(status)} &middot; {updated}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            c1, c2 = st.columns([5, 1])
            with c1:
                if st.button("Open", key=f"open_{ws['id']}", use_container_width=True):
                    load_workspace_view(ws["id"])
                    st.rerun()
            with c2:
                if st.button("✕", key=f"del_{ws['id']}"):
                    try:
                        delete_workspace(ws["id"])
                        if st.session_state.active_workspace_id == ws["id"]:
                            st.session_state.active_workspace_id = None
                            st.session_state.messages = []
                            st.session_state.last_loaded_for = None
                        st.rerun()
                    except APIError as e:
                        st.error(str(e))


def handle_new_url(url: str) -> None:
    # If a workspace already exists for this URL, just open it.
    try:
        existing = get_workspace_by_url(url)
    except APIError as e:
        st.session_state.error = str(e)
        return
    if existing:
        load_workspace_view(existing["id"])
        st.session_state.error = None
        st.rerun()
        return
    try:
        ws = create_workspace(url)
    except APIError as e:
        st.session_state.error = str(e)
        return
    load_workspace_view(ws["id"])
    st.session_state.error = None
    st.rerun()


def render_chat_view() -> None:
    ws = st.session_state.get("active_workspace")
    if not ws:
        render_empty_state()
        return

    render_video_header(ws)
    status = ws.get("status")

    if st.session_state.error:
        st.markdown(f'<div class="error-box">{st.session_state.error}</div>', unsafe_allow_html=True)

    if status == "pending" or status == "ingesting":
        st.info("Indexing video transcript... This usually takes 5-30 seconds.")
        # Auto-refresh while ingesting
        time.sleep(POLL_INTERVAL_S)
        refresh_active_workspace()
        st.rerun()
        return

    if status == "failed":
        st.markdown(
            f'<div class="error-box">Ingestion failed: {ws.get("error") or "unknown error"}</div>',
            unsafe_allow_html=True,
        )
        return

    # Ready: show messages
    for m in st.session_state.messages:
        with st.chat_message(m["role"], avatar="🧑" if m["role"] == "user" else "🤖"):
            st.markdown(m["content"])
            if m["role"] == "assistant":
                render_sources(m.get("sources") or [])

    # Chat input
    prompt = st.chat_input("Ask anything about this video...")
    if prompt:
        send_and_render(prompt)


def send_and_render(prompt: str) -> None:
    wid = st.session_state.active_workspace_id
    # Optimistic user message
    st.session_state.messages.append(
        {"id": "tmp", "role": "user", "content": prompt, "sources": [], "created_at": datetime.utcnow().isoformat()}
    )
    try:
        result = send_message(wid, prompt)
    except APIError as e:
        st.session_state.messages.pop()  # remove optimistic
        st.session_state.error = str(e)
        st.rerun()
        return
    # Replace optimistic user msg + append assistant
    st.session_state.messages = [result["user_message"], result["assistant_message"]]
    st.session_state.error = None
    st.rerun()


def render_empty_state() -> None:
    st.markdown(
        """
        <div class="empty-hero">
            <h1>Chat with any YouTube video</h1>
            <p>Paste a YouTube URL in the sidebar to get a grounded, transcript-aware AI assistant. Your chats are saved per video.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(
        page_title="YT Chat",
        page_icon="▶",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    init_state()
    render_sidebar()
    render_chat_view()


if __name__ == "__main__":
    main()
