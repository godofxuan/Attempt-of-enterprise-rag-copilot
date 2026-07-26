from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.errors import ApiError
from app.api.identity import (
    authenticated_principal,
    document_bearer_authentication,
)
from app.lifecycle.operator import (
    LifecycleActivateRequest,
    LifecycleActivationResult,
    LifecycleBuildRequest,
    LifecycleBuildResult,
    LifecycleOperationError,
    LifecyclePreviewRequest,
    LifecyclePreviewResult,
    LifecycleRollbackRequest,
    LifecycleRollbackResult,
    LifecycleStatusResult,
)
from app.observability.tracing import trace_span
from app.runtime.resources import ServiceContainer


def _operator(container: ServiceContainer):
    service = container.lifecycle_operator
    if service is None:
        raise ApiError(
            status_code=503,
            code="lifecycle_service_unavailable",
            message="The lifecycle operator service is unavailable.",
            retryable=True,
        )
    return service


def _safe_api_error(exc: LifecycleOperationError) -> ApiError:
    mapping = {
        "schema": (422, "lifecycle_request_invalid", False),
        "authorization": (403, "lifecycle_scope_forbidden", False),
        "file_validation": (422, "source_validation_failed", False),
        "quarantine": (409, "source_quarantined", False),
        "conflict": (409, "lifecycle_conflict", False),
        "build": (503, "lifecycle_build_failed", True),
        "manifest": (500, "lifecycle_state_invalid", False),
        "activation": (409, "lifecycle_activation_failed", False),
        "rollback": (409, "lifecycle_rollback_failed", False),
    }
    status_code, code, retryable = mapping[exc.category]
    if exc.code == "lifecycle_version_not_found":
        status_code, code, retryable = 404, exc.code, False
    elif exc.code == "active_version_conflict":
        code = exc.code
    elif exc.code == "activation_outcome_unknown":
        status_code, code, retryable = 503, exc.code, True
    return ApiError(
        status_code=status_code,
        code=code,
        message=exc.safe_message,
        retryable=retryable,
    )


def create_lifecycle_router(container: ServiceContainer) -> APIRouter:
    router = APIRouter(
        prefix="/operator/lifecycle",
        dependencies=[Depends(document_bearer_authentication)],
    )

    @router.post("/preview", response_model=LifecyclePreviewResult)
    def preview(
        payload: LifecyclePreviewRequest,
        request: Request,
    ) -> LifecyclePreviewResult:
        principal = authenticated_principal(request)
        try:
            with trace_span("lifecycle.preview"):
                result = _operator(container).preview(payload, principal)
        except LifecycleOperationError as exc:
            raise _safe_api_error(exc) from None
        request.state.outcome = result.plan_kind.casefold()
        return result

    @router.post("/build", response_model=LifecycleBuildResult)
    def build(
        payload: LifecycleBuildRequest,
        request: Request,
    ) -> LifecycleBuildResult:
        principal = authenticated_principal(request)
        try:
            with trace_span("lifecycle.build"):
                result = _operator(container).build(payload, principal)
        except LifecycleOperationError as exc:
            raise _safe_api_error(exc) from None
        request.state.outcome = "activated" if result.activated else "installed"
        return result

    @router.post("/activate", response_model=LifecycleActivationResult)
    def activate(
        payload: LifecycleActivateRequest,
        request: Request,
    ) -> LifecycleActivationResult:
        principal = authenticated_principal(request)
        try:
            with trace_span("lifecycle.activate"):
                result = _operator(container).activate_existing(
                    payload,
                    principal,
                )
        except LifecycleOperationError as exc:
            raise _safe_api_error(exc) from None
        request.state.outcome = "activated"
        return result

    @router.post("/rollback", response_model=LifecycleRollbackResult)
    def rollback(
        payload: LifecycleRollbackRequest,
        request: Request,
    ) -> LifecycleRollbackResult:
        principal = authenticated_principal(request)
        try:
            with trace_span("lifecycle.rollback"):
                result = _operator(container).rollback(payload, principal)
        except LifecycleOperationError as exc:
            raise _safe_api_error(exc) from None
        request.state.outcome = "rolled_back"
        return result

    @router.get("/status", response_model=LifecycleStatusResult)
    def status(request: Request) -> LifecycleStatusResult:
        principal = authenticated_principal(request)
        try:
            with trace_span("lifecycle.status"):
                result = _operator(container).status(principal)
        except LifecycleOperationError as exc:
            raise _safe_api_error(exc) from None
        request.state.outcome = result.state.casefold()
        return result

    return router


__all__ = ["create_lifecycle_router"]
