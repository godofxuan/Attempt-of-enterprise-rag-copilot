from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.queries import UserContext


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
    user_context: UserContext
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

    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=20_000)
    helpful: bool


class FeedbackResponse(BaseModel):
    status: Literal["ok"]
