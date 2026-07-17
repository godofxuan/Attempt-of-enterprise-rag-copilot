from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    app_name: str = "Enterprise RAG Copilot"

    data_dir: Path = BASE_DIR / "data"
    raw_docs_dir: Path = data_dir / "raw_docs"
    parsed_docs_dir: Path = data_dir / "parsed_docs"
    indexes_dir: Path = data_dir / "indexes"
    v2_indexes_dir: Path = data_dir / "indexes_v2"
    v2_corpus_profile: Literal["demo", "benchmark"] = "demo"
    v2_chunker_mode: Literal["fixed", "heading", "parent_child"] = "fixed"

    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    chat_model: str = "qwen2.5:3b"
    evidence_model: str = "qwen3:8b"
    embedding_model: str = "bge-m3"

    chunk_size: int = 500
    chunk_overlap: int = 80
    retrieval_top_k: int = 5
    retrieval_candidate_k: int = 8

    agent_v2_max_search_calls: int = Field(default=3, ge=1, le=10)
    agent_v2_max_find_calls: int = Field(default=2, ge=1, le=10)
    agent_v2_max_open_calls: int = Field(default=4, ge=1, le=20)
    agent_v2_max_steps: int = Field(default=12, ge=1, le=50)
    agent_v2_max_context_chars: int = Field(default=12_000, ge=100, le=100_000)
    agent_v2_deadline_ms: int = Field(default=15_000, ge=100, le=300_000)

    api_request_deadline_ms: int = Field(default=15_000, ge=100, le=300_000)
    model_request_timeout_seconds: float = Field(default=12.0, gt=0, le=300)
    model_max_attempts: int = Field(default=2, ge=1, le=3)
    model_retry_backoff_ms: int = Field(default=100, ge=0, le=10_000)
    structured_generation_max_attempts: int = Field(default=2, ge=1, le=2)
    readiness_probe_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    readiness_ttl_seconds: float = Field(default=5.0, gt=0, le=300)
    trace_buffer_size: int = Field(default=200, ge=10, le=10_000)
    metrics_latency_buffer_size: int = Field(default=1_000, ge=10, le=100_000)
    sqlite_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    sqlite_path: Path = BASE_DIR / "data" / "app.db"

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
