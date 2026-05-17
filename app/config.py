from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    app_name: str = "Enterprise RAG Copilot"

    data_dir: Path = BASE_DIR / "data"
    raw_docs_dir: Path = data_dir / "raw_docs"
    parsed_docs_dir: Path = data_dir / "parsed_docs"
    indexes_dir: Path = data_dir / "indexes"

    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    chat_model: str = "qwen2.5:3b"
    embedding_model: str = "bge-m3"

    chunk_size: int = 500
    chunk_overlap: int = 80
    retrieval_top_k: int = 5
    retrieval_candidate_k: int = 8

    sqlite_path: Path = BASE_DIR / "data" / "app.db"

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()