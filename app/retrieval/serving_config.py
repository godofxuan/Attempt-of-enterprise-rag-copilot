from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import BASE_DIR


class ServingRetrievalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="V2_", extra="ignore")
    retrieval_profile: Literal[
        "hybrid_default", "dense_reference", "safe_dense_raw20_bge", "safe_dense_raw50_bge"
    ] = "hybrid_default"
    reranker_path: Path = BASE_DIR / ".private" / "reranker_models" / "BAAI--bge-reranker-v2-m3"
    reranker_device: Literal["cpu", "cuda"] = "cpu"
