from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import BASE_DIR, Settings
from app.domain.evidence import AnswerResponse
from app.main import create_app
from app.observability.metrics import MetricsRegistry
from app.observability.tracing import InMemoryTraceStore
from app.runtime.resources import (
    DEFAULT_ROUTE_TEMPLATES,
    ReadinessSnapshot,
    ReadyIndexInfo,
    ServiceContainer,
)
from app.security.demo_identity import initialize_demo_identity
from app.security.identity import (
    FeedbackActorPseudonymizer,
    IdentityVerifier,
    Principal,
    UnavailableIdentityVerifier,
    build_feedback_actor_hasher,
    build_identity_verifier,
)
from app.security.token_source import BearerTokenFileSource


EXPECTED_MATRIX_SHA256 = "fe5fdddd9cd4d067930b971ca0658a22deb63778723c31597df7f7fab70b4e2f"
TRUSTED_IDENTITY_SOURCE_FILES = (
    "app/api/identity.py",
    "app/db.py",
    "app/evaluation/trusted_identity.py",
    "app/main.py",
    "app/runtime/resources.py",
    "app/schemas.py",
    "app/security/demo_identity.py",
    "app/security/identity.py",
    "app/security/token_source.py",
    "scripts/eval_trusted_identity.py",
)
_FEEDBACK_TARGET_REQUEST_ID = "identity-eval-answer"
_FEEDBACK_QUESTION = "What is the policy?"
_FEEDBACK_ANSWER = "No visible evidence."


class TrustedIdentityCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,99}$")
    method: Literal["GET", "POST"]
    path: str = Field(min_length=1, max_length=200, pattern=r"^/")
    credential: Literal[
        "none",
        "user",
        "operator",
        "invalid",
        "duplicate",
        "unavailable",
    ]
    body_kind: Literal[
        "none",
        "chat_valid",
        "chat_identity_override",
        "chat_invalid_top_k",
        "chat_invalid_and_override",
        "feedback_valid",
        "feedback_missing_receipt",
        "feedback_tampered_receipt",
        "feedback_modified_answer",
    ]
    expected_status: int = Field(ge=200, le=599)
    expected_code: str | None = Field(default=None, max_length=100)
    expected_agent_calls: int = Field(ge=0, le=1)
    expected_feedback_writes: int = Field(ge=0, le=1)


class TrustedIdentityMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["trusted-identity-matrix-v1"]
    matrix_id: Literal["r2-s5-trusted-identity-api-v1"]
    cases: list[TrustedIdentityCase] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_case_ids(self) -> TrustedIdentityMatrix:
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("trusted identity case IDs must be unique")
        return self


class TrustedIdentityCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    expected_status: int
    observed_status: int
    expected_code: str | None
    observed_code: str | None
    agent_calls: int
    feedback_writes: int
    identity_context_match: bool | None
    chat_receipt_match: bool | None
    feedback_binding_match: bool | None
    feedback_privacy_match: bool | None
    credential_leak: bool
    passed: bool


class TrustedIdentityEvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["trusted-identity-evaluation-v2"]
    evaluation_contract_id: str = Field(
        pattern=r"^trusted-identity-contract-[0-9a-f]{16}$"
    )
    matrix_id: str
    matrix_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_sha256: dict[str, str]
    total_cases: int
    passed_cases: int
    failed_cases: int
    denied_cases: int
    denied_side_effect_violations: int
    credential_leaks: int
    release_pass: bool
    cases: list[TrustedIdentityCaseResult]

    @model_validator(mode="after")
    def validate_provenance(self) -> TrustedIdentityEvaluationResult:
        if set(self.source_sha256) != set(TRUSTED_IDENTITY_SOURCE_FILES) or any(
            len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            for digest in self.source_sha256.values()
        ):
            raise ValueError("trusted identity source provenance is invalid")
        expected = _evaluation_contract_id(
            self.matrix_sha256,
            self.source_sha256,
        )
        if self.evaluation_contract_id != expected:
            raise ValueError("trusted identity contract ID is invalid")
        return self


class _ReadyResources:
    def __init__(self) -> None:
        self.snapshot = ReadinessSnapshot(
            status="ready",
            checks={
                "database": "ok",
                "index": "ok",
                "models": "ok",
                "identity": "ok",
            },
            retrieved_guard="ready",
            index=ReadyIndexInfo(
                run_id="identity-eval-index",
                chunk_count=1,
                embedding_model="offline",
                embedding_dimension=1,
                build_duration_ms=0,
                index_size_bytes=0,
            ),
            checked_at_utc="2026-07-22T00:00:00Z",
        )

    def start(self) -> ReadinessSnapshot:
        return self.snapshot

    def refresh_if_stale(self) -> ReadinessSnapshot:
        return self.snapshot

    def close(self) -> None:
        return None


def load_trusted_identity_matrix(path: Path) -> tuple[TrustedIdentityMatrix, str]:
    source = Path(path)
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_MATRIX_SHA256:
        raise ValueError("trusted identity matrix hash mismatch")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ValueError("trusted identity matrix is invalid") from None
    return TrustedIdentityMatrix.model_validate(payload), digest


def evaluate_trusted_identity(path: Path) -> TrustedIdentityEvaluationResult:
    matrix, digest = load_trusted_identity_matrix(path)
    source_sha256 = {
        relative: hashlib.sha256((BASE_DIR / relative).read_bytes()).hexdigest()
        for relative in TRUSTED_IDENTITY_SOURCE_FILES
    }
    with TemporaryDirectory(prefix="r2-s5-identity-eval-") as temporary:
        root = Path(temporary)
        initialize_demo_identity(
            root,
            issuer="https://identity.localhost/",
            audience="enterprise-rag-api",
            token_lifetime_seconds=900,
        )
        settings = Settings(
            _env_file=None,
            identity_jwks_path=root / "jwks.json",
            identity_feedback_hmac_key_path=root / "feedback_actor_hmac.key",
            trace_buffer_size=100,
            metrics_latency_buffer_size=100,
        )
        user_token = BearerTokenFileSource(root / "load_user_token.txt").get_token()
        operator_token = BearerTokenFileSource(root / "operator_token.txt").get_token()
        hmac_key = (root / "feedback_actor_hmac.key").read_bytes()
        results = [
            _evaluate_case(
                case,
                settings=settings,
                user_token=user_token,
                operator_token=operator_token,
                hmac_key=hmac_key,
            )
            for case in matrix.cases
        ]

    denied = [item for item in results if item.observed_status >= 400]
    side_effect_violations = sum(
        item.agent_calls != 0 or item.feedback_writes != 0 for item in denied
    )
    passed = sum(item.passed for item in results)
    leaks = sum(item.credential_leak for item in results)
    return TrustedIdentityEvaluationResult(
        schema_version="trusted-identity-evaluation-v2",
        evaluation_contract_id=_evaluation_contract_id(digest, source_sha256),
        matrix_id=matrix.matrix_id,
        matrix_sha256=digest,
        source_sha256=source_sha256,
        total_cases=len(results),
        passed_cases=passed,
        failed_cases=len(results) - passed,
        denied_cases=len(denied),
        denied_side_effect_violations=side_effect_violations,
        credential_leaks=leaks,
        release_pass=(
            passed == len(results)
            and side_effect_violations == 0
            and leaks == 0
        ),
        cases=results,
    )


def _evaluation_contract_id(
    matrix_sha256: str,
    source_sha256: dict[str, str],
) -> str:
    material = json.dumps(
        {
            "matrix_sha256": matrix_sha256,
            "source_sha256": {
                relative: source_sha256[relative]
                for relative in sorted(source_sha256)
            },
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return "trusted-identity-contract-" + hashlib.sha256(material).hexdigest()[:16]


def _evaluate_case(
    case: TrustedIdentityCase,
    *,
    settings: Settings,
    user_token: str,
    operator_token: str,
    hmac_key: bytes,
) -> TrustedIdentityCaseResult:
    counters = {"agent": 0, "feedback": 0}
    observed_context: dict[str, Any] = {}
    feedback_calls: list[dict[str, Any]] = []

    def fake_run(question, user, top_k=None):
        counters["agent"] += 1
        observed_context.update(user.model_dump(mode="json"))
        return AnswerResponse(
            mode="not_found",
            answer="No visible evidence.",
            stop_reason="not_found",
            trace={"intent": "fact", "steps": [], "budget": {}},
        )

    def fake_feedback(**kwargs) -> None:
        counters["feedback"] += 1
        feedback_calls.append(dict(kwargs))

    trusted_verifier = build_identity_verifier(settings)
    verifier: IdentityVerifier = (
        UnavailableIdentityVerifier()
        if case.credential == "unavailable"
        else trusted_verifier
    )
    feedback_hasher = build_feedback_actor_hasher(settings)
    signing_principal = _signing_principal(
        case,
        verifier=trusted_verifier,
        user_token=user_token,
        operator_token=operator_token,
    )
    feedback_receipt = feedback_hasher.issue_feedback_receipt(
        signing_principal,
        target_request_id=_FEEDBACK_TARGET_REQUEST_ID,
        question=_FEEDBACK_QUESTION,
        answer=_FEEDBACK_ANSWER,
    )
    container = ServiceContainer(
        settings=settings,
        resources=_ReadyResources(),
        metrics=MetricsRegistry(
            latency_buffer_size=100,
            allowed_routes=DEFAULT_ROUTE_TEMPLATES,
            memory_provider=lambda: 0,
        ),
        traces=InMemoryTraceStore(max_records=100),
        identity_verifier=verifier,
        feedback_actor_hasher=feedback_hasher,
    )
    headers = _headers(case, user_token=user_token, operator_token=operator_token)
    request_id = f"identity-eval-{case.case_id}"
    if isinstance(headers, dict):
        headers = {**headers, "X-Request-ID": request_id}
    else:
        headers = [("X-Request-ID", request_id), *headers]

    with patch("app.main.run_agent_v2_chat", fake_run), patch(
        "app.main.save_feedback_metadata", fake_feedback
    ), TestClient(create_app(container)) as client:
        response = client.request(
            case.method,
            case.path,
            headers=headers,
            json=_body(case.body_kind, feedback_receipt=feedback_receipt),
        )

    observed_code = _error_code(response)
    credential_leak = _contains_credential_leak(
        response,
        case=case,
        user_token=user_token,
        operator_token=operator_token,
        hmac_key=hmac_key,
    )
    identity_match: bool | None = None
    chat_receipt_match: bool | None = None
    if case.expected_agent_calls:
        identity_match = observed_context == {
            "user_id": "load-demo-employee",
            "tenant_id": "starbridge-cn",
            "region": "cn",
            "groups": ["all_employees"],
            "roles": [],
        }
        receipt = response.headers.get("X-Feedback-Receipt")
        chat_receipt_match = (
            isinstance(receipt, str)
            and feedback_hasher.verify_feedback_receipt(
                signing_principal,
                target_request_id=request_id,
                question="What is the policy?",
                answer=_FEEDBACK_ANSWER,
                receipt=receipt,
            )
        )
    feedback_binding_match: bool | None = None
    feedback_privacy_match: bool | None = None
    if case.expected_feedback_writes:
        feedback_binding_match, feedback_privacy_match = (
            _evaluate_feedback_write(
                feedback_calls,
                settings=settings,
                feedback_hasher=feedback_hasher,
                principal=signing_principal,
            )
        )
    passed = (
        response.status_code == case.expected_status
        and observed_code == case.expected_code
        and counters["agent"] == case.expected_agent_calls
        and counters["feedback"] == case.expected_feedback_writes
        and not credential_leak
        and identity_match is not False
        and chat_receipt_match is not False
        and feedback_binding_match is not False
        and feedback_privacy_match is not False
    )
    return TrustedIdentityCaseResult(
        case_id=case.case_id,
        expected_status=case.expected_status,
        observed_status=response.status_code,
        expected_code=case.expected_code,
        observed_code=observed_code,
        agent_calls=counters["agent"],
        feedback_writes=counters["feedback"],
        identity_context_match=identity_match,
        chat_receipt_match=chat_receipt_match,
        feedback_binding_match=feedback_binding_match,
        feedback_privacy_match=feedback_privacy_match,
        credential_leak=credential_leak,
        passed=passed,
    )


def _headers(
    case: TrustedIdentityCase,
    *,
    user_token: str,
    operator_token: str,
) -> dict[str, str] | list[tuple[str, str]]:
    if case.credential == "none":
        return {}
    if case.credential in {"user", "unavailable"}:
        return {"Authorization": f"Bearer {user_token}"}
    if case.credential == "operator":
        return {"Authorization": f"Bearer {operator_token}"}
    if case.credential == "invalid":
        return {"Authorization": "Bearer attacker-token"}
    return [
        ("Authorization", f"Bearer {user_token}"),
        ("Authorization", f"Bearer {operator_token}"),
    ]


def _body(
    kind: str,
    *,
    feedback_receipt: str,
) -> dict[str, Any] | None:
    if kind == "none":
        return None
    if kind == "chat_valid":
        return {"question": "What is the policy?", "top_k": 3}
    if kind == "chat_identity_override":
        return {
            "question": "What is the policy?",
            "user_context": {
                "user_id": "admin",
                "tenant_id": "other",
                "region": "global",
                "groups": ["admin"],
                "roles": ["rag.operator"],
            },
        }
    if kind == "chat_invalid_top_k":
        return {"question": "What is the policy?", "top_k": 0}
    if kind == "chat_invalid_and_override":
        return {"question": "", "user_context": {"roles": ["rag.operator"]}}
    if kind == "feedback_valid":
        return {
            "target_request_id": _FEEDBACK_TARGET_REQUEST_ID,
            "question": _FEEDBACK_QUESTION,
            "answer": _FEEDBACK_ANSWER,
            "helpful": True,
            "receipt": feedback_receipt,
        }
    if kind == "feedback_missing_receipt":
        return {
            "target_request_id": _FEEDBACK_TARGET_REQUEST_ID,
            "question": _FEEDBACK_QUESTION,
            "answer": _FEEDBACK_ANSWER,
            "helpful": True,
        }
    if kind == "feedback_tampered_receipt":
        replacement = "0" if feedback_receipt[0] != "0" else "1"
        return {
            "target_request_id": _FEEDBACK_TARGET_REQUEST_ID,
            "question": _FEEDBACK_QUESTION,
            "answer": _FEEDBACK_ANSWER,
            "helpful": True,
            "receipt": f"{replacement}{feedback_receipt[1:]}",
        }
    if kind == "feedback_modified_answer":
        return {
            "target_request_id": _FEEDBACK_TARGET_REQUEST_ID,
            "question": _FEEDBACK_QUESTION,
            "answer": "Modified after the answer was issued.",
            "helpful": True,
            "receipt": feedback_receipt,
        }
    raise ValueError("unknown trusted identity body kind")


def _signing_principal(
    case: TrustedIdentityCase,
    *,
    verifier: IdentityVerifier,
    user_token: str,
    operator_token: str,
) -> Principal:
    token = operator_token if case.credential == "operator" else user_token
    return verifier.verify_bearer(f"Bearer {token}")


def _evaluate_feedback_write(
    calls: list[dict[str, Any]],
    *,
    settings: Settings,
    feedback_hasher: FeedbackActorPseudonymizer,
    principal: Principal,
) -> tuple[bool, bool]:
    if len(calls) != 1:
        return False, False
    call = calls[0]
    binding_match = (
        call.get("actor_pseudonym")
        == feedback_hasher.pseudonym(principal)
        and call.get("target_request_id") == _FEEDBACK_TARGET_REQUEST_ID
        and call.get("request_id") == "identity-eval-feedback_verified_user"
    )
    privacy_match = (
        "question" not in call
        and "answer" not in call
        and call.get("question_hmac_sha256")
        == feedback_hasher.content_digest("question", _FEEDBACK_QUESTION)
        and call.get("answer_hmac_sha256")
        == feedback_hasher.content_digest("answer", _FEEDBACK_ANSWER)
        and call.get("helpful") is True
        and call.get("settings") is settings
        and _FEEDBACK_QUESTION not in call.values()
        and _FEEDBACK_ANSWER not in call.values()
    )
    return binding_match, privacy_match


def _contains_credential_leak(
    response: Any,
    *,
    case: TrustedIdentityCase,
    user_token: str,
    operator_token: str,
    hmac_key: bytes,
) -> bool:
    surface = response.text + "\n" + json.dumps(
        dict(response.headers),
        ensure_ascii=False,
        sort_keys=True,
    )
    token_markers = {
        user_token,
        operator_token,
        "attacker-token",
        *user_token.split("."),
        *operator_token.split("."),
    }
    key_markers = {
        hmac_key.hex(),
        base64.b64encode(hmac_key).decode("ascii"),
        base64.urlsafe_b64encode(hmac_key).decode("ascii"),
        "BEGIN PRIVATE KEY",
        "BEGIN RSA PRIVATE KEY",
        "feedback_actor_hmac.key",
    }
    identity_markers = set()
    if case.path != "/identity/me":
        identity_markers = {
            "load-demo-employee",
            "starbridge-cn",
            "all_employees",
            "https://identity.localhost/",
        }
    return any(
        marker and marker in surface
        for marker in token_markers | key_markers | identity_markers
    )


def _error_code(response) -> str | None:
    if response.status_code < 400:
        return None
    try:
        payload = response.json()
    except Exception:
        return "invalid_error_response"
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) else "invalid_error_response"


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


__all__ = [
    "EXPECTED_MATRIX_SHA256",
    "TRUSTED_IDENTITY_SOURCE_FILES",
    "TrustedIdentityEvaluationResult",
    "TrustedIdentityMatrix",
    "evaluate_trusted_identity",
    "load_trusted_identity_matrix",
]
