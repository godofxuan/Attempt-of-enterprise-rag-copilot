from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RawProvenance(_StrictModel):
    dataset_name: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    source_file: str = Field(min_length=1)
    source_row: int = Field(ge=1)
    source_native_id: str = Field(min_length=1)
    raw_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EnterpriseSection(_StrictModel):
    heading: str = Field(min_length=1)
    level: int = Field(ge=0, le=12)
    text: str
    ordinal: int = Field(ge=1)


class EnterpriseDocument(_StrictModel):
    document_id: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    source_native_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    sections: list[EnterpriseSection] = Field(default_factory=list)
    author: str | None = None
    participants: list[str] = Field(default_factory=list)
    timestamp: datetime | None = None
    thread_id: str | None = None
    parent_id: str | None = None
    project_id: str | None = None
    status: str | None = None
    version: str | None = None
    freshness: str | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    raw_provenance: RawProvenance

    @model_validator(mode="after")
    def validate_source_identity(self) -> "EnterpriseDocument":
        if self.source_native_id != self.raw_provenance.source_native_id:
            raise ValueError("source native ID must match raw provenance")
        if len(self.participants) != len(set(self.participants)):
            raise ValueError("participants must be unique")
        if self.timestamp is not None and (
            self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None
        ):
            raise ValueError("timestamp must be timezone-aware when present")
        return self


__all__ = ["EnterpriseDocument", "EnterpriseSection", "RawProvenance"]

