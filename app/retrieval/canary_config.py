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
    finance_known_report_page_fusion_enabled: bool = True
    finance_known_report_policy_ids: list[str] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def validate_activation_boundary(self) -> RetrievalCanarySettings:
        for label, values in (
            ("retrieval canary", self.canary_policy_ids),
            ("finance known-report", self.finance_known_report_policy_ids),
        ):
            if len(values) != len(set(values)) or any(not value.strip() for value in values):
                raise ValueError(f"{label} policy IDs must be unique and non-empty")
        if self.canary_policy_ids and self.finance_known_report_policy_ids:
            raise ValueError("legacy canary and promoted finance policy lists cannot both be set")
        if self.profile == "finance_known_report_page_fusion_v1" and not (self.canary_policy_ids):
            raise ValueError("finance retrieval canary requires an explicit policy allowlist")
        if self.profile == "default" and self.canary_policy_ids:
            raise ValueError("default retrieval cannot carry a stale canary allowlist")
        return self

    @property
    def page_fusion_policy_ids(self) -> list[str]:
        if not self.finance_known_report_page_fusion_enabled:
            return []
        if self.finance_known_report_policy_ids:
            return self.finance_known_report_policy_ids
        if self.profile == "finance_known_report_page_fusion_v1":
            return self.canary_policy_ids
        return []

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
