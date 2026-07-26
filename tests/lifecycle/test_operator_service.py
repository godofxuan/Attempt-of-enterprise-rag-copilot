from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.lifecycle.operator import (
    LifecycleActivateRequest,
    LifecycleBuildRequest,
    LifecycleOperationError,
    LifecycleOperatorService,
    LifecyclePlanProposal,
    LifecyclePreviewRequest,
    LifecyclePreviewResult,
    LifecycleRollbackRequest,
    OperatorSourceEventInput,
)
from app.domain.documents import DocumentVersion
from app.indexing.computation_cache import (
    ComponentFingerprint,
    EmbeddingFingerprint,
)
from app.indexing.incremental_computation import PipelineConfiguration
from app.indexing.store import publication_lock
from app.ingestion.chunking import ChunkerConfig
from app.ingestion.revision_catalog import DocumentProjection
from app.security.identity import Principal


NOW = datetime(2026, 7, 27, 1, 30, tzinfo=timezone.utc)
CONTENT = b"# Leave\nEmployees receive ten days of annual leave.\n"


class ActorPseudonymizer:
    def pseudonym(self, principal: Principal) -> str:
        return f"actor-{principal.subject}"


def _principal(*, operator: bool = True) -> Principal:
    return Principal(
        subject="ops-user",
        tenant_id="tenant-a",
        region="ap-east",
        groups=["group-employees"],
        roles=["rag.operator"] if operator else [],
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        key_id="test-key",
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=10),
    )


def _pipeline() -> PipelineConfiguration:
    return PipelineConfiguration(
        materializer=ComponentFingerprint(
            name="production-revision-materializer",
            semantic_version="1",
            implementation_sha256="1" * 64,
        ),
        governance=ComponentFingerprint(
            name="enterprise-governance",
            semantic_version="1",
            implementation_sha256="2" * 64,
        ),
        normalizer=ComponentFingerprint(
            name="lifecycle-normalizer",
            semantic_version="1",
            implementation_sha256="3" * 64,
        ),
        chunker=ComponentFingerprint(
            name="enterprise-chunker",
            semantic_version="1",
            implementation_sha256="4" * 64,
        ),
        chunker_config=ChunkerConfig(
            mode="fixed",
            chunk_size=200,
            overlap=20,
        ),
        embedding=EmbeddingFingerprint(
            component=ComponentFingerprint(
                name="fixture-embedder",
                semantic_version="1",
                implementation_sha256="5" * 64,
            ),
            backend="deterministic-test",
            model_identifier="fixture-4d",
            model_sha256="6" * 64,
            dimension=4,
            normalization="l2",
        ),
    )


def _service(
    root: Path,
    *,
    enable_build: bool = False,
    operation_lock_timeout_seconds: float = 10.0,
) -> LifecycleOperatorService:
    return LifecycleOperatorService(
        input_root=(root / "input").absolute(),
        asset_root=(root / "assets").absolute(),
        catalog_root=(root / "catalog").absolute(),
        cache_root=(root / "cache").absolute(),
        index_root=(root / "indexes").absolute(),
        actor_pseudonymizer=ActorPseudonymizer(),
        pipeline=_pipeline() if enable_build else None,
        embed_text=(
            (lambda text: [1.0, 2.0, 3.0, 4.0])
            if enable_build
            else None
        ),
        operation_lock_timeout_seconds=operation_lock_timeout_seconds,
    )


def _upsert(*, tenant_id: str = "tenant-a") -> OperatorSourceEventInput:
    return OperatorSourceEventInput(
        event_id="evt-leave-1",
        operation="UPSERT",
        tenant_id=tenant_id,
        region="ap-east",
        source_system="sharepoint",
        source_key="policy/leave",
        occurred_at=NOW,
        content_relpath="policies/leave.md",
        declared_media_type="text/markdown",
        content_sha256=hashlib.sha256(CONTENT).hexdigest(),
        acl_groups=("group-employees",),
        document_projection=DocumentProjection(
            source_type="policy",
            source_path="sharepoint:policy/leave",
            format="markdown",
            department="People",
            filed_department="People",
            policy_id=None,
            document_version=DocumentVersion(
                version_id="leave-v1",
                version="1",
                status="active",
                effective_from=NOW.date(),
                authority_level=80,
            ),
            authority_level=80,
            variant="authoritative",
        ),
    )


def test_preview_derives_actor_and_leaves_all_durable_roots_absent(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)

    result = service.preview(
        LifecyclePreviewRequest(
            target_run_id="run-preview-1",
            events=(_upsert(),),
        ),
        _principal(),
    )

    assert result.operation == "PREVIEW"
    assert result.status == "COMPLETED"
    assert result.plan_kind == "PROPOSED"
    assert result.plan is None
    assert result.proposal is not None
    assert result.proposal.requested_event_count == 1
    assert result.proposal.materialization_pending_count == 1
    assert result.proposal.replay_count == 0
    assert not any(tmp_path.iterdir())


def test_preview_result_rejects_inconsistent_exact_and_proposed_shapes() -> None:
    proposal = LifecyclePlanProposal(
        target_run_id="run-preview-1",
        base_catalog_sha256="0" * 64,
        current_catalog_sha256="0" * 64,
        requested_events_sha256="1" * 64,
        requested_event_count=1,
        upsert_count=1,
        delete_count=0,
        replay_count=0,
        materialization_pending_count=1,
    )

    with pytest.raises(ValueError):
        LifecyclePreviewResult(plan_kind="EXACT", proposal=proposal)

    with pytest.raises(ValueError):
        LifecyclePreviewResult(plan_kind="PROPOSED")


@pytest.mark.parametrize(
    ("principal", "event", "expected_code"),
    [
        (_principal(operator=False), _upsert(), "operator_role_required"),
        (_principal(), _upsert(tenant_id="tenant-b"), "tenant_mismatch"),
    ],
)
def test_preview_rejects_untrusted_scope_before_storage_access(
    tmp_path: Path,
    principal: Principal,
    event: OperatorSourceEventInput,
    expected_code: str,
) -> None:
    service = _service(tmp_path)

    with pytest.raises(LifecycleOperationError) as captured:
        service.preview(
            LifecyclePreviewRequest(
                target_run_id="run-preview-1",
                events=(event,),
            ),
            principal,
        )

    assert captured.value.category == "authorization"
    assert captured.value.code == expected_code
    assert not any(tmp_path.iterdir())


def test_operator_transport_rejects_actor_and_storage_capabilities() -> None:
    payload = _upsert().model_dump(mode="json")
    payload["actor_pseudonym"] = "forged"
    payload["index_root"] = "C:/outside"

    with pytest.raises(ValueError):
        OperatorSourceEventInput.model_validate(payload)


def test_operator_transport_rejects_delete_acl_before_business_execution() -> None:
    payload = _upsert().model_dump(mode="json")
    payload.update(
        {
            "event_id": "evt-delete-with-acl",
            "operation": "DELETE",
            "expected_revision_id": f"rev_{'1' * 64}",
            "content_relpath": None,
            "declared_media_type": None,
            "content_sha256": None,
            "document_projection": None,
            "acl_groups": ["group-employees"],
        }
    )

    with pytest.raises(ValueError, match="DELETE must not carry ACL groups"):
        OperatorSourceEventInput.model_validate(payload)


@pytest.mark.parametrize(
    "updates",
    [
        {"content_relpath": "../outside.txt"},
        {"declared_media_type": "not-a-media-type"},
        {"occurred_at": "2026-07-27T04:00:00"},
        {"acl_groups": ["group-employees", "group-employees"]},
        {"source_key": "policy/control\ninjection"},
    ],
)
def test_operator_transport_preflights_complete_source_event_contract(
    updates: dict[str, object],
) -> None:
    payload = _upsert().model_dump(mode="json")
    payload.update(updates)

    with pytest.raises(ValueError):
        OperatorSourceEventInput.model_validate(payload)


def test_projection_digest_is_bound_into_the_canonical_source_event() -> None:
    first = _upsert()
    assert first.document_projection is not None
    changed = first.model_copy(
        update={
            "document_projection": first.document_projection.model_copy(
                update={"department": "Legal"}
            )
        }
    )

    first_event = first.to_source_event(actor_pseudonym="actor-ops-user")
    changed_event = changed.to_source_event(actor_pseudonym="actor-ops-user")

    assert first_event.metadata != changed_event.metadata
    assert (
        first_event.metadata["document_projection_sha256"]
        != changed_event.metadata["document_projection_sha256"]
    )


@pytest.mark.parametrize("activate", [False, True])
def test_build_publishes_real_snapshot_and_only_activates_when_requested(
    tmp_path: Path,
    activate: bool,
) -> None:
    input_path = tmp_path / "input" / "policies" / "leave.md"
    input_path.parent.mkdir(parents=True)
    input_path.write_bytes(CONTENT)
    service = _service(tmp_path, enable_build=True)

    result = service.build(
        LifecycleBuildRequest(
            target_run_id=f"run-build-{int(activate)}",
            events=(_upsert(),),
            activate=activate,
        ),
        _principal(),
    )

    target = tmp_path / "indexes" / "versions" / result.run_id
    assert result.operation == (
        "BUILD_AND_ACTIVATE" if activate else "BUILD"
    )
    assert result.status == "COMPLETED"
    assert result.activated is activate
    assert target.is_dir()
    assert (target / "manifest.json").is_file()
    assert (target / "lifecycle.json").is_file()
    assert (tmp_path / "indexes" / "active.json").exists() is activate


def test_activate_existing_uses_expected_current_cas_and_status_is_derived(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input" / "policies" / "leave.md"
    input_path.parent.mkdir(parents=True)
    input_path.write_bytes(CONTENT)
    service = _service(tmp_path, enable_build=True)
    built = service.build(
        LifecycleBuildRequest(
            target_run_id="run-installed",
            events=(_upsert(),),
            activate=False,
        ),
        _principal(),
    )

    pending = service.status(_principal())
    assert pending.state == "INDEX_UPDATE_PENDING"
    assert pending.active_run_id is None
    assert pending.catalog_event_count == 1
    activated = service.activate_existing(
        LifecycleActivateRequest(
            target_run_id=built.run_id,
            expected_current_run_id=None,
        ),
        _principal(),
    )

    assert activated.run_id == built.run_id
    synchronized = service.status(_principal())
    assert synchronized.state == "SYNCHRONIZED"
    assert synchronized.active_run_id == built.run_id
    assert synchronized.active_catalog_sha256 == synchronized.catalog_sha256
    assert "path" not in synchronized.model_dump_json().casefold()

    with pytest.raises(LifecycleOperationError) as captured:
        service.activate_existing(
            LifecycleActivateRequest(
                target_run_id=built.run_id,
                expected_current_run_id=None,
            ),
            _principal(),
        )
    assert captured.value.category == "conflict"
    assert captured.value.code == "active_version_conflict"
    assert service.status(_principal()).active_run_id == built.run_id


def test_exact_replay_does_not_reopen_source_or_create_another_asset(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input" / "policies" / "leave.md"
    input_path.parent.mkdir(parents=True)
    input_path.write_bytes(CONTENT)
    service = _service(tmp_path, enable_build=True)
    accepted = service.build(
        LifecycleBuildRequest(
            target_run_id="run-replay-base",
            events=(_upsert(),),
            activate=True,
        ),
        _principal(),
    )
    staged_root = tmp_path / "assets" / "staged"
    first_assets = sorted(path.name for path in staged_root.iterdir())
    input_path.unlink()

    replayed = service.build(
        LifecycleBuildRequest(
            target_run_id="run-replay-target",
            events=(_upsert(),),
            activate=False,
        ),
        _principal(),
    )

    assert replayed.status == "COMPLETED"
    assert accepted.events[0].disposition == "APPLIED"
    assert replayed.events[0].disposition == "REPLAYED"
    assert (
        replayed.events[0].event_payload_sha256
        == accepted.events[0].event_payload_sha256
    )
    assert (
        replayed.events[0].resulting_revision_id
        == accepted.events[0].resulting_revision_id
    )
    assert sorted(path.name for path in staged_root.iterdir()) == first_assets


def test_replay_preview_is_byte_for_byte_read_only(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input" / "policies" / "leave.md"
    input_path.parent.mkdir(parents=True)
    input_path.write_bytes(CONTENT)
    service = _service(tmp_path, enable_build=True)
    service.build(
        LifecycleBuildRequest(
            target_run_id="run-read-only-base",
            events=(_upsert(),),
            activate=True,
        ),
        _principal(),
    )
    catalog_lock = tmp_path / "catalog" / ".catalog.lock"
    catalog_lock.unlink()

    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    result = service.preview(
        LifecyclePreviewRequest(
            target_run_id="run-read-only-preview",
            events=(_upsert(),),
        ),
        _principal(),
    )
    after = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    assert result.plan_kind == "EXACT"
    assert before == after
    assert not catalog_lock.exists()


def test_build_reports_busy_when_another_lifecycle_operation_holds_lock(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input" / "policies" / "leave.md"
    input_path.parent.mkdir(parents=True)
    input_path.write_bytes(CONTENT)
    service = _service(
        tmp_path,
        enable_build=True,
        operation_lock_timeout_seconds=0.01,
    )

    with publication_lock(service.operation_lock_root):
        with pytest.raises(LifecycleOperationError) as captured:
            service.build(
                LifecycleBuildRequest(
                    target_run_id="run-contended",
                    events=(_upsert(),),
                ),
                _principal(),
            )

    assert captured.value.category == "conflict"
    assert captured.value.code == "lifecycle_operation_busy"
    assert not (tmp_path / "catalog").exists()
    assert not (tmp_path / "assets").exists()


def test_rollback_is_synchronous_audited_and_keeps_status_sanitized(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input" / "policies" / "leave.md"
    input_path.parent.mkdir(parents=True)
    input_path.write_bytes(CONTENT)
    service = _service(tmp_path, enable_build=True)
    first = service.build(
        LifecycleBuildRequest(
            target_run_id="run-rollback-base",
            events=(_upsert(),),
            activate=True,
        ),
        _principal(),
    )
    second = service.build(
        LifecycleBuildRequest(
            target_run_id="run-rollback-current",
            events=(),
            activate=True,
        ),
        _principal(),
    )

    rolled_back = service.rollback(
        LifecycleRollbackRequest(
            target_run_id=first.run_id,
            expected_current_run_id=second.run_id,
        ),
        _principal(),
    )

    assert rolled_back.operation == "ROLLBACK"
    assert rolled_back.status == "COMPLETED"
    assert rolled_back.from_run_id == second.run_id
    assert rolled_back.to_run_id == first.run_id
    assert (tmp_path / "indexes" / "audit" / "rollback.jsonl").is_file()
    status = service.status(_principal())
    assert status.active_run_id == first.run_id
    assert status.state == "SYNCHRONIZED"
