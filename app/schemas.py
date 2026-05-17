from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str


class IngestResponse(BaseModel):
    status: str
    document_count: int
    chunk_count: int


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int | None = None


class SourceItem(BaseModel):
    source: str
    section: str
    chunk_id: str
    preview: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceItem] = []


class FeedbackRequest(BaseModel):
    question: str
    answer: str
    helpful: bool