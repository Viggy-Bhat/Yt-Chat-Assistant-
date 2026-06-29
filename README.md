# YouTube Chat

An AI chat app for YouTube videos. Paste a YouTube URL → the app ingests the video's transcript, indexes it as vector embeddings, and gives you a chat assistant that answers questions grounded in what was actually said. Chat history persists per video, so you can come back to any workspace and pick up where you left off.

**Stack:** Python 3.12 · FastAPI · LangChain (LCEL) · Groq LLM · ChromaDB · SQLite (SQLAlchemy + Alembic) · Streamlit · `sentence-transformers` (local embeddings).

---

## How it works

### 1. User flow
A user opens the Streamlit app, pastes a YouTube URL in the sidebar, and presses Enter. The app creates a **workspace** (one per video) and a background task starts ingesting the transcript. Within ~10–30 seconds the workspace flips from `Indexing` to `Ready` and a chat input appears. The user asks questions; the assistant answers with citations tied to transcript timestamps. The workspace stays in the sidebar forever (until deleted).

### 2. YouTube ingestion pipeline
When a URL is posted to `POST /api/v1/workspaces`:

1. **URL normalization** — the 11-char YouTube video ID is extracted with a regex (handles `watch?v=`, `youtu.be/`, `/embed/`, `/shorts/`, bare IDs). The URL is rewritten to its canonical `https://www.youtube.com/watch?v={id}` form so duplicate detection works.
2. **Metadata fetch** — YouTube's oEmbed endpoint returns title, channel name, and thumbnail without needing an API key. Failures here are non-fatal (the transcript is the real source of truth).
3. **Transcript fetch** — `youtube-transcript-api>=1.0` calls the timedtext endpoint, preferring English captions (manual then auto-generated) and falling back to whatever exists. Returns ~seconds-aligned segments.
4. **Chunking** — segments are joined with a sliding window of ~800 characters and 200-character overlap. Each chunk records `min(start)` and `max(end)` of its contributing segments as its timestamp range.
5. **Embedding** — chunks are batched through a local `sentence-transformers/all-MiniLM-L6-v2` model (384-dim, normalized for cosine similarity). No API call, no quota.
6. **Vector upsert** — chunks + embeddings + metadata are written to a per-workspace Chroma collection. One workspace = one collection, named `ws_{uuid}`.

If the URL was already ingested, the existing workspace is returned (idempotent). If ingestion fails (no captions, private video, network error), the workspace is marked `failed` with the error message preserved.

### 3. Chat pipeline (RAG)
When a message is posted to `POST /api/v1/workspaces/{id}/messages`:

1. **History load** — the last 10 messages for this workspace are pulled from SQLite and converted to LangChain `HumanMessage`/`AIMessage` objects.
2. **Query embedding** — the user's question is embedded with the same sentence-transformer.
3. **Retrieval** — Chroma returns the top-5 chunks by cosine similarity from the workspace's collection. Each carries the timestamp range and a distance score.
4. **Prompt construction (LCEL)** — a `ChatPromptTemplate` is filled with: a system prompt (rules: answer only from transcript, cite timestamps, say "I couldn't find that" when uncertain), the time-stamped context block, the history placeholder, and the current question.
5. **LLM call** — the chain `prompt | ChatGroq(...)` invokes Groq with `llama-3.3-70b-versatile` at temperature 0.2.
6. **Persistence** — both the user message and assistant message are written to SQLite in a single transaction, along with the sources used, token counts, and latency. Returned to the client as a `ChatResponse`.

The assistant's system prompt is strict: it must answer only from the transcript, cite `[mm:ss]` timestamps, and admit when the answer isn't in the context. This is the single biggest determinant of answer quality.

### 4. The two databases

| Store | What it holds | Why |
|---|---|---|
| **SQLite** (`data/app.db`) | `workspaces` (id, url, video_id, title, status, chunk_count, error, timestamps), `messages` (id, workspace_id, role, content, sources JSON, tokens, latency) | Structured, queryable, transactional, persistent metadata. Replaced with Postgres via SQLAlchemy URL when scaling. |
| **ChromaDB** (`data/chroma/`) | Vector embeddings + transcript chunks + `{start, end, chunk_index}` metadata, one collection per workspace | Optimized for similarity search; per-collection isolation makes deletion a single `delete_collection` call. |

This split follows the standard retrieval-augmented pattern: **relational data in a relational store, vectors in a vector store, joined at query time by the workspace ID.**

### 5. The frontend (Streamlit)
The Streamlit app is purely a presentation layer — it makes HTTP calls to the FastAPI backend and never touches the databases directly.

- **Sidebar** lists all workspaces, each with title, status pill (animated pulse while ingesting), and relative timestamp. URL input is wrapped in `st.form` so **Enter submits**. Cards are clickable to open the chat; the ✕ button deletes.
- **Main view** shows the video header (thumbnail + title + channel + status), the chat history, and a `st.chat_input` for new questions.
- **Polling** — when a workspace is in `pending`/`ingesting`, the page reruns every 2s and refetches the workspace until `ready` or `failed`.
- **Sources panel** — each assistant message has an expander listing the retrieved chunks with their `[mm:ss]` timestamps in a monospace font.

The dark theme uses a custom CSS palette (slate-950 backgrounds, indigo/violet accent, emerald success) with Inter and JetBrains Mono fonts — not the default Streamlit look.

### 6. Lifecycle of a workspace

```
[user pastes URL] → POST /workspaces
        ↓
[insert row status=pending]
        ↓
[BackgroundTask fires]
        ↓
[status=ingesting]  ←── polled every 2s by UI
        ↓
[fetch transcript → chunk → embed → upsert to Chroma]
        ↓
[status=ready, chunk_count=N]  ←── user can now chat
        ↓
[each message: persist + RAG + persist reply]
        ↓
[user clicks ✕] → DELETE /workspaces/{id}  →  drop Chroma collection + cascade messages
```

Failed workspaces can be retried by re-submitting the same URL — the route detects `status=failed` and re-runs ingestion.

---

## Architecture

```
┌────────────────────┐   HTTP/JSON   ┌──────────────────────┐
│  Streamlit (UI)    │ ────────────► │   FastAPI backend    │
│  - sidebar         │ ◄──────────── │   - 8 routes v1      │
│  - chat view       │               │   - lifespan warms   │
│  - poll on ingest  │               │     embedder + chroma│
└────────────────────┘               └──────────────────────┘
                                              │
              ┌───────────────────────────────┼───────────────────────────────┐
              ▼                               ▼                               ▼
      ┌──────────────┐               ┌──────────────────┐            ┌──────────────────┐
      │   SQLite     │               │    ChromaDB      │            │  Groq (LLM)      │
      │   ───────    │               │    ──────────    │            │  ────────────    │
      │ workspaces   │               │  ws_{uuid} coll. │            │  llama-3.3-70b   │
      │ messages     │               │  per workspace   │            │  temperature 0.2 │
      │ (FK cascade) │               │  cosine distance │            │                  │
      └──────────────┘               └──────────────────┘            └──────────────────┘
                                                                              ▲
                                                                      ┌───────┴────────┐
                                                                      │ sentence-trans- │
                                                                      │ formers (local) │
                                                                      │ MiniLM-L6-v2    │
                                                                      │ 384-d, cosine   │
                                                                      └────────────────┘
```

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | |
| Web framework | **FastAPI** | Async, auto OpenAPI, Pydantic-native, low ceremony |
| LLM | **Groq** (`llama-3.3-70b-versatile`) | Fast inference, generous free tier |
| Orchestration | **LangChain** (LCEL) | Composable chains, standard RAG patterns, easy to swap LLM/retriever |
| Embeddings | **sentence-transformers** (`all-MiniLM-L6-v2`) | Local, free, 384-dim, no API quota |
| Vector DB | **ChromaDB** | Embedded, persistent, per-collection isolation, no infra |
| Metadata DB | **SQLite** + SQLAlchemy 2.0 + Alembic | File-based MVP, easy Postgres migration later |
| Frontend | **Streamlit** | Per project taste; pure HTTP client, no DB access |
| Migrations | **Alembic** | Schema versioning from day 1 |
| HTTP | **httpx** | Async YouTube calls, sync API client in Streamlit |
| Logging | **loguru** | Single-sink, structured, colorized |
| Config | **pydantic-settings** + `.env` | 12-factor, validated at startup |

---

## Project layout

```
yt-video-anlaysis/
├── alembic/                  # DB migrations
│   ├── env.py
│   └── versions/0001_initial.py
├── backend/
│   ├── main.py               # FastAPI app, lifespan, CORS, router include
│   ├── deps.py               # DI: db session
│   ├── api/
│   │   ├── health.py         # GET /api/v1/health
│   │   └── workspaces.py     # all workspace + message routes
│   ├── core/
│   │   ├── config.py         # pydantic-settings, .env loader
│   │   ├── logging.py        # loguru setup
│   │   └── exceptions.py     # AppError hierarchy + handlers
│   ├── db/
│   │   ├── base.py           # DeclarativeBase
│   │   ├── session.py        # engine, SessionLocal, get_db()
│   │   └── models.py         # Workspace, Message
│   ├── schemas/              # Pydantic v2 request/response
│   │   ├── workspace.py
│   │   └── message.py
│   └── services/
│       ├── youtube.py        # URL parsing, oEmbed, transcript fetch
│       ├── embeddings.py     # sentence-transformers singleton
│       ├── vectorstore.py    # Chroma wrapper, per-workspace collections
│       ├── ingestion.py      # chunk_transcript + run_ingestion pipeline
│       └── rag.py            # LCEL chain, prompt, history loader, JSON sources
├── frontend/
│   └── streamlit_app.py      # single-page app: sidebar + chat
├── tests/                    # 21 tests, all passing
│   ├── conftest.py           # autouse env-isolated temp DB
│   ├── test_youtube_service.py
│   ├── test_ingestion.py
│   ├── test_api.py
│   └── test_e2e.py           # full create→ingest→chat→delete with mocks
├── data/                     # runtime (gitignored)
│   ├── app.db                # SQLite
│   └── chroma/               # ChromaDB
├── requirements.txt
├── alembic.ini
├── .env.example
└── README.md
```

---

## Quick start

```bash
# 1. Install
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS/Linux
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env and set GROQ_API_KEY

# 3. Initialize database
alembic upgrade head

# 4. Run backend (terminal 1)
uvicorn backend.main:app --reload --port 8000

# 5. Run frontend (terminal 2)
streamlit run frontend/streamlit_app.py
```

Open the Streamlit URL (default `http://localhost:8501`). Backend OpenAPI docs live at `http://localhost:8000/docs`.

---

## Database schema

```sql
CREATE TABLE workspaces (
    id            TEXT PRIMARY KEY,           -- UUID4
    youtube_url   TEXT UNIQUE NOT NULL,       -- canonical watch?v= form
    video_id      TEXT NOT NULL,              -- 11-char YouTube ID
    title         TEXT NOT NULL DEFAULT '',
    channel       TEXT,
    duration_s    INTEGER,
    thumbnail     TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending|ingesting|ready|failed
    error         TEXT,                       -- failure reason
    chunk_count   INTEGER NOT NULL DEFAULT 0,
    created_at    DATETIME NOT NULL,
    updated_at    DATETIME NOT NULL
);
CREATE INDEX ix_workspaces_video_id ON workspaces(video_id);
CREATE INDEX ix_workspaces_created_at ON workspaces(created_at);

CREATE TABLE messages (
    id            TEXT PRIMARY KEY,           -- UUID4
    workspace_id  TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    role          TEXT NOT NULL,              -- user|assistant|system
    content       TEXT NOT NULL,
    sources       TEXT,                       -- JSON: [{start, end, text, score}]
    tokens_in     INTEGER,
    tokens_out    INTEGER,
    latency_ms    INTEGER,
    created_at    DATETIME NOT NULL
);
CREATE INDEX ix_messages_workspace_created ON messages(workspace_id, created_at);
```

ChromaDB schema is implicit: one collection per workspace (`ws_{uuid}`) containing transcript chunks with `{start, end, chunk_index}` metadata.

---

## API endpoints (v1)

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/api/v1/health` | Liveness probe |
| `POST` | `/api/v1/workspaces` | Ingest a YouTube URL (idempotent; returns 202) |
| `GET`  | `/api/v1/workspaces` | List workspaces (paginated, recent first) |
| `GET`  | `/api/v1/workspaces/by-url?url=...` | Lookup workspace by URL |
| `GET`  | `/api/v1/workspaces/{id}` | Get workspace detail |
| `DELETE` | `/api/v1/workspaces/{id}` | Delete workspace + Chroma collection + messages |
| `GET`  | `/api/v1/workspaces/{id}/messages` | List messages (chronological) |
| `POST` | `/api/v1/workspaces/{id}/messages` | Send message, get assistant reply with sources |

All errors return JSON: `{"error": {"code": "...", "message": "...", "details": ...}}`.

---

## Configuration

All config in `.env` (see `.env.example`). Knobs:

| Var | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | _required_ | Groq LLM API key |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | LLM model |
| `GROQ_TEMPERATURE` | `0.2` | Lower = more deterministic for grounded answers |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Local HF model |
| `CHUNK_SIZE` | `800` | Transcript chunk char size |
| `CHUNK_OVERLAP` | `200` | Chunk overlap (must be < chunk_size) |
| `RETRIEVAL_TOP_K` | `5` | Top-k chunks for RAG context |
| `CHAT_HISTORY_WINDOW` | `10` | Prior messages kept in LLM context |
| `MAX_CONTEXT_CHARS` | `12000` | Hard cap on context block to fit LLM window |
| `CHROMA_PERSIST_DIR` | `./data/chroma` | Vector store location |
| `SQLITE_PATH` | `./data/app.db` | SQLite location |

---

## Edge cases handled

| Case | Behavior |
|---|---|
| Invalid / non-YouTube URL | 422 (Pydantic `HttpUrl`) |
| Video has no captions | Status `failed`, error preserved |
| Private / region-locked / age-restricted | oEmbed 401/403/404 → friendly error |
| Same URL submitted twice | Returns existing workspace (idempotent) |
| Failed workspace re-submitted | Status reset to `pending`, re-ingest runs |
| Empty / whitespace message | 422 (Pydantic min_length) |
| Workspace not ready when messaging | 409 Conflict with helpful message |
| Groq rate-limit / 5xx | 503 via custom exception handler |
| `GROQ_API_KEY` missing | Fail-fast at app startup, not first request |
| Embedding model not yet cached | Pre-warmed in lifespan; first request doesn't pay cold-start |
| Concurrent ingest of same URL | DB UNIQUE constraint + IntegrityError catch → return winner |
| Very long videos | Sliding-window chunker + `MAX_CONTEXT_CHARS` cap |
| Large chat history | Sliding window of last 10 messages sent to LLM; full history in DB |

---

## Testing

```bash
pytest -v
```

21 tests, all passing:
- 12 URL parsing edge cases
- 4 transcript chunker scenarios
- 4 API smoke tests (health, validation, 404s, list)
- 1 full E2E (create → ingest → chat → list → delete) with YouTube and Groq mocked

The autouse `temp_env` fixture in `conftest.py` gives every test a throwaway SQLite + Chroma dir, so tests never touch real state.

---

## Evaluation (LangSmith)

The project includes automated, reference-free evaluation using LangSmith. The evaluation pipeline generates questions from real transcript chunks, runs the actual RAG chain against them, and scores the outputs without requiring hand-written ground-truth answers.

### Prerequisites

Set `LANGSMITH_API_KEY` in your `.env` file (or export as an environment variable). The key is available from [smith.langchain.com](https://smith.langchain.com).

### Step 1 — Generate a dataset (one-time per video)

```bash
python -m evals.generate_dataset --workspace-id <workspace-uuid>
```

This loads the Chroma chunks for an already-ingested workspace, uses Groq to write one question per chunk (sampled evenly across the video), and uploads the question/range pairs to a LangSmith dataset named `yt-chat-eval-{workspace_id}`. It also adds a small number of negative (off-topic) examples.

Options:

| Flag | Default | Description |
|---|---|---|
| `--workspace-id` | _required_ | UUID of an ingested workspace |
| `--max-examples` | 20 | Max positive examples (sampled evenly) |
| `--max-negative` | 5 | Number of negative/off-topic examples |

After generation, quickly skim the auto-generated questions in the LangSmith UI dataset view (~2–3 min) to sanity-check none are nonsensical before trusting eval scores.

### Step 2 — Run an evaluation experiment (repeatable)

```bash
python -m evals.run_eval --workspace-id <workspace-uuid> --experiment-name "baseline-chunk800"
```

This loads the dataset, runs the real RAG chain (`backend/services/rag.py`'s `build_chain` + `VectorStoreService`) against each question, and applies two reference-free evaluators:

| Evaluator | What it measures | Method |
|---|---|---|
| `faithfulness` | Is the answer grounded in the retrieved sources? | LLM-as-judge (YES/NO). For negative examples, checks correct refusal. |
| `retrieval_recall` | Did retrieval find a chunk overlapping the expected timestamp? | Compares `[start, end]` of retrieved chunks vs. the expected range. |

Results are uploaded to LangSmith under the project configured in `LANGSMITH_PROJECT` (default: `yt-chat-eval`). A summary is also printed to stdout.

Options:

| Flag | Default | Description |
|---|---|---|
| `--workspace-id` | _required_ | UUID of the ingested workspace |
| `--experiment-name` | `eval-{timestamp}` | Label for this experiment |

### Suggested workflow

1. Ingest a test video (paste a YouTube URL in the frontend).
2. Generate a dataset: `python -m evals.generate_dataset --workspace-id <id>`
3. Run a baseline eval: `python -m evals.run_eval --workspace-id <id> --experiment-name "baseline"`
4. Change one variable (chunk size, `RETRIEVAL_TOP_K`, system prompt wording, etc.).
5. Re-run eval with a new experiment name: `python -m evals.run_eval --workspace-id <id> --experiment-name "chunk-1200"`
6. Compare both experiments side-by-side in the LangSmith UI.

### Design notes

- The dataset is generated from the same Chroma chunks the RAG pipeline uses at inference time — no separate gold corpus to maintain.
- `expected_timestamp_range` comes from each chunk's `[start, end]` metadata, so ground truth is free and always in sync with the actual transcript.
- Reference-free evaluators mean you never write a "correct answer" by hand.
- Generation and evaluation are separate steps so the same dataset can be reused across many experiments when comparing chunk size, `top_k`, or prompt changes.
- The eval tests the *real* production chain (`build_chain` + `VectorStoreService`), not a reimplementation — if something changes in the app, eval moves with it.

---

## License

MIT
