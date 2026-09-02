from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parents[2]


class RetrievalCanarySettings(BaseSettings):
    profile: Literal[
        "default",
        "finance_known_report_page_fusion_v1",
    ] = "default"
    canary_policy_ids: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_activation_boundary(self) -> RetrievalCanarySettings:
        if len(self.canary_policy_ids) != len(set(self.canary_policy_ids)) or any(
            not value.strip() for value in self.canary_policy_ids
        ):
            raise ValueError("retrieval canary policy IDs must be unique and non-empty")
        if self.profile == "finance_known_report_page_fusion_v1" and not (self.canary_policy_ids):
            raise ValueError("finance retrieval canary requires an explicit policy allowlist")
        if self.profile == "default" and self.canary_policy_ids:
            raise ValueError("default retrieval cannot carry a stale canary allowlist")
        return self

    model_config = SettingsConfigDict(
        env_prefix="RETRIEVAL_",
        env_file=_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_retrieval_canary_settings() -> RetrievalCanarySettings:
    return RetrievalCanarySettings()


__all__ = ["RetrievalCanarySettings", "get_retrieval_canary_settings"]
