from functools import lru_cache
import os
from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent
IDENTITY_CLOCK_SKEW_MAX_SECONDS = 120
_IDENTITY_AUDIENCE_PATTERN = re.compile(r"[A-Za-z0-9._:/-]{1,200}")


class Settings(BaseSettings):
    app_name: str = "Enterprise RAG Copilot"

    data_dir: Path = BASE_DIR / "data"
    raw_docs_dir: Path = data_dir / "raw_docs"
    parsed_docs_dir: Path = data_dir / "parsed_docs"
    indexes_dir: Path = data_dir / "indexes"
    v2_indexes_dir: Path = data_dir / "indexes_v2"
    lifecycle_input_root: Path = data_dir / "enterprise_bundle"
    lifecycle_index_root: Path = data_dir / "indexes_lifecycle"
    lifecycle_private_root: Path = (
        BASE_DIR / ".private" / "lifecycle" / "runtime"
    )
    runtime_cache_dir: Path = BASE_DIR / ".private" / "runtime_cache"
    v2_corpus_profile: Literal[
        "demo",
        "benchmark",
        "expanded",
        "expanded_benchmark",
    ] = "expanded"
    v2_chunker_mode: Literal["fixed", "heading", "parent_child"] = "fixed"

    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    chat_model: str = "qwen2.5:3b"
    evidence_model: str = "qwen3:8b"
    embedding_model: str = "bge-m3"

    deployment_release_id: str | None = None
    deployment_expected_index_run_id: str | None = None
    deployment_expected_index_manifest_sha256: str | None = None

    identity_jwks_path: Path = (
        BASE_DIR / ".private" / "identity" / "jwks.json"
    ).resolve()
    identity_feedback_hmac_key_path: Path = (
        BASE_DIR / ".private" / "identity" / "feedback_actor_hmac.key"
    ).resolve()
    identity_issuer: str = "https://identity.localhost/"
    identity_audience: str = "enterprise-rag-api"
    identity_algorithm: Literal["RS256"] = "RS256"
    identity_token_type: Literal["at+jwt"] = "at+jwt"
    identity_operator_role: Literal["rag.operator"] = "rag.operator"
    identity_clock_skew_seconds: int = Field(
        default=30,
        ge=0,
        le=IDENTITY_CLOCK_SKEW_MAX_SECONDS,
    )
    identity_max_token_lifetime_seconds: int = Field(
        default=900,
        ge=60,
        le=3_600,
    )
    identity_max_token_bytes: int = Field(default=8_192, ge=512, le=16_384)
    identity_jwks_max_bytes: int = Field(default=65_536, ge=1_024, le=1_048_576)
    identity_jwks_max_keys: int = Field(default=8, ge=1, le=16)
    identity_feedback_hmac_key_max_bytes: int = Field(
        default=256,
        ge=32,
        le=4_096,
    )

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
    readiness_model_load_timeout_seconds: float = Field(
        default=60.0,
        gt=0,
        le=300,
        description=(
            "Total deadline shared by the complete readiness model probe."
        ),
    )
    readiness_ttl_seconds: float = Field(default=5.0, gt=0, le=300)
    trace_buffer_size: int = Field(default=200, ge=10, le=10_000)
    metrics_latency_buffer_size: int = Field(default=1_000, ge=10, le=100_000)
    sqlite_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    sqlite_path: Path = BASE_DIR / "data" / "app.db"

    @model_validator(mode="after")
    def derive_runtime_paths_from_data_dir(self) -> "Settings":
        if "data_dir" not in self.model_fields_set:
            return self
        derived = {
            "raw_docs_dir": self.data_dir / "raw_docs",
            "parsed_docs_dir": self.data_dir / "parsed_docs",
            "indexes_dir": self.data_dir / "indexes",
            "v2_indexes_dir": self.data_dir / "indexes_v2",
            "lifecycle_input_root": self.data_dir / "enterprise_bundle",
            "lifecycle_index_root": self.data_dir / "indexes_lifecycle",
            "sqlite_path": self.data_dir / "app.db",
        }
        for field_name, value in derived.items():
            if field_name not in self.model_fields_set:
                object.__setattr__(self, field_name, value)
        return self

    @model_validator(mode="after")
    def validate_deployment_binding(self) -> "Settings":
        values = (
            self.deployment_release_id,
            self.deployment_expected_index_run_id,
            self.deployment_expected_index_manifest_sha256,
        )
        if all(value is None for value in values):
            return self
        if any(value is None for value in values):
            raise ValueError(
                "deployment release and expected index binding must be set together"
            )
        assert self.deployment_release_id is not None
        assert self.deployment_expected_index_run_id is not None
        assert self.deployment_expected_index_manifest_sha256 is not None
        identifier_pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
        if (
            not identifier_pattern.fullmatch(self.deployment_release_id)
            or not identifier_pattern.fullmatch(
                self.deployment_expected_index_run_id
            )
            or not re.fullmatch(
                r"[0-9a-f]{64}",
                self.deployment_expected_index_manifest_sha256,
            )
        ):
            raise ValueError("deployment release binding is invalid")
        return self

    @field_validator("identity_issuer")
    @classmethod
    def validate_identity_issuer(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("identity issuer must not contain outer whitespace")
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("identity issuer must be a pinned HTTPS URL")
        return value

    @field_validator("identity_audience")
    @classmethod
    def validate_identity_audience(cls, value: str) -> str:
        if (
            value != value.strip()
            or not value.isascii()
            or not _IDENTITY_AUDIENCE_PATTERN.fullmatch(value)
        ):
            raise ValueError("identity audience must be a bounded ASCII string")
        return value

    @field_validator("identity_jwks_path", "identity_feedback_hmac_key_path")
    @classmethod
    def resolve_identity_private_file_path(cls, value: Path) -> Path:
        candidate = value if value.is_absolute() else BASE_DIR / value
        resolved = Path(os.path.abspath(candidate))
        repository_root = BASE_DIR.resolve()
        private_root = (BASE_DIR / ".private").resolve()
        if resolved.is_relative_to(repository_root) and not resolved.is_relative_to(
            private_root
        ):
            raise ValueError("identity private file path must be under .private")
        return resolved

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
