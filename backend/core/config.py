"""Application configuration via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Centralized application settings.

    All values are loaded from environment / .env file. Required values
    (e.g. GROQ_API_KEY) will raise on instantiation if missing.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- LLM / Groq ----
    groq_api_key: str = Field(..., description="Groq API key (required)")
    groq_model: str = Field(default="llama-3.3-70b-versatile")
    groq_temperature: float = Field(default=0.2, ge=0.0, le=2.0)

    # ---- Embeddings ----
    embedding_model: str = Field(default="sentence-transformers/all-MiniLM-L6-v2")

    # ---- Storage paths ----
    chroma_persist_dir: Path = Field(default=PROJECT_ROOT / "data" / "chroma")
    sqlite_path: Path = Field(default=PROJECT_ROOT / "data" / "app.db")

    # ---- API / server ----
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_base_url: str = "http://localhost:8000"

    streamlit_port: int = 8501

    log_level: str = "INFO"

    # ---- Ingestion / RAG ----
    chunk_size: int = Field(default=800, ge=100, le=4000)
    chunk_overlap: int = Field(default=200, ge=0, le=1000)
    retrieval_top_k: int = Field(default=5, ge=1, le=20)
    chat_history_window: int = Field(default=10, ge=0, le=50)
    max_context_chars: int = Field(default=12000, ge=1000, le=100000)

    # ---- Derived ----
    @property
    def sqlite_url(self) -> str:
        return f"sqlite:///{self.sqlite_path}"

    @property
    def cors_origins(self) -> list[str]:
        # Streamlit default ports + localhost variations
        return [
            f"http://localhost:{self.streamlit_port}",
            f"http://127.0.0.1:{self.streamlit_port}",
            "http://localhost:3000",
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor."""
    return Settings()  # type: ignore[call-arg]
