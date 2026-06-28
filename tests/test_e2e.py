"""End-to-end smoke test: ingest a workspace, send a message, get a reply.

Externals (YouTube, Groq, Chroma) are mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


def test_e2e_ingest_and_chat():
    # Mock YouTube metadata + transcript
    from backend.services.youtube import TranscriptSegment
    fake_meta = MagicMock(title="Test Video", channel="Test Channel", thumbnail="http://example.com/t.jpg")
    fake_segments = [
        TranscriptSegment(text="Hello world this is a test transcript", start=0.0, duration=5.0),
        TranscriptSegment(text="The second sentence covers more ground", start=5.0, duration=5.0),
        TranscriptSegment(text="And the third segment wraps up the discussion", start=10.0, duration=5.0),
    ]

    with patch("backend.services.youtube.fetch_video_metadata", new=AsyncMock(return_value=fake_meta)), \
         patch("backend.services.youtube.fetch_transcript", return_value=fake_segments), \
         patch("backend.services.rag.build_chain") as mock_build_chain:

        # The chain's .invoke(input_dict) is called. Build a mock that returns
        # a LangChain-style AIMessage.
        from langchain_core.messages import AIMessage
        mock_chain = MagicMock()
        mock_chain.invoke.return_value = AIMessage(
            content="This is a mock answer about the video.",
            response_metadata={"token_usage": {"prompt_tokens": 100, "completion_tokens": 20}},
        )
        mock_build_chain.return_value = mock_chain

        from backend.main import create_app
        app = create_app()
        with TestClient(app) as client:
            # 1. Create workspace
            r = client.post(
                "/api/v1/workspaces",
                json={"youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
            assert r.status_code == 202, r.text
            ws = r.json()
            ws_id = ws["id"]
            assert ws["status"] in ("pending", "ingesting", "ready")
            assert ws["video_id"] == "dQw4w9WgXcQ"

            # 2. Wait for ingestion to complete (poll briefly)
            for _ in range(60):
                r = client.get(f"/api/v1/workspaces/{ws_id}")
                assert r.status_code == 200
                if r.json()["status"] == "ready":
                    break
                if r.json()["status"] == "failed":
                    pytest.fail(f"Ingestion failed: {r.json().get('error')}")
                import time
                time.sleep(0.5)
            else:
                pytest.fail("Ingestion did not complete in time")

            # 3. List workspaces
            r = client.get("/api/v1/workspaces")
            assert r.status_code == 200
            assert r.json()["total"] >= 1

            # 4. Lookup by URL (idempotency)
            r = client.get(
                "/api/v1/workspaces/by-url",
                params={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
            assert r.status_code == 200
            assert r.json()["id"] == ws_id

            # 5. Send a message
            r = client.post(
                f"/api/v1/workspaces/{ws_id}/messages",
                json={"content": "What is this video about?"},
            )
            assert r.status_code == 200, r.text
            chat = r.json()
            assert "user_message" in chat
            assert "assistant_message" in chat
            assert chat["user_message"]["role"] == "user"
            assert chat["assistant_message"]["role"] == "assistant"
            assert "mock answer" in chat["assistant_message"]["content"]

            # 6. List messages
            r = client.get(f"/api/v1/workspaces/{ws_id}/messages")
            assert r.status_code == 200
            msgs = r.json()["items"]
            assert len(msgs) == 2  # user + assistant

            # 7. Delete
            r = client.delete(f"/api/v1/workspaces/{ws_id}")
            assert r.status_code == 204

            r = client.get(f"/api/v1/workspaces/{ws_id}")
            assert r.status_code == 404
