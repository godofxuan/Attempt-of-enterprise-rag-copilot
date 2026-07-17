from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.agent.runner import run_agent_chat
from app.agent.runner_v2 import run_agent_v2_chat
from app.agent.schemas import AgentChatResponse
from app.api.errors import ApiError, install_error_handlers
from app.api.middleware import RequestContextMiddleware
from app.config import get_settings
from app.db import save_feedback_metadata
from app.domain.evidence import AnswerResponse
from app.observability.tracing import RequestTrace, trace_span
from app.rag_service import answer_question
from app.retriever import build_indexes
from app.runtime.request_context import current_request_id
from app.runtime.resources import ServiceContainer, build_service_container
from app.schemas import (
    AgentV2ChatRequest,
    ChatRequest,
    ChatResponse,
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    IngestResponse,
    LivenessResponse,
    SourceItem,
)
from app.security.access import redact_trace_payload
from app.utils import ensure_dir


def create_app(container: ServiceContainer | None = None) -> FastAPI:
    return _create_application(container, compatibility=False)


def create_compatibility_app(
    container: ServiceContainer | None = None,
) -> FastAPI:
    return _create_application(container, compatibility=True)


def _create_application(
    container: ServiceContainer | None,
    *,
    compatibility: bool,
) -> FastAPI:
    service = container or build_service_container(get_settings())

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        settings = service.settings
        for path in (
            settings.raw_docs_dir,
            settings.parsed_docs_dir,
            settings.indexes_dir,
            settings.v2_indexes_dir,
        ):
            ensure_dir(path)
        service.resources.start()
        try:
            yield
        finally:
            service.resources.close()

    application = FastAPI(
        title=service.settings.app_name,
        lifespan=lifespan,
    )
    application.state.service_container = service
    application.state.service_profile = (
        "local_compatibility" if compatibility else "secure"
    )
    application.add_middleware(RequestContextMiddleware, container=service)
    install_error_handlers(application)

    @application.get("/health/live", response_model=LivenessResponse)
    def liveness(request: Request) -> LivenessResponse:
        request.state.outcome = "alive"
        return LivenessResponse(status="alive")

    @application.get("/health", response_model=HealthResponse)
    def health_compatibility(request: Request) -> JSONResponse:
        request.state.outcome = "ok"
        return JSONResponse(
            content=HealthResponse(status="ok").model_dump(mode="json"),
            headers={"Deprecation": "true"},
        )

    @application.get("/health/ready")
    def readiness(request: Request) -> JSONResponse:
        snapshot = service.resources.refresh_if_stale()
        request.state.outcome = snapshot.status
        return JSONResponse(
            status_code=200 if snapshot.status == "ready" else 503,
            content=snapshot.model_dump(mode="json"),
        )

    if compatibility:
        @application.post("/ingest", response_model=IngestResponse)
        def ingest(request: Request) -> IngestResponse:
            document_count, chunk_count = build_indexes()
            request.state.outcome = "indexed"
            return IngestResponse(
                status="ok",
                document_count=document_count,
                chunk_count=chunk_count,
            )

        @application.post("/chat", response_model=ChatResponse)
        def chat(payload: ChatRequest, request: Request) -> ChatResponse:
            result = answer_question(payload.question, payload.top_k)
            request.state.outcome = "answered"
            return ChatResponse(
                answer=result["answer"],
                sources=[SourceItem(**item) for item in result["sources"]],
            )

        @application.post("/agent/chat", response_model=AgentChatResponse)
        def agent_chat(
            payload: ChatRequest,
            request: Request,
        ) -> AgentChatResponse:
            response = run_agent_chat(payload.question, payload.top_k)
            request.state.outcome = response.trace.final_outcome or "completed"
            return response

    @application.post("/agent/v2/chat", response_model=AnswerResponse)
    def agent_v2_chat(payload: AgentV2ChatRequest, request: Request) -> AnswerResponse:
        with trace_span("agent.run"):
            response = run_agent_v2_chat(
                payload.question,
                payload.user_context,
                payload.top_k,
            )
        safe_trace = redact_trace_payload(
            {**response.trace, "request_id": current_request_id() or "untracked"}
        )
        request.state.outcome = response.mode
        return response.model_copy(update={"trace": safe_trace})

    @application.post("/feedback", response_model=FeedbackResponse)
    def feedback(payload: FeedbackRequest, request: Request) -> FeedbackResponse:
        with trace_span("feedback.persist"):
            save_feedback_metadata(
                question=payload.question,
                answer=payload.answer,
                helpful=payload.helpful,
                request_id=current_request_id() or "untracked",
            )
        request.state.outcome = "stored"
        return FeedbackResponse(status="ok")

    @application.get("/observability/metrics")
    def metrics(request: Request) -> dict:
        request.state.outcome = "observed"
        return service.metrics.snapshot()

    @application.get(
        "/observability/traces/{request_id}",
        response_model=RequestTrace,
    )
    def trace(request_id: str, request: Request) -> RequestTrace:
        record = service.traces.get(request_id)
        if record is None:
            raise ApiError(
                status_code=404,
                code="trace_not_found",
                message="The requested trace was not found.",
            )
        request.state.outcome = "observed"
        return record

    return application


app = create_app()


__all__ = ["app", "create_app", "create_compatibility_app"]
