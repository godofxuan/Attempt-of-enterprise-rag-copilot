from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.indexing.change_plan import ChangePlan, build_change_plan
from app.indexing.computation_cache import PersistentComputationCache
from app.indexing.incremental_computation import (
    EmbedText,
    IncrementalComputationError,
    PipelineConfiguration,
)
from app.indexing.incremental_snapshot import validate_incremental_index_directory
from app.indexing.incremental_snapshot import (
    LifecyclePublicationError,
    execute_incremental_publication,
    recover_pending_rollback,
    rollback_index_version,
)
from app.indexing.store import (
    activate_version,
    load_index_version,
    publication_lock,
)
from app.ingestion.file_validation import (
    AssetAdmissionError,
    admit_source_event_asset,
)
from app.ingestion.email_parser import EmailParseError
from app.ingestion.revision_catalog import (
    CatalogApplication,
    CatalogConflict,
    DocumentProjection,
    PersistentRevisionCatalog,
    RevisionCatalogSnapshot,
    apply_revision_catalog_snapshot,
    empty_revision_catalog_snapshot,
    load_revision_catalog_snapshot_read_only,
    revision_catalog_sha256,
)
from app.ingestion.source_events import (
    MetadataScalar,
    SourceEvent,
    SourceEventConflict,
    SourceEventLedger,
    SourceOperation,
    source_event_payload_sha256,
)
from app.security.identity import Principal
from app.lifecycle.materializer import ProductionRevisionContentMaterializer
from app.lifecycle.pipeline import LifecyclePipelineRuntime


LifecycleErrorCategory = Literal[
    "schema",
    "authorization",
    "file_validation",
    "quarantine",
    "conflict",
    "build",
    "manifest",
    "activation",
    "rollback",
]


class LifecycleOperatorModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class OperatorSourceEventTemplateInput(LifecycleOperatorModel):
    schema_version: Literal["operator_source_event_v1"] = (
        "operator_source_event_v1"
    )
    event_id: str = Field(min_length=1, max_length=128)
    operation: SourceOperation
    tenant_id: str = Field(min_length=1, max_length=128)
    region: str = Field(min_length=1, max_length=64)
    source_system: str = Field(min_length=1, max_length=128)
    source_key: str = Field(min_length=1, max_length=256)
    expected_revision_id: str | None = Field(
        default=None,
        pattern=r"^rev_[0-9a-f]{64}$",
    )
    occurred_at: datetime
    content_relpath: str | None = Field(default=None, max_length=512)
    declared_media_type: str | None = Field(default=None, max_length=128)
    content_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    acl_groups: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    metadata: dict[str, MetadataScalar] = Field(default_factory=dict, max_length=64)
    document_projection: DocumentProjection | None = None

    @model_validator(mode="after")
    def validate_projection_shape(self) -> OperatorSourceEventTemplateInput:
        if "document_projection_sha256" in self.metadata:
            raise ValueError(
                "document projection digest is derived by the trusted boundary"
            )
        if self.operation == "UPSERT" and self.document_projection is None:
            raise ValueError("UPSERT requires document_projection")
        if self.operation == "UPSERT" and not self.acl_groups:
            raise ValueError("UPSERT requires ACL groups")
        if self.operation == "DELETE" and self.document_projection is not None:
            raise ValueError("DELETE must not carry document_projection")
        if self.operation == "DELETE" and self.acl_groups:
            raise ValueError("DELETE must not carry ACL groups")
        payload = self.model_dump(
            mode="python",
            exclude={"schema_version", "document_projection"},
        )
        if self.operation == "DELETE" and self.expected_revision_id is None:
            payload["expected_revision_id"] = f"rev_{'0' * 64}"
        try:
            SourceEvent(
                **payload,
                actor_pseudonym="operator-transport-preflight",
            )
        except ValidationError as exc:
            raise ValueError(
                "operator event violates the canonical source contract"
            ) from exc
        return self

    def to_source_event(self, *, actor_pseudonym: str) -> SourceEvent:
        payload = self.model_dump(
            mode="python",
            exclude={"schema_version", "document_projection"},
        )
        if self.document_projection is not None:
            payload["metadata"] = {
                **payload["metadata"],
                "document_projection_sha256": (
                    self.document_projection.canonical_sha256()
                ),
            }
        return SourceEvent(
            **payload,
            actor_pseudonym=actor_pseudonym,
        )


class OperatorSourceEventInput(OperatorSourceEventTemplateInput):
    @model_validator(mode="after")
    def require_concrete_delete_revision(self) -> OperatorSourceEventInput:
        if self.operation == "DELETE" and self.expected_revision_id is None:
            raise ValueError("DELETE requires expected_revision_id")
        return self


class LifecyclePreviewRequest(LifecycleOperatorModel):
    schema_version: Literal["lifecycle_preview_request_v1"] = (
        "lifecycle_preview_request_v1"
    )
    target_run_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )
    events: tuple[OperatorSourceEventInput, ...] = Field(
        min_length=1,
        max_length=1000,
    )

    @field_validator("events")
    @classmethod
    def validate_event_ids(
        cls,
        values: tuple[OperatorSourceEventInput, ...],
    ) -> tuple[OperatorSourceEventInput, ...]:
        event_ids = [event.event_id for event in values]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("preview event IDs must be unique")
        return values


class LifecycleBuildRequest(LifecycleOperatorModel):
    schema_version: Literal["lifecycle_build_request_v1"] = (
        "lifecycle_build_request_v1"
    )
    target_run_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )
    events: tuple[OperatorSourceEventInput, ...] = Field(
        default_factory=tuple,
        max_length=1000,
    )
    activate: bool = False

    @field_validator("events")
    @classmethod
    def validate_event_ids(
        cls,
        values: tuple[OperatorSourceEventInput, ...],
    ) -> tuple[OperatorSourceEventInput, ...]:
        event_ids = [event.event_id for event in values]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("build event IDs must be unique")
        return values


class LifecycleBuildResult(LifecycleOperatorModel):
    schema_version: Literal["lifecycle_build_result_v1"] = (
        "lifecycle_build_result_v1"
    )
    operation: Literal["BUILD", "BUILD_AND_ACTIVATE"]
    status: Literal["COMPLETED"] = "COMPLETED"
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    plan_id: str = Field(pattern=r"^plan_[0-9a-f]{64}$")
    publication_id: str = Field(pattern=r"^publication_[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    activated: bool
    document_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    events: tuple[LifecycleEventResult, ...] = ()


class LifecycleEventResult(LifecycleOperatorModel):
    schema_version: Literal["lifecycle_event_result_v1"] = (
        "lifecycle_event_result_v1"
    )
    event_id: str = Field(min_length=1, max_length=128)
    disposition: Literal["APPLIED", "REPLAYED"]
    operation: SourceOperation
    event_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    resulting_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{64}$")
    deleted: bool
    catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_application(
        cls,
        application: CatalogApplication,
    ) -> LifecycleEventResult:
        receipt = application.receipt
        return cls(
            event_id=receipt.event_id,
            disposition=application.status,
            operation=receipt.operation,
            event_payload_sha256=receipt.payload_sha256,
            resulting_revision_id=receipt.resulting_revision_id,
            deleted=receipt.deleted,
            catalog_sha256=application.catalog_sha256,
        )


class LifecycleActivateRequest(LifecycleOperatorModel):
    schema_version: Literal["lifecycle_activate_request_v1"] = (
        "lifecycle_activate_request_v1"
    )
    target_run_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )
    expected_current_run_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )


class LifecycleActivationResult(LifecycleOperatorModel):
    schema_version: Literal["lifecycle_activation_result_v1"] = (
        "lifecycle_activation_result_v1"
    )
    operation: Literal["ACTIVATE"] = "ACTIVATE"
    status: Literal["COMPLETED"] = "COMPLETED"
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class LifecycleStatusResult(LifecycleOperatorModel):
    schema_version: Literal["lifecycle_status_result_v1"] = (
        "lifecycle_status_result_v1"
    )
    state: Literal[
        "EMPTY",
        "INDEX_UPDATE_PENDING",
        "SYNCHRONIZED",
        "STATE_INVALID",
    ]
    catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_event_count: int = Field(ge=0)
    live_source_count: int = Field(ge=0)
    tombstone_count: int = Field(ge=0)
    active_run_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    active_manifest_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    active_catalog_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


class LifecycleRollbackRequest(LifecycleOperatorModel):
    schema_version: Literal["lifecycle_rollback_request_v1"] = (
        "lifecycle_rollback_request_v1"
    )
    target_run_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )
    expected_current_run_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )


class LifecycleRollbackResult(LifecycleOperatorModel):
    schema_version: Literal["lifecycle_rollback_result_v1"] = (
        "lifecycle_rollback_result_v1"
    )
    operation: Literal["ROLLBACK"] = "ROLLBACK"
    status: Literal["COMPLETED"] = "COMPLETED"
    from_run_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )
    to_run_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    audit_event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class LifecyclePreviewResult(LifecycleOperatorModel):
    schema_version: Literal["lifecycle_preview_result_v1"] = (
        "lifecycle_preview_result_v1"
    )
    operation: Literal["PREVIEW"] = "PREVIEW"
    status: Literal["COMPLETED"] = "COMPLETED"
    plan_kind: Literal["EXACT", "PROPOSED"]
    plan: ChangePlan | None = None
    proposal: LifecyclePlanProposal | None = None

    @model_validator(mode="after")
    def validate_result_shape(self) -> LifecyclePreviewResult:
        if self.plan_kind == "EXACT":
            if self.plan is None or self.proposal is not None:
                raise ValueError("EXACT preview requires only an exact plan")
        elif self.plan is not None or self.proposal is None:
            raise ValueError("PROPOSED preview requires only a proposal")
        return self


class LifecyclePlanProposal(LifecycleOperatorModel):
    schema_version: Literal["lifecycle_plan_proposal_v1"] = (
        "lifecycle_plan_proposal_v1"
    )
    target_run_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )
    base_index_run_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    base_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_events_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_event_count: int = Field(ge=1)
    upsert_count: int = Field(ge=0)
    delete_count: int = Field(ge=0)
    replay_count: int = Field(ge=0)
    materialization_pending_count: int = Field(ge=1)


class ActorPseudonymizer(Protocol):
    def pseudonym(self, principal: Principal) -> str: ...


class LifecycleOperationError(RuntimeError):
    def __init__(
        self,
        category: LifecycleErrorCategory,
        code: str,
        safe_message: str,
    ) -> None:
        self.category = category
        self.code = code
        self.safe_message = safe_message
        super().__init__(f"{category}:{code}")


class LifecycleOperatorService:
    def __init__(
        self,
        *,
        input_root: Path,
        asset_root: Path,
        catalog_root: Path,
        cache_root: Path,
        index_root: Path,
        actor_pseudonymizer: ActorPseudonymizer,
        operator_role: str = "rag.operator",
        pipeline: PipelineConfiguration | None = None,
        embed_text: EmbedText | None = None,
        runtime_factory: Callable[[], LifecyclePipelineRuntime] | None = None,
        operation_lock_timeout_seconds: float = 10.0,
    ) -> None:
        roots = (
            Path(input_root),
            Path(asset_root),
            Path(catalog_root),
            Path(cache_root),
            Path(index_root),
        )
        if any(not root.is_absolute() for root in roots):
            raise ValueError("lifecycle roots must be absolute")
        if operation_lock_timeout_seconds <= 0:
            raise ValueError("operation_lock_timeout_seconds must be positive")
        (
            self.input_root,
            self.asset_root,
            self.catalog_root,
            self.cache_root,
            self.index_root,
        ) = roots
        self.actor_pseudonymizer = actor_pseudonymizer
        self.operator_role = operator_role
        self.pipeline = pipeline
        self.embed_text = embed_text
        self.runtime_factory = runtime_factory
        self.operation_lock_timeout_seconds = operation_lock_timeout_seconds
        self.operation_lock_root = self.catalog_root.parent / "operator-lock"

    def with_operator_roots(
        self,
        *,
        input_root: Path | None = None,
        index_root: Path | None = None,
    ) -> LifecycleOperatorService:
        return LifecycleOperatorService(
            input_root=(
                self.input_root
                if input_root is None
                else Path(input_root)
            ),
            asset_root=self.asset_root,
            catalog_root=self.catalog_root,
            cache_root=self.cache_root,
            index_root=(
                self.index_root
                if index_root is None
                else Path(index_root)
            ),
            actor_pseudonymizer=self.actor_pseudonymizer,
            operator_role=self.operator_role,
            pipeline=self.pipeline,
            embed_text=self.embed_text,
            runtime_factory=self.runtime_factory,
            operation_lock_timeout_seconds=self.operation_lock_timeout_seconds,
        )

    def preview(
        self,
        request: LifecyclePreviewRequest,
        principal: Principal,
    ) -> LifecyclePreviewResult:
        strict_request = LifecyclePreviewRequest.model_validate(
            request.model_dump(mode="json")
        )
        strict_principal = Principal.model_validate(
            principal.model_dump(mode="python")
        )
        self._authorize_batch(strict_request.events, strict_principal)
        try:
            actor = self.actor_pseudonymizer.pseudonym(strict_principal)
        except Exception:
            raise LifecycleOperationError(
                "authorization",
                "identity_material_unavailable",
                "The trusted actor identity is unavailable.",
            ) from None

        events = tuple(
            item.to_source_event(actor_pseudonym=actor)
            for item in strict_request.events
        )
        try:
            current = self._current_catalog()
            base, base_run_id = self._active_catalog()
            applications = self._preview_applications(current, events)
            pending = sum(
                event.operation == "UPSERT" and status == "APPLIED"
                for event, status in zip(events, applications, strict=True)
            )
            if pending:
                event_hashes = sorted(
                    source_event_payload_sha256(event)
                    for event in events
                )
                proposal = LifecyclePlanProposal(
                    target_run_id=strict_request.target_run_id,
                    base_index_run_id=base_run_id,
                    base_catalog_sha256=revision_catalog_sha256(base),
                    current_catalog_sha256=revision_catalog_sha256(current),
                    requested_events_sha256=hashlib.sha256(
                        ("\n".join(event_hashes)).encode("ascii")
                    ).hexdigest(),
                    requested_event_count=len(events),
                    upsert_count=sum(
                        event.operation == "UPSERT" for event in events
                    ),
                    delete_count=sum(
                        event.operation == "DELETE" for event in events
                    ),
                    replay_count=applications.count("REPLAYED"),
                    materialization_pending_count=pending,
                )
                return LifecyclePreviewResult(
                    plan_kind="PROPOSED",
                    proposal=proposal,
                )
            target = self._exact_preview_target(current, events)
            plan = build_change_plan(
                base=base,
                target=target,
                base_index_run_id=base_run_id,
                target_index_run_id=strict_request.target_run_id,
            )
        except (SourceEventConflict, CatalogConflict) as exc:
            raise LifecycleOperationError(
                "conflict",
                getattr(exc, "code", "lifecycle_conflict"),
                "The requested lifecycle transition conflicts with current state.",
            ) from None
        except LifecycleOperationError:
            raise
        except Exception:
            raise LifecycleOperationError(
                "manifest",
                "lifecycle_state_invalid",
                "The lifecycle state failed validation.",
            ) from None
        return LifecyclePreviewResult(plan_kind="EXACT", plan=plan)

    def build(
        self,
        request: LifecycleBuildRequest,
        principal: Principal,
    ) -> LifecycleBuildResult:
        strict_request = LifecycleBuildRequest.model_validate(
            request.model_dump(mode="json")
        )
        strict_principal = Principal.model_validate(
            principal.model_dump(mode="python")
        )
        self._authorize_batch(strict_request.events, strict_principal)
        return self._run_serialized(
            lambda: self._build_impl(strict_request, strict_principal)
        )

    def _build_impl(
        self,
        request: LifecycleBuildRequest,
        principal: Principal,
    ) -> LifecycleBuildResult:
        strict_request = LifecycleBuildRequest.model_validate(
            request.model_dump(mode="json")
        )
        strict_principal = Principal.model_validate(
            principal.model_dump(mode="python")
        )
        self._authorize_batch(strict_request.events, strict_principal)
        pipeline = self.pipeline
        embed_text = self.embed_text
        if pipeline is None or embed_text is None:
            if self.runtime_factory is None:
                raise LifecycleOperationError(
                    "build",
                    "lifecycle_pipeline_unavailable",
                    "The lifecycle build pipeline is unavailable.",
                )
            try:
                runtime = self.runtime_factory()
                pipeline = runtime.pipeline
                embed_text = runtime.embed_text
            except Exception:
                raise LifecycleOperationError(
                    "build",
                    "lifecycle_pipeline_unavailable",
                    "The lifecycle build pipeline is unavailable.",
                ) from None
        try:
            actor = self.actor_pseudonymizer.pseudonym(strict_principal)
        except Exception:
            raise LifecycleOperationError(
                "authorization",
                "identity_material_unavailable",
                "The trusted actor identity is unavailable.",
            ) from None
        events = tuple(
            item.to_source_event(actor_pseudonym=actor)
            for item in strict_request.events
        )
        materializer = ProductionRevisionContentMaterializer(
            asset_root=self.asset_root
        )
        catalog = PersistentRevisionCatalog(self.catalog_root)
        applications: list[CatalogApplication] = []
        try:
            for source_input, event in zip(
                strict_request.events,
                events,
                strict=True,
            ):
                snapshot = catalog.snapshot()
                disposition = SourceEventLedger.from_snapshot(
                    snapshot.ledger
                ).apply(event)
                if disposition.status == "REPLAYED":
                    applications.append(
                        catalog.apply(event, materialization=None)
                    )
                    continue
                if event.operation == "DELETE":
                    applications.append(
                        catalog.apply(event, materialization=None)
                    )
                    continue
                receipt = admit_source_event_asset(
                    event=event,
                    principal=strict_principal,
                    source_root=self.input_root,
                    storage_root=self.asset_root,
                )
                if receipt.status != "STAGED":
                    raise LifecycleOperationError(
                        "quarantine",
                        "source_quarantined",
                        "A source asset was quarantined.",
                    )
                assert source_input.document_projection is not None
                materialization = materializer.prepare(
                    event=event,
                    receipt=receipt,
                    document_projection=source_input.document_projection,
                    principal=strict_principal,
                )
                applications.append(
                    catalog.apply(
                        event,
                        materialization=materialization,
                    )
                )

            target = catalog.snapshot()
            base, base_run_id = self._active_catalog()
            plan = build_change_plan(
                base=base,
                target=target,
                base_index_run_id=base_run_id,
                target_index_run_id=strict_request.target_run_id,
            )
            publication = execute_incremental_publication(
                root=self.index_root,
                plan=plan,
                base_catalog=base,
                target_catalog=target,
                cache=PersistentComputationCache(self.cache_root),
                pipeline=pipeline,
                materializer=materializer,
                embed_text=embed_text,
                validate_files=lambda: materializer.validate_catalog_files(
                    target
                ),
                profile_id="lifecycle-operator",
                activate=strict_request.activate,
            )
        except LifecycleOperationError:
            raise
        except (SourceEventConflict, CatalogConflict) as exc:
            raise LifecycleOperationError(
                "conflict",
                getattr(exc, "code", "lifecycle_conflict"),
                "The requested lifecycle transition conflicts with current state.",
            ) from None
        except AssetAdmissionError as exc:
            raise LifecycleOperationError(
                "file_validation",
                exc.code,
                "A source asset failed admission.",
            ) from None
        except EmailParseError as exc:
            raise LifecycleOperationError(
                "quarantine",
                exc.code,
                "A staged email was quarantined.",
            ) from None
        except IncrementalComputationError as exc:
            raise LifecycleOperationError(
                "build",
                exc.code,
                "The incremental computation failed.",
            ) from None
        except LifecyclePublicationError as exc:
            category: LifecycleErrorCategory = (
                "activation"
                if "active" in exc.code or "activation" in exc.code
                else "manifest"
            )
            raise LifecycleOperationError(
                category,
                exc.code,
                "The immutable index publication failed.",
            ) from None
        except Exception:
            raise LifecycleOperationError(
                "build",
                "lifecycle_build_failed",
                "The lifecycle build failed.",
            ) from None
        return LifecycleBuildResult(
            operation=(
                "BUILD_AND_ACTIVATE"
                if strict_request.activate
                else "BUILD"
            ),
            run_id=publication.index_manifest.run_id,
            plan_id=plan.plan_id,
            publication_id=publication.lifecycle_manifest.publication_id,
            manifest_sha256=publication.manifest_sha256,
            activated=publication.activated,
            document_count=publication.index_manifest.canonical_document_count,
            chunk_count=publication.index_manifest.chunk_count,
            events=tuple(
                LifecycleEventResult.from_application(application)
                for application in applications
            ),
        )

    def activate_existing(
        self,
        request: LifecycleActivateRequest,
        principal: Principal,
    ) -> LifecycleActivationResult:
        strict_request = LifecycleActivateRequest.model_validate(
            request.model_dump(mode="json")
        )
        strict_principal = Principal.model_validate(
            principal.model_dump(mode="python")
        )
        self._authorize_batch((), strict_principal)
        return self._run_serialized(
            lambda: self._activate_existing_impl(
                strict_request,
                strict_principal,
            )
        )

    def _activate_existing_impl(
        self,
        request: LifecycleActivateRequest,
        principal: Principal,
    ) -> LifecycleActivationResult:
        strict_request = LifecycleActivateRequest.model_validate(
            request.model_dump(mode="json")
        )
        strict_principal = Principal.model_validate(
            principal.model_dump(mode="python")
        )
        self._authorize_batch((), strict_principal)
        try:
            with publication_lock(self.index_root):
                active_path = self.index_root / "active.json"
                current_run_id = (
                    load_index_version(self.index_root).manifest.run_id
                    if active_path.exists()
                    else None
                )
                if current_run_id != strict_request.expected_current_run_id:
                    raise LifecycleOperationError(
                        "conflict",
                        "active_version_conflict",
                        "The active index changed before activation.",
                    )
                target = load_index_version(
                    self.index_root,
                    strict_request.target_run_id,
                )
                lifecycle = validate_incremental_index_directory(target.path)
                catalog = self._current_catalog()
                if (
                    lifecycle.target_catalog_sha256
                    != revision_catalog_sha256(catalog)
                ):
                    raise LifecycleOperationError(
                        "conflict",
                        "target_catalog_stale",
                        "The target index does not represent the current catalog.",
                    )
                pointer = activate_version(
                    self.index_root,
                    strict_request.target_run_id,
                    _lock_held=True,
                )
        except LifecycleOperationError:
            raise
        except FileNotFoundError:
            raise LifecycleOperationError(
                "activation",
                "lifecycle_version_not_found",
                "The requested immutable index version was not found.",
            ) from None
        except Exception:
            raise LifecycleOperationError(
                "activation",
                "activation_failed",
                "The immutable index activation failed.",
            ) from None
        return LifecycleActivationResult(
            run_id=pointer.run_id,
            manifest_sha256=pointer.manifest_sha256,
        )

    def status(self, principal: Principal) -> LifecycleStatusResult:
        strict_principal = Principal.model_validate(
            principal.model_dump(mode="python")
        )
        self._authorize_batch((), strict_principal)
        return self._run_serialized(
            lambda: self._status_impl(strict_principal)
        )

    def _status_impl(self, principal: Principal) -> LifecycleStatusResult:
        strict_principal = Principal.model_validate(
            principal.model_dump(mode="python")
        )
        self._authorize_batch((), strict_principal)
        try:
            if (
                self.index_root / "audit" / "rollback.intent.json"
            ).exists():
                recover_pending_rollback(root=self.index_root)
            catalog = self._current_catalog()
            catalog_sha256 = revision_catalog_sha256(catalog)
            live_source_count = sum(
                not head.deleted for head in catalog.ledger.source_heads
            )
            tombstone_count = sum(
                head.deleted for head in catalog.ledger.source_heads
            )
            if not (self.index_root / "active.json").exists():
                return LifecycleStatusResult(
                    state=(
                        "EMPTY"
                        if not catalog.ledger.receipts
                        else "INDEX_UPDATE_PENDING"
                    ),
                    catalog_sha256=catalog_sha256,
                    catalog_event_count=len(catalog.ledger.receipts),
                    live_source_count=live_source_count,
                    tombstone_count=tombstone_count,
                )
            active = load_index_version(self.index_root)
            lifecycle = validate_incremental_index_directory(active.path)
            return LifecycleStatusResult(
                state=(
                    "SYNCHRONIZED"
                    if lifecycle.target_catalog_sha256 == catalog_sha256
                    else "INDEX_UPDATE_PENDING"
                ),
                catalog_sha256=catalog_sha256,
                catalog_event_count=len(catalog.ledger.receipts),
                live_source_count=live_source_count,
                tombstone_count=tombstone_count,
                active_run_id=active.manifest.run_id,
                active_manifest_sha256=active.manifest_sha256,
                active_catalog_sha256=lifecycle.target_catalog_sha256,
            )
        except LifecycleOperationError:
            raise
        except Exception:
            raise LifecycleOperationError(
                "manifest",
                "lifecycle_state_invalid",
                "The lifecycle state failed validation.",
            ) from None

    def rollback(
        self,
        request: LifecycleRollbackRequest,
        principal: Principal,
    ) -> LifecycleRollbackResult:
        strict_request = LifecycleRollbackRequest.model_validate(
            request.model_dump(mode="json")
        )
        strict_principal = Principal.model_validate(
            principal.model_dump(mode="python")
        )
        self._authorize_batch((), strict_principal)
        return self._run_serialized(
            lambda: self._rollback_impl(strict_request, strict_principal)
        )

    def _rollback_impl(
        self,
        request: LifecycleRollbackRequest,
        principal: Principal,
    ) -> LifecycleRollbackResult:
        strict_request = LifecycleRollbackRequest.model_validate(
            request.model_dump(mode="json")
        )
        strict_principal = Principal.model_validate(
            principal.model_dump(mode="python")
        )
        self._authorize_batch((), strict_principal)
        try:
            result = rollback_index_version(
                root=self.index_root,
                target_run_id=strict_request.target_run_id,
                expected_current_run_id=(
                    strict_request.expected_current_run_id
                ),
            )
        except FileNotFoundError:
            raise LifecycleOperationError(
                "rollback",
                "lifecycle_version_not_found",
                "The requested immutable index version was not found.",
            ) from None
        except LifecyclePublicationError as exc:
            if exc.code == "rollback_source_conflict":
                category: LifecycleErrorCategory = "conflict"
                code = "active_version_conflict"
            elif exc.code == "rollback_outcome_unknown":
                category = "rollback"
                code = "activation_outcome_unknown"
            else:
                category = "rollback"
                code = exc.code
            raise LifecycleOperationError(
                category,
                code,
                "The rollback operation did not complete normally.",
            ) from None
        except Exception:
            raise LifecycleOperationError(
                "rollback",
                "rollback_failed",
                "The rollback operation failed.",
            ) from None
        return LifecycleRollbackResult(
            from_run_id=result.audit_event.from_run_id,
            to_run_id=result.audit_event.to_run_id,
            manifest_sha256=result.pointer_manifest_sha256,
            audit_event_sha256=result.audit_event.event_sha256,
        )

    def _run_serialized(self, operation: Callable[[], object]):
        acquired = False
        try:
            with publication_lock(
                self.operation_lock_root,
                timeout_seconds=self.operation_lock_timeout_seconds,
            ):
                acquired = True
                return operation()
        except LifecycleOperationError:
            raise
        except TimeoutError:
            if acquired:
                raise
            raise LifecycleOperationError(
                "conflict",
                "lifecycle_operation_busy",
                "Another lifecycle operation is in progress.",
            ) from None
        except (OSError, PermissionError):
            if acquired:
                raise
            raise LifecycleOperationError(
                "manifest",
                "lifecycle_operation_lock_failed",
                "The lifecycle operation lock is unavailable.",
            ) from None

    def _authorize_batch(
        self,
        events: tuple[OperatorSourceEventInput, ...],
        principal: Principal,
    ) -> None:
        if self.operator_role not in principal.roles:
            raise LifecycleOperationError(
                "authorization",
                "operator_role_required",
                "The authenticated principal lacks the operator role.",
            )
        for event in events:
            if event.tenant_id != principal.tenant_id:
                raise LifecycleOperationError(
                    "authorization",
                    "tenant_mismatch",
                    "The authenticated principal cannot operate on this tenant.",
                )
            if event.region != principal.region:
                raise LifecycleOperationError(
                    "authorization",
                    "region_mismatch",
                    "The authenticated principal cannot operate in this region.",
                )

    def _current_catalog(self) -> RevisionCatalogSnapshot:
        if not self.catalog_root.exists():
            return empty_revision_catalog_snapshot()
        return load_revision_catalog_snapshot_read_only(self.catalog_root)

    def _active_catalog(self) -> tuple[RevisionCatalogSnapshot, str | None]:
        if not (self.index_root / "active.json").exists():
            return empty_revision_catalog_snapshot(), None
        loaded = load_index_version(self.index_root)
        validate_incremental_index_directory(loaded.path)
        raw = (loaded.path / "revision_catalog.json").read_bytes()
        catalog = RevisionCatalogSnapshot.model_validate_json(raw)
        run_id = loaded.manifest.run_id if catalog.ledger.receipts else None
        return catalog, run_id

    @staticmethod
    def _preview_applications(
        base: RevisionCatalogSnapshot,
        events: tuple[SourceEvent, ...],
    ) -> tuple[Literal["APPLIED", "REPLAYED"], ...]:
        ledger = SourceEventLedger.from_snapshot(base.ledger)
        return tuple(ledger.apply(event).status for event in events)

    @staticmethod
    def _exact_preview_target(
        base: RevisionCatalogSnapshot,
        events: tuple[SourceEvent, ...],
    ) -> RevisionCatalogSnapshot:
        target = base
        for event in events:
            target = apply_revision_catalog_snapshot(
                target,
                event,
                materialization=None,
            ).snapshot
        return target


__all__ = [
    "LifecycleActivateRequest",
    "LifecycleActivationResult",
    "LifecycleBuildRequest",
    "LifecycleBuildResult",
    "LifecycleEventResult",
    "LifecycleOperationError",
    "LifecycleOperatorService",
    "LifecyclePlanProposal",
    "LifecyclePreviewRequest",
    "LifecyclePreviewResult",
    "LifecycleRollbackRequest",
    "LifecycleRollbackResult",
    "LifecycleStatusResult",
    "OperatorSourceEventInput",
    "OperatorSourceEventTemplateInput",
]
