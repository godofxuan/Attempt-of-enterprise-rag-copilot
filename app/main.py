from fastapi import FastAPI, HTTPException

from app.config import get_settings
from app.db import init_db, save_feedback
from app.retriever import build_indexes
from app.rag_service import answer_question
from app.schemas import (
    ChatRequest,
    ChatResponse,
    FeedbackRequest,
    HealthResponse,
    IngestResponse,
    SourceItem,
)
from app.utils import ensure_dir

app = FastAPI(title="Enterprise RAG Copilot")


@app.on_event("startup")
def startup_event() -> None:
    settings = get_settings()
    ensure_dir(settings.raw_docs_dir)
    ensure_dir(settings.parsed_docs_dir)
    ensure_dir(settings.indexes_dir)
    init_db()


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/ingest", response_model=IngestResponse)
def ingest() -> IngestResponse:
    try:
        doc_count, chunk_count = build_indexes()
        return IngestResponse(
            status="ok",
            document_count=doc_count,
            chunk_count=chunk_count,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    try:
        result = answer_question(payload.question, payload.top_k)
        return ChatResponse(
            answer=result["answer"],
            sources=[SourceItem(**item) for item in result["sources"]],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/feedback")
def feedback(payload: FeedbackRequest):
    try:
        save_feedback(
            question=payload.question,
            answer=payload.answer,
            helpful=payload.helpful,
        )
        return {"status": "ok"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))