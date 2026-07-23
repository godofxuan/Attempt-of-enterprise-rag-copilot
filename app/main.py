from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.agent.runner_v2 import run_agent_v2_chat
from app.api.errors import ApiError, install_error_handlers
from app.api.identity import (
    TrustedIdentityMiddleware,
    authenticated_principal,
    document_bearer_authentication,
)
from app.api.middleware import RequestContextMiddleware
from app.config import get_settings
from app.db import save_feedback_metadata
from app.domain.evidence import AnswerResponse
from app.observability.tracing import RequestTrace, trace_span
from app.runtime.request_context import current_request_id
from app.runtime.resources import ServiceContainer, build_service_container
from app.schemas import (
    AgentV2ChatRequest,
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    IdentityResponse,
    LivenessResponse,
)
from app.security.access import redact_trace_payload
from app.security.identity import IdentityConfigurationError
from app.utils import ensure_dir


def create_app(container: ServiceContainer | None = None) -> FastAPI:
    return _create_application(container)


def _create_application(
    container: ServiceContainer | None,
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
    application.state.service_profile = "secure"
    application.add_middleware(TrustedIdentityMiddleware, container=service)
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

    @application.post(
        "/agent/v2/chat",
        response_model=AnswerResponse,
        dependencies=[Depends(document_bearer_authentication)],
    )
    def agent_v2_chat(
        payload: AgentV2ChatRequest,
        request: Request,
        response: Response,
    ) -> AnswerResponse:
        principal = authenticated_principal(request)
        _require_service_dependencies(service, require_all=True)
        try:
            service.feedback_actor_hasher.ready()
        except IdentityConfigurationError:
            raise _identity_unavailable() from None
        with trace_span("agent.run"):
            answer = run_agent_v2_chat(
                payload.question,
                principal.to_user_context(),
                payload.top_k,
            )
        safe_trace = redact_trace_payload(
            {**answer.trace, "request_id": current_request_id() or "untracked"}
        )
        request_id = current_request_id() or getattr(request.state, "request_id", "")
        try:
            receipt = service.feedback_actor_hasher.issue_feedback_receipt(
                principal,
                target_request_id=request_id,
                question=payload.question,
                answer=answer.answer,
            )
        except (IdentityConfigurationError, ValueError):
            raise _identity_unavailable() from None
        response.headers["X-Feedback-Receipt"] = receipt
        request.state.outcome = answer.mode
        return answer.model_copy(update={"trace": safe_trace})

    @application.post(
        "/feedback",
        response_model=FeedbackResponse,
        dependencies=[Depends(document_bearer_authentication)],
    )
    def feedback(payload: FeedbackRequest, request: Request) -> FeedbackResponse:
        principal = authenticated_principal(request)
        _require_service_dependencies(
            service,
            required_checks={"database", "identity"},
        )
        try:
            if not service.feedback_actor_hasher.verify_feedback_receipt(
                principal,
                target_request_id=payload.target_request_id,
                question=payload.question,
                answer=payload.answer,
                receipt=payload.receipt,
            ):
                raise ApiError(
                    status_code=403,
                    code="invalid_feedback_binding",
                    message="The feedback does not match the referenced answer.",
                )
            actor_pseudonym = service.feedback_actor_hasher.pseudonym(principal)
            question_digest = service.feedback_actor_hasher.content_digest(
                "question",
                payload.question,
            )
            answer_digest = service.feedback_actor_hasher.content_digest(
                "answer",
                payload.answer,
            )
        except IdentityConfigurationError:
            raise _identity_unavailable() from None
        with trace_span("feedback.persist"):
            save_feedback_metadata(
                question_hmac_sha256=question_digest,
                answer_hmac_sha256=answer_digest,
                helpful=payload.helpful,
                request_id=current_request_id() or "untracked",
                target_request_id=payload.target_request_id,
                actor_pseudonym=actor_pseudonym,
                settings=service.settings,
            )
        request.state.outcome = "stored"
        return FeedbackResponse(status="ok")

    @application.get(
        "/identity/me",
        response_model=IdentityResponse,
        dependencies=[Depends(document_bearer_authentication)],
    )
    def identity_me(request: Request) -> IdentityResponse:
        principal = authenticated_principal(request)
        request.state.outcome = "identity_verified"
        return IdentityResponse(
            subject=principal.subject,
            tenant_id=principal.tenant_id,
            region=principal.region,
            groups=list(principal.groups),
            roles=list(principal.roles),
            issuer=principal.issuer,
            audience=principal.audience,
            key_id=principal.key_id,
        )

    @application.get(
        "/observability/metrics",
        dependencies=[Depends(document_bearer_authentication)],
    )
    def metrics(request: Request) -> dict:
        request.state.outcome = "observed"
        return service.metrics.snapshot()

    @application.get(
        "/observability/traces/{request_id}",
        response_model=RequestTrace,
        dependencies=[Depends(document_bearer_authentication)],
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


def _require_service_dependencies(
    service: ServiceContainer,
    *,
    require_all: bool = False,
    required_checks: set[str] | None = None,
) -> None:
    snapshot = service.resources.refresh_if_stale()
    checks = required_checks or set()
    available = (
        snapshot.status == "ready"
        if require_all
        else all(snapshot.checks.get(name) == "ok" for name in checks)
    )
    if not available:
        raise ApiError(
            status_code=503,
            code="service_not_ready",
            message="The service is not ready to process this request.",
            retryable=True,
        )


def _identity_unavailable() -> ApiError:
    return ApiError(
        status_code=503,
        code="identity_unavailable",
        message="The identity service is unavailable.",
        retryable=True,
    )


app = create_app()


__all__ = ["app", "create_app"]
