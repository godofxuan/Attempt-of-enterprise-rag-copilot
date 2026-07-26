from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.identity import route_access_policy
from app.lifecycle.operator import LifecycleStatusResult
from app.main import create_app
from tests.api_v2.helpers import OPERATOR_HEADERS, USER_HEADERS, make_container


OPERATOR_ROUTES = (
    ("POST", "/operator/lifecycle/preview"),
    ("POST", "/operator/lifecycle/build"),
    ("POST", "/operator/lifecycle/activate"),
    ("POST", "/operator/lifecycle/rollback"),
    ("GET", "/operator/lifecycle/status"),
)


class RecordingLifecycleOperator:
    def __init__(self) -> None:
        self.calls = 0

    def status(self, principal) -> LifecycleStatusResult:
        self.calls += 1
        return LifecycleStatusResult(
            state="EMPTY",
            catalog_sha256="0" * 64,
            catalog_event_count=0,
            live_source_count=0,
            tombstone_count=0,
        )

    def preview(self, request, principal):
        raise AssertionError("preview was not expected")

    def build(self, request, principal):
        raise AssertionError("build was not expected")

    def activate_existing(self, request, principal):
        raise AssertionError("activation was not expected")

    def rollback(self, request, principal):
        raise AssertionError("rollback was not expected")


def _client(operator: RecordingLifecycleOperator) -> TestClient:
    container = replace(
        make_container(),
        lifecycle_operator=operator,
    )
    return TestClient(create_app(container))


def test_every_lifecycle_route_is_exactly_operator_only() -> None:
    for method, path in OPERATOR_ROUTES:
        assert route_access_policy(method, path).access == "operator"


@pytest.mark.parametrize(
    ("headers", "expected_status", "expected_code"),
    [
        ({}, 401, "authentication_required"),
        (USER_HEADERS, 403, "insufficient_role"),
    ],
)
def test_status_rejects_before_lifecycle_service_access(
    headers: dict[str, str],
    expected_status: int,
    expected_code: str,
) -> None:
    operator = RecordingLifecycleOperator()

    response = _client(operator).get(
        "/operator/lifecycle/status",
        headers=headers,
    )

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert operator.calls == 0


def test_operator_status_is_synchronous_and_sanitized() -> None:
    operator = RecordingLifecycleOperator()

    response = _client(operator).get(
        "/operator/lifecycle/status",
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 200
    assert operator.calls == 1
    payload = response.json()
    assert payload["state"] == "EMPTY"
    rendered = response.text.casefold()
    for forbidden in (
        "job_id",
        "queued",
        "input_root",
        "catalog_root",
        "index_root",
        "token",
        "claims",
    ):
        assert forbidden not in rendered


@pytest.mark.parametrize(
    ("headers", "expected_status", "expected_code"),
    [
        ({}, 401, "authentication_required"),
        (USER_HEADERS, 403, "insufficient_role"),
    ],
)
def test_authentication_precedes_invalid_lifecycle_request_body(
    headers: dict[str, str],
    expected_status: int,
    expected_code: str,
) -> None:
    operator = RecordingLifecycleOperator()

    response = _client(operator).post(
        "/operator/lifecycle/build",
        headers={
            **headers,
            "content-type": "application/json",
        },
        content=b'{"not valid JSON"',
    )

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert operator.calls == 0


def test_operator_request_cannot_select_private_storage_roots() -> None:
    operator = RecordingLifecycleOperator()

    response = _client(operator).post(
        "/operator/lifecycle/build",
        headers=OPERATOR_HEADERS,
        json={
            "target_run_id": "run-api-root-rejected",
            "events": [],
            "catalog_root": "C:/private/catalog",
            "cache_root": "C:/private/cache",
            "index_root": "C:/private/index",
        },
    )

    assert response.status_code == 422
    assert operator.calls == 0
    rendered = response.text.casefold()
    assert "c:/private" not in rendered


def test_invalid_source_event_path_is_rejected_before_operator_call() -> None:
    operator = RecordingLifecycleOperator()

    response = _client(operator).post(
        "/operator/lifecycle/build",
        headers=OPERATOR_HEADERS,
        json={
            "target_run_id": "run-api-invalid-path",
            "events": [
                {
                    "event_id": "evt-api-invalid-path",
                    "operation": "UPSERT",
                    "tenant_id": "tenant-a",
                    "region": "cn",
                    "source_system": "sharepoint",
                    "source_key": "policy/remote-access",
                    "occurred_at": datetime(
                        2026, 7, 27, 4, 0, tzinfo=timezone.utc
                    ).isoformat(),
                    "content_relpath": "../outside.txt",
                    "declared_media_type": "text/plain",
                    "content_sha256": "1" * 64,
                    "acl_groups": ["group-employees"],
                    "document_projection": {
                        "document_id": "doc-api-invalid-path",
                        "version_id": "v1",
                        "title": "Invalid path fixture",
                        "department": "Security",
                        "version": "1",
                        "authority_level": 80,
                    },
                }
            ],
        },
    )

    assert response.status_code == 422
    assert operator.calls == 0
    assert "../outside.txt" not in response.text


@pytest.mark.parametrize(
    ("category", "private_code", "expected_status", "public_code"),
    [
        ("file_validation", "contains-private-name", 422, "source_validation_failed"),
        ("build", "ollama-payload-contained-secret", 503, "lifecycle_build_failed"),
        ("manifest", "D:/private/catalog-corrupt", 500, "lifecycle_state_invalid"),
    ],
)
def test_api_maps_private_domain_errors_to_stable_public_codes(
    category: str,
    private_code: str,
    expected_status: int,
    public_code: str,
) -> None:
    class FailingOperator(RecordingLifecycleOperator):
        def status(self, principal):
            self.calls += 1
            from app.lifecycle.operator import LifecycleOperationError

            raise LifecycleOperationError(
                category,
                private_code,
                "The lifecycle operation failed safely.",
            )

    operator = FailingOperator()

    response = _client(operator).get(
        "/operator/lifecycle/status",
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == public_code
    assert private_code not in response.text
