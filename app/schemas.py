from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

class HealthResponse(BaseModel):
    status: Literal["ok"]


class LivenessResponse(BaseModel):
    status: Literal["alive"]


class IngestResponse(BaseModel):
    status: str
    document_count: int
    chunk_count: int


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int | None = None


class AgentV2ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)


class SourceItem(BaseModel):
    source: str
    section: str
    chunk_id: str
    preview: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceItem] = []


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_request_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=20_000)
    helpful: bool
    receipt: str = Field(pattern=r"^[0-9a-f]{64}$")


class FeedbackResponse(BaseModel):
    status: Literal["ok"]


class IdentityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    tenant_id: str
    region: str
    groups: list[str]
    roles: list[str]
    issuer: str
    audience: str
    key_id: str
