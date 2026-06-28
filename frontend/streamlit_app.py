"""Streamlit frontend for YouTube Chat — Cinematic Dark Theatre Edition.

Design notes:
- Deep black background with warm radial glow (stage lighting effect).
- Typography: Fraunces (display) + Sora (body) + JetBrains Mono (mono).
- Gold/amber accent palette for warmth and premium feel.
- Film grain noise overlay + subtle vignette for theatrical depth.
- Smooth animations on messages, cards, and status transitions.

Run:  streamlit run frontend/streamlit_app.py
"""

from __future__ import annotations

import html
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
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400;9..144,500;9..144,600;9..144,700&family=Sora:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0,200');

:root {
    --bg-0: #0a0a0a;
    --bg-1: #111111;
    --bg-2: #1a1a1a;
    --bg-3: #242424;
    --bg-4: #2e2e2e;
    --border: #2a2a2a;
    --border-light: #3a3a3a;
    --text-0: #f5efe0;
    --text-1: #bfb8a8;
    --text-2: #6b6558;
    --text-3: #4a453c;
    --accent: #c9a95c;
    --accent-2: #d4b96a;
    --accent-dim: rgba(201, 169, 92, 0.15);
    --accent-glow: rgba(201, 169, 92, 0.08);
    --success: #7ac96a;
    --warn: #d4a54a;
    --danger: #c96a6a;
    --shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
    --shadow-glow: 0 4px 24px rgba(201, 169, 92, 0.12);
    --radius: 12px;
    --radius-lg: 16px;
}

html, body, [class*="css"] {
    font-family: 'Sora', -apple-system, BlinkMacSystemFont, sans-serif !important;
}

h1, h2, h3, h4, h5, h6 {
    font-family: 'Fraunces', Georgia, serif !important;
    letter-spacing: -0.02em;
}

.stApp {
    background: var(--bg-0) !important;
    color: var(--text-0);
}

/* Film grain overlay */
.stApp::after {
    content: '';
    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 9999;
    opacity: 0.03;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
    background-repeat: repeat;
    background-size: 256px 256px;
}

/* Vignette effect */
.stApp::before {
    content: '';
    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 9998;
    background: radial-gradient(ellipse 80% 60% at 50% 40%, transparent 40%, rgba(0, 0, 0, 0.6) 100%);
}

/* Warm stage glow behind main content */
.main > .block-container {
    position: relative;
}
.main > .block-container::before {
    content: '';
    position: fixed;
    top: -20%;
    left: 50%;
    transform: translateX(-50%);
    width: 800px;
    height: 600px;
    background: radial-gradient(ellipse, rgba(201, 169, 92, 0.04) 0%, transparent 70%);
    pointer-events: none;
    z-index: 0;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: var(--bg-1) !important;
    border-right: 1px solid var(--border);
    position: relative;
    z-index: 1;
}
section[data-testid="stSidebar"] * {
    color: var(--text-0) !important;
}

/* Headers */
h1, h2, h3 {
    color: var(--text-0) !important;
    font-weight: 600 !important;
    letter-spacing: -0.02em;
}

/* Buttons */
.stButton > button {
    background: var(--bg-2) !important;
    color: var(--text-0) !important;
    border: 1px solid var(--border) !important;
    font-family: 'Sora', sans-serif !important;
    border-radius: 10px !important;
    padding: 0.55rem 1rem !important;
    font-weight: 500 !important;
    font-size: 0.85rem !important;
    transition: all 0.2s ease !important;
}
.stButton > button:hover {
    background: var(--bg-3) !important;
    border-color: var(--accent) !important;
    box-shadow: var(--shadow-glow);
    transform: translateY(-1px);
}
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, var(--accent) 0%, var(--accent-2) 100%) !important;
    border: none !important;
    color: #0a0a0a !important;
    font-weight: 600 !important;
    letter-spacing: 0.02em;
}
.stButton > button[kind="primary"]:hover {
    box-shadow: 0 4px 20px rgba(201, 169, 92, 0.3) !important;
    transform: translateY(-2px);
}

/* Input fields */
.stTextInput input, .stChatInput textarea, .stChatInput input {
    background: var(--bg-2) !important;
    color: var(--text-0) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    font-family: 'Sora', sans-serif !important;
    font-size: 0.9rem !important;
    caret-color: var(--accent);
}
.stTextInput input:focus, .stChatInput textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px var(--accent-dim) !important;
}
.stTextInput input::placeholder, .stChatInput textarea::placeholder {
    color: var(--text-3) !important;
}

/* Custom chat bubbles */
.chat-bubble {
    display: flex;
    gap: 10px;
    align-items: flex-start;
    padding: 0.35rem 0;
    animation: fadeSlideIn 0.3s ease-out;
}
.chat-avatar {
    font-size: 1.3rem;
    background: var(--bg-2);
    width: 34px;
    height: 34px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    flex-shrink: 0;
    border: 1px solid var(--border);
    line-height: 1;
}
.chat-content {
    background: var(--bg-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 0.85rem 1.1rem;
    color: var(--text-0);
    font-size: 0.9rem;
    line-height: 1.65;
    flex: 1;
    min-width: 0;
}
.chat-bubble-user .chat-avatar {
    order: 1;
}
.chat-bubble-user .chat-content {
    background: linear-gradient(135deg, var(--bg-3), var(--bg-2));
    border-color: var(--accent);
    border-bottom-right-radius: 4px;
}
.chat-bubble-assistant .chat-content {
    border-left: 2px solid var(--accent);
    border-bottom-left-radius: 4px;
}

/* Thinking indicator — animated gold bouncing dots */
.thinking-indicator {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 0.85rem 1.1rem;
    margin: 0.35rem 0 0.35rem 44px;
    background: var(--bg-2);
    border: 1px solid var(--border);
    border-left: 2px solid var(--accent);
    border-radius: var(--radius-lg);
    border-bottom-left-radius: 4px;
    min-height: 36px;
    animation: fadeSlideIn 0.2s ease-out;
}
.thinking-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--accent);
    animation: thinkBounce 1.4s ease-in-out infinite;
}
.thinking-dot:nth-child(2) { animation-delay: 0.2s; }
.thinking-dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes thinkBounce {
    0%, 80%, 100% { opacity: 0.25; transform: translateY(0); }
    40% { opacity: 1; transform: translateY(-6px); }
}

@keyframes fadeSlideIn {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
}

/* Hide default decorations */
#MainMenu, footer, header[data-testid="stHeader"] {
    visibility: hidden;
}

/* Custom scrollbar */
::-webkit-scrollbar {
    width: 6px;
    height: 6px;
}
::-webkit-scrollbar-track {
    background: transparent;
}
::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
    background: var(--accent);
}

/* Workspace cards */
.ws-card {
    padding: 0.85rem 0.95rem;
    margin: 0.5rem 0;
    background: var(--bg-2);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    cursor: pointer;
    transition: all 0.2s ease;
    position: relative;
    overflow: hidden;
}
.ws-card::before {
    content: '';
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 3px;
    background: transparent;
    border-radius: 0 3px 3px 0;
    transition: background 0.2s ease;
}
.ws-card:hover {
    background: var(--bg-3);
    border-color: var(--accent);
    transform: translateX(3px);
    box-shadow: var(--shadow-glow);
}
.ws-card.active {
    background: linear-gradient(135deg, var(--accent-dim), transparent 80%);
    border-color: var(--accent);
    box-shadow: var(--shadow-glow);
}
.ws-card.active::before {
    background: var(--accent);
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
    margin-top: 0.25rem;
}

/* Status pills */
.status-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.15rem 0.6rem;
    border-radius: 999px;
    font-size: 0.65rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    position: relative;
}
.status-pending  { background: rgba(212, 165, 74, 0.12); color: var(--warn); border: 1px solid rgba(212, 165, 74, 0.2); }
.status-ingesting { background: rgba(201, 169, 92, 0.12); color: var(--accent); border: 1px solid rgba(201, 169, 92, 0.2); }
.status-ready    { background: rgba(122, 201, 106, 0.12); color: var(--success); border: 1px solid rgba(122, 201, 106, 0.2); }
.status-failed   { background: rgba(201, 106, 106, 0.12); color: var(--danger); border: 1px solid rgba(201, 106, 106, 0.2); }
.status-pill::before {
    content: '';
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: currentColor;
}
.status-ingesting::before {
    animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.3; transform: scale(0.6); }
}

/* Video header */
.video-header {
    display: flex;
    gap: 1rem;
    padding: 1rem 1.25rem;
    background: var(--bg-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    margin-bottom: 1.5rem;
    align-items: center;
    position: relative;
    z-index: 1;
    transition: border-color 0.2s ease;
}
.video-header:hover {
    border-color: var(--border-light);
}
.video-header img {
    width: 120px;
    height: 68px;
    object-fit: cover;
    border-radius: 8px;
    flex-shrink: 0;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
}
.video-header .vtitle {
    font-family: 'Fraunces', Georgia, serif !important;
    font-size: 1.1rem;
    font-weight: 600;
    color: var(--text-0);
    margin: 0 0 0.2rem 0;
    line-height: 1.3;
}
.video-header .vchannel {
    font-size: 0.82rem;
    color: var(--text-1);
    margin: 0;
}

/* Empty state */
.empty-hero {
    text-align: center;
    padding: 6rem 2rem 3rem;
    position: relative;
    z-index: 1;
}
.empty-hero h1 {
    font-family: 'Fraunces', Georgia, serif !important;
    font-size: 2.8rem !important;
    font-weight: 700 !important;
    background: linear-gradient(135deg, #f5efe0 0%, var(--accent-2) 50%, var(--accent) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 0.75rem;
    line-height: 1.15;
}
.empty-hero p {
    color: var(--text-1);
    font-size: 1.05rem;
    max-width: 480px;
    margin: 0 auto;
    line-height: 1.6;
}

/* Source cards (inside expander) */
.source-card {
    background: var(--bg-3);
    border: 1px solid var(--border);
    border-left: 3px solid var(--accent);
    border-radius: 8px;
    padding: 0.7rem 0.9rem;
    margin: 0.5rem 0;
    font-size: 0.82rem;
    color: var(--text-1);
    line-height: 1.55;
    transition: all 0.15s ease;
}
.source-card:hover {
    border-color: var(--border-light);
    background: var(--bg-4);
}
.source-card .ts {
    font-family: 'JetBrains Mono', monospace;
    color: var(--accent);
    font-weight: 500;
    font-size: 0.75rem;
    margin-right: 0.5rem;
    display: inline-block;
    min-width: 3.5em;
}
.source-card .source-score {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.7rem;
    color: var(--text-2);
    float: right;
}

/* Expander override */
.streamlit-expanderHeader {
    font-family: 'Sora', sans-serif !important;
    font-size: 0.82rem !important;
    color: var(--text-1) !important;
    background: var(--bg-2) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    padding: 0.4rem 0.8rem !important;
    margin: 0.25rem 0 !important;
}
.streamlit-expanderHeader:hover {
    border-color: var(--accent) !important;
}
.streamlit-expanderContent {
    border: none !important;
    background: transparent !important;
    padding: 0.25rem 0 0 0.5rem !important;
}

/* Brand */
.brand {
    display: flex;
    align-items: center;
    gap: 0.65rem;
    padding: 0.5rem 0 1.25rem;
}
.brand-text {
    font-family: 'Fraunces', Georgia, serif !important;
    font-weight: 700;
    font-size: 1.25rem;
    color: var(--text-0);
    letter-spacing: -0.03em;
}
.brand-mark {
    width: 34px;
    height: 34px;
    background: linear-gradient(135deg, var(--accent), var(--accent-2));
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #0a0a0a;
    font-size: 1.05rem;
    font-weight: 700;
    font-family: 'Fraunces', serif;
    box-shadow: 0 2px 12px rgba(201, 169, 92, 0.25);
    animation: glowPulse 3s ease-in-out infinite;
    flex-shrink: 0;
}
@keyframes glowPulse {
    0%, 100% { box-shadow: 0 2px 12px rgba(201, 169, 92, 0.25); }
    50% { box-shadow: 0 2px 20px rgba(201, 169, 92, 0.4); }
}

.subtle {
    color: var(--text-2);
    font-size: 0.78rem;
    line-height: 1.5;
}

/* Error box */
.error-box {
    background: rgba(201, 106, 106, 0.08);
    border: 1px solid rgba(201, 106, 106, 0.25);
    color: var(--danger);
    padding: 0.7rem 1rem;
    border-radius: 10px;
    font-size: 0.85rem;
    margin: 0.5rem 0;
    line-height: 1.5;
}

/* Indexing info box override */
.stAlert {
    background: var(--accent-dim) !important;
    color: var(--accent) !important;
    border: 1px solid rgba(201, 169, 92, 0.2) !important;
    border-radius: var(--radius) !important;
    font-family: 'Sora', sans-serif !important;
    font-size: 0.9rem !important;
    backdrop-filter: blur(8px);
}

/* Separator */
hr {
    border-color: var(--border) !important;
    margin: 1rem 0 !important;
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
    with st.expander(f"📎 Sources ({len(sources)})", expanded=False):
        for s in sources:
            ts = format_timestamp(s.get("start", 0))
            text = (s.get("text") or "").strip()
            score = s.get("score")
            score_html = f' <span class="source-score">{score:.3f}</span>' if score is not None else ""
            st.markdown(
                f'<div class="source-card"><span class="ts">{ts}</span>{text}{score_html}</div>',
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
            '<div class="brand"><div class="brand-mark">⌂</div><div class="brand-text">YT Chat</div></div>',
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

        st.markdown("<hr>", unsafe_allow_html=True)
        st.markdown("<h4 style='margin: 0.5rem 0 0.25rem 0; font-family: Fraunces, serif !important;'>Workspaces</h4>", unsafe_allow_html=True)

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
        role = m["role"]
        avatar = "🧑" if role == "user" else "🤖"
        bubble_class = "chat-bubble-user" if role == "user" else "chat-bubble-assistant"
        safe_content = html.escape(m["content"])
        st.markdown(
            f'<div class="chat-bubble {bubble_class}">'
            f'<span class="chat-avatar">{avatar}</span>'
            f'<div class="chat-content">{safe_content}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        if role == "assistant":
            render_sources(m.get("sources") or [])

    # Chat input
    prompt = st.chat_input("Ask anything about this video...")
    if prompt:
        send_and_render(prompt)


def send_and_render(prompt: str) -> None:
    wid = st.session_state.active_workspace_id

    # Render animated thinking indicator before the blocking API call.
    # This element renders immediately while the request is in flight.
    st.markdown(
        '<div class="thinking-indicator">'
        '<span class="thinking-dot"></span>'
        '<span class="thinking-dot"></span>'
        '<span class="thinking-dot"></span>'
        '</div>',
        unsafe_allow_html=True,
    )

    try:
        result = send_message(wid, prompt)
    except APIError as e:
        st.session_state.error = str(e)
        st.rerun()
        return

    st.session_state.messages.append(result["user_message"])
    st.session_state.messages.append(result["assistant_message"])
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
