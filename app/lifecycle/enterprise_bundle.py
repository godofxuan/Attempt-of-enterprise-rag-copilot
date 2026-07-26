from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ingestion.email_parser import (
    EmailParseError,
    inspect_email_decoded_surfaces,
)
from app.lifecycle.operator import (
    OperatorSourceEventInput,
    OperatorSourceEventTemplateInput,
)


_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_ASSET_BYTES = 16 * 1024 * 1024
_MAX_TOTAL_ASSET_BYTES = 64 * 1024 * 1024
_EMAIL_ADDRESS = re.compile(
    rb"(?i)(?<![A-Z0-9._%+-])"
    rb"[A-Z0-9._%+-]+@(\[[^\]\r\n]{1,255}\]|[A-Z0-9.-]{1,255})"
)
_WINDOWS_SEPARATOR = bytes((92,))
_PRIVATE_MARKERS = (
    b"c:" + _WINDOWS_SEPARATOR + b"users" + _WINDOWS_SEPARATOR,
    b"/users/",
    b"/home/",
    b"begin private key",
    b"authorization: bearer",
    b"sk-",
)


class EnterpriseBundleModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class EnterpriseBundleError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class EnterpriseBundleAsset(EnterpriseBundleModel):
    schema_version: Literal["enterprise_bundle_asset_v1"] = (
        "enterprise_bundle_asset_v1"
    )
    asset_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    domain: Literal["policy", "project", "operations", "email"]
    path: str = Field(min_length=1, max_length=512)
    media_type: str = Field(min_length=1, max_length=128)
    byte_count: int = Field(ge=1, le=_MAX_ASSET_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_path(self) -> EnterpriseBundleAsset:
        candidate = PurePosixPath(self.path)
        if (
            candidate.is_absolute()
            or not candidate.parts
            or candidate.parts[0] != "sources"
            or any(part in {"", ".", ".."} for part in candidate.parts)
            or "\\" in self.path
        ):
            raise ValueError("bundle asset path must be contained under sources")
        return self


class EnterpriseBundleEvent(EnterpriseBundleModel):
    schema_version: Literal["enterprise_bundle_event_v1"] = (
        "enterprise_bundle_event_v1"
    )
    batch: Literal["initial", "change"]
    event: OperatorSourceEventTemplateInput
    expected_revision_from_event_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_revision_reference(self) -> EnterpriseBundleEvent:
        if self.event.expected_revision_id is not None:
            raise ValueError(
                "bundle events use symbolic expected revision references"
            )
        if self.batch == "initial" and self.expected_revision_from_event_id:
            raise ValueError("initial bundle event cannot reference a revision")
        if self.batch == "change" and not self.expected_revision_from_event_id:
            raise ValueError("change bundle event requires a revision reference")
        return self


class EnterpriseBundleQuery(EnterpriseBundleModel):
    schema_version: Literal["enterprise_bundle_query_v1"] = (
        "enterprise_bundle_query_v1"
    )
    query_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    query: str = Field(min_length=1, max_length=512)
    purpose: str = Field(min_length=1, max_length=256)
    groups: tuple[str, ...] = Field(min_length=1, max_length=32)
    expected_source_key_in_initial: str = Field(min_length=1, max_length=256)


class EnterpriseBundleManifest(EnterpriseBundleModel):
    schema_version: Literal["enterprise_lifecycle_bundle_v1"] = (
        "enterprise_lifecycle_bundle_v1"
    )
    bundle_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,127}$")
    producer: Literal["enterprise_agentic_rag_v2"]
    synthetic: Literal[True]
    identity_policy: Literal["fictional-example-invalid-v1"]
    tenant_id: str = Field(min_length=1, max_length=128)
    region: str = Field(min_length=1, max_length=64)
    assets: tuple[EnterpriseBundleAsset, ...] = Field(
        min_length=1,
        max_length=100,
    )
    events: tuple[EnterpriseBundleEvent, ...] = Field(
        min_length=1,
        max_length=1000,
    )
    fixed_queries: tuple[EnterpriseBundleQuery, ...] = Field(
        min_length=1,
        max_length=32,
    )

    @model_validator(mode="after")
    def validate_manifest_graph(self) -> EnterpriseBundleManifest:
        asset_ids = [asset.asset_id for asset in self.assets]
        asset_paths = [asset.path for asset in self.assets]
        event_ids = [item.event.event_id for item in self.events]
        query_ids = [query.query_id for query in self.fixed_queries]
        for values, label in (
            (asset_ids, "asset IDs"),
            (asset_paths, "asset paths"),
            (event_ids, "event IDs"),
            (query_ids, "query IDs"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"bundle {label} must be unique")

        assets_by_path = {asset.path: asset for asset in self.assets}
        events_by_id: dict[str, OperatorSourceEventTemplateInput] = {}
        referenced_assets: set[str] = set()
        seen_change = False
        for item in self.events:
            event = item.event
            if item.batch == "change":
                seen_change = True
            elif seen_change:
                raise ValueError("initial events must precede change events")
            if event.tenant_id != self.tenant_id or event.region != self.region:
                raise ValueError("bundle event scope differs from manifest")
            if event.operation == "UPSERT":
                assert event.content_relpath is not None
                asset = assets_by_path.get(event.content_relpath)
                if (
                    asset is None
                    or asset.media_type != event.declared_media_type
                    or asset.sha256 != event.content_sha256
                ):
                    raise ValueError("bundle event is not bound to its asset")
                referenced_assets.add(asset.path)
            reference = item.expected_revision_from_event_id
            if reference is not None:
                prior = events_by_id.get(reference)
                if prior is None:
                    raise ValueError("bundle revision reference is not earlier")
                if (
                    prior.tenant_id,
                    prior.region,
                    prior.source_system,
                    prior.source_key,
                ) != (
                    event.tenant_id,
                    event.region,
                    event.source_system,
                    event.source_key,
                ):
                    raise ValueError(
                        "bundle revision reference changes source identity"
                    )
            events_by_id[event.event_id] = event
        if referenced_assets != set(asset_paths):
            raise ValueError("every bundle asset must be referenced once or later")
        initial_upserts = [
            item.event
            for item in self.events
            if item.batch == "initial" and item.event.operation == "UPSERT"
        ]
        for query in self.fixed_queries:
            matches = [
                event
                for event in initial_upserts
                if event.source_key == query.expected_source_key_in_initial
            ]
            if len(matches) != 1:
                raise ValueError(
                    "bundle query must bind exactly one initial UPSERT source"
                )
        return self


class EnterpriseLifecyclePublicSummary(EnterpriseBundleModel):
    schema_version: Literal["enterprise_lifecycle_g9_summary_v1"] = (
        "enterprise_lifecycle_g9_summary_v1"
    )
    bundle_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,127}$")
    bundle_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    synthetic: Literal[True]
    embedding_backend: Literal["deterministic-test"]
    initial_run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    changed_run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    catalog_advanced: Literal[True]
    exact_retry_plan_match: Literal[True]
    exact_retry_publication_match: Literal[True]
    stale_activation_rejected: Literal[True]
    rollback_manifest_restored: Literal[True]
    initial_event_count: int = Field(ge=1)
    replayed_event_count: int = Field(ge=1)
    change_event_count: int = Field(ge=1)
    initial_document_count: int = Field(ge=1)
    changed_document_count: int = Field(ge=0)
    active_index_deleted_residual_count: Literal[0]
    initial_query_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    changed_query_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    restored_query_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rollback_audit_event_count: Literal[1]

    @model_validator(mode="after")
    def validate_scenario_result(self) -> EnterpriseLifecyclePublicSummary:
        if self.initial_run_id == self.changed_run_id:
            raise ValueError("G9 run IDs must be distinct")
        if self.replayed_event_count != self.initial_event_count:
            raise ValueError("G9 must replay every initial event")
        if self.changed_document_count >= self.initial_document_count:
            raise ValueError("G9 deletion must reduce the document count")
        if (
            self.restored_query_fingerprint_sha256
            != self.initial_query_fingerprint_sha256
        ):
            raise ValueError("G9 rollback did not restore the fixed query")
        if (
            self.changed_query_fingerprint_sha256
            == self.initial_query_fingerprint_sha256
        ):
            raise ValueError("G9 changed query fingerprint did not change")
        return self


def canonical_enterprise_bundle_manifest_bytes(
    manifest: EnterpriseBundleManifest,
) -> bytes:
    validated = EnterpriseBundleManifest.model_validate(
        manifest.model_dump(mode="json")
    )
    return (
        json.dumps(
            validated.model_dump(mode="json"),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def canonical_enterprise_lifecycle_summary_bytes(
    summary: EnterpriseLifecyclePublicSummary,
) -> bytes:
    validated = EnterpriseLifecyclePublicSummary.model_validate(
        summary.model_dump(mode="json")
    )
    return (
        json.dumps(
            validated.model_dump(mode="json"),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


@dataclass(frozen=True)
class LoadedEnterpriseBundle:
    root: Path
    manifest: EnterpriseBundleManifest
    manifest_sha256: str

    def batch(
        self,
        name: Literal["initial", "change"],
    ) -> tuple[OperatorSourceEventInput, ...]:
        if name == "change" and any(
            item.expected_revision_from_event_id is not None
            for item in self.manifest.events
            if item.batch == name
        ):
            raise EnterpriseBundleError(
                "bundle_revision_resolution_required",
                "The change batch requires accepted revision IDs.",
            )
        return tuple(
            OperatorSourceEventInput.model_validate(
                item.event.model_dump(mode="python")
            )
            for item in self.manifest.events
            if item.batch == name
        )

    def resolve_batch(
        self,
        name: Literal["initial", "change"],
        *,
        accepted_revisions: Mapping[str, str],
    ) -> tuple[OperatorSourceEventInput, ...]:
        resolved = []
        for item in self.manifest.events:
            if item.batch != name:
                continue
            reference = item.expected_revision_from_event_id
            if reference is None:
                resolved.append(
                    OperatorSourceEventInput.model_validate(
                        item.event.model_dump(mode="python")
                    )
                )
                continue
            revision_id = accepted_revisions.get(reference)
            if revision_id is None:
                raise EnterpriseBundleError(
                    "bundle_revision_unavailable",
                    "An accepted revision required by the bundle is unavailable.",
                )
            resolved.append(
                OperatorSourceEventInput.model_validate(
                    item.event.model_copy(
                        update={"expected_revision_id": revision_id}
                    ).model_dump(mode="python")
                )
            )
        return tuple(resolved)

    def query(self, query_id: str) -> EnterpriseBundleQuery:
        for query in self.manifest.fixed_queries:
            if query.query_id == query_id:
                return query
        raise EnterpriseBundleError(
            "bundle_query_unknown",
            "The requested fixed query is not in the bundle.",
        )

    def expected_initial_event(
        self,
        query_id: str,
    ) -> OperatorSourceEventTemplateInput:
        query = self.query(query_id)
        matches = [
            item.event
            for item in self.manifest.events
            if (
                item.batch == "initial"
                and item.event.operation == "UPSERT"
                and item.event.source_key
                == query.expected_source_key_in_initial
            )
        ]
        if len(matches) != 1:
            raise EnterpriseBundleError(
                "bundle_query_source_invalid",
                "The fixed query source binding is invalid.",
            )
        return matches[0]


def _read_regular_file(path: Path, *, byte_limit: int) -> bytes:
    descriptor: int | None = None
    try:
        expected = path.lstat()
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        current = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or not os.path.samestat(expected, opened)
            or not os.path.samestat(opened, current)
            or opened.st_size > byte_limit
        ):
            raise EnterpriseBundleError(
                "bundle_file_unsafe",
                "A bundle file is not a bounded regular file.",
            )
        chunks: list[bytes] = []
        remaining = byte_limit + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(payload) > byte_limit
            or len(payload) != opened.st_size
            or not os.path.samestat(opened, after)
            or opened.st_size != after.st_size
            or getattr(opened, "st_mtime_ns", None)
            != getattr(after, "st_mtime_ns", None)
        ):
            raise EnterpriseBundleError(
                "bundle_file_changed",
                "A bundle file changed during validation.",
            )
        return payload
    except EnterpriseBundleError:
        raise
    except OSError as exc:
        raise EnterpriseBundleError(
            "bundle_file_unavailable",
            "A bundle file is unavailable.",
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _validate_fictional_content(
    content: bytes,
    *,
    require_utf8: bool = True,
) -> None:
    lowered = content.lower()
    if any(marker in lowered for marker in _PRIVATE_MARKERS):
        raise EnterpriseBundleError(
            "bundle_private_marker_detected",
            "A private or credential marker was found in the bundle.",
        )
    if any(
        match.group(1).lower() != b"example.invalid"
        for match in _EMAIL_ADDRESS.finditer(content)
    ):
        raise EnterpriseBundleError(
            "bundle_identity_policy_failed",
            "A bundle email address is outside example.invalid.",
        )
    if require_utf8:
        content.decode("utf-8")


def _contained_asset_path(root: Path, relative_path: str) -> Path:
    current = root
    parts = PurePosixPath(relative_path).parts
    try:
        for index, part in enumerate(parts):
            current = current / part
            metadata = current.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise EnterpriseBundleError(
                    "bundle_asset_path_invalid",
                    "A bundle asset path contains a symbolic link.",
                )
            if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
                raise EnterpriseBundleError(
                    "bundle_asset_path_invalid",
                    "A bundle asset parent is not a directory.",
                )
        current.resolve(strict=True).relative_to(root)
        return current
    except EnterpriseBundleError:
        raise
    except (OSError, ValueError) as exc:
        raise EnterpriseBundleError(
            "bundle_asset_path_invalid",
            "A bundle asset path escapes or is unavailable.",
        ) from exc


def load_enterprise_bundle(root: Path) -> LoadedEnterpriseBundle:
    candidate = Path(root)
    try:
        root_metadata = candidate.lstat()
        if candidate.is_symlink() or not stat.S_ISDIR(root_metadata.st_mode):
            raise EnterpriseBundleError(
                "bundle_root_unsafe",
                "The enterprise bundle root is unsafe.",
            )
        resolved_root = candidate.resolve(strict=True)
    except EnterpriseBundleError:
        raise
    except OSError as exc:
        raise EnterpriseBundleError(
            "bundle_root_unavailable",
            "The enterprise bundle root is unavailable.",
        ) from exc

    manifest_raw = _read_regular_file(
        resolved_root / "manifest.json",
        byte_limit=_MAX_MANIFEST_BYTES,
    )
    try:
        manifest = EnterpriseBundleManifest.model_validate_json(manifest_raw)
    except Exception as exc:
        raise EnterpriseBundleError(
            "bundle_manifest_invalid",
            "The enterprise bundle manifest failed strict validation.",
        ) from exc
    if manifest_raw != canonical_enterprise_bundle_manifest_bytes(manifest):
        raise EnterpriseBundleError(
            "bundle_manifest_noncanonical",
            "The enterprise bundle manifest is not canonical.",
        )

    total_bytes = 0
    for asset in manifest.assets:
        asset_path = _contained_asset_path(resolved_root, asset.path)
        content = _read_regular_file(
            asset_path,
            byte_limit=_MAX_ASSET_BYTES,
        )
        total_bytes += len(content)
        if (
            len(content) != asset.byte_count
            or hashlib.sha256(content).hexdigest() != asset.sha256
        ):
            raise EnterpriseBundleError(
                "bundle_asset_integrity_failed",
                "A bundle asset does not match its manifest.",
            )
        try:
            _validate_fictional_content(content)
            if asset.media_type == "message/rfc822":
                for surface in inspect_email_decoded_surfaces(content):
                    _validate_fictional_content(
                        surface,
                        require_utf8=False,
                    )
        except EmailParseError as exc:
            raise EnterpriseBundleError(
                "bundle_email_inspection_failed",
                "A fictional email failed decoded-content inspection.",
            ) from exc
        except UnicodeDecodeError as exc:
            raise EnterpriseBundleError(
                "bundle_asset_encoding_invalid",
                "A fictional bundle asset is not UTF-8.",
            ) from exc
    if total_bytes > _MAX_TOTAL_ASSET_BYTES:
        raise EnterpriseBundleError(
            "bundle_total_size_exceeded",
            "The enterprise bundle exceeds its total byte budget.",
        )
    return LoadedEnterpriseBundle(
        root=resolved_root,
        manifest=manifest,
        manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
    )


__all__ = [
    "EnterpriseBundleAsset",
    "EnterpriseBundleError",
    "EnterpriseBundleEvent",
    "EnterpriseBundleManifest",
    "EnterpriseBundleQuery",
    "EnterpriseLifecyclePublicSummary",
    "LoadedEnterpriseBundle",
    "canonical_enterprise_bundle_manifest_bytes",
    "canonical_enterprise_lifecycle_summary_bytes",
    "load_enterprise_bundle",
]
