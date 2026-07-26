from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.domain.documents import DocumentRecord, DocumentVersion
from app.lifecycle.performance_bundle import (
    PerformanceBundleError,
    PerformanceBundleManifest,
    PerformanceBundleRevisionContentMaterializer,
    canonical_performance_bundle_manifest_bytes,
    generate_performance_bundle,
    load_performance_bundle,
)
from app.ingestion.revision_catalog import (
    apply_revision_catalog_snapshot,
    empty_revision_catalog_snapshot,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _document(number: int) -> DocumentRecord:
    text = f"Lifecycle benchmark document {number:04d} stable retrieval token."
    text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return DocumentRecord(
        doc_id=f"doc-{number:04d}",
        title=f"Benchmark Document {number:04d}",
        source_type="policy",
        source_path=f"fixture/policy-{number:04d}.md",
        format="markdown",
        department="Engineering",
        filed_department="Engineering",
        policy_id=f"policy-{number:04d}",
        region="global",
        tenant_id="tenant-fixture",
        acl_groups=["employees"],
        document_version=DocumentVersion(
            version_id=f"version-{number:04d}",
            version="1",
            status="active",
            effective_from=date(2026, 1, 1),
            authority_level=80,
        ),
        authority_level=80,
        checksum=text_sha256,
        normalized_text_hash=text_sha256,
        ingested_at=NOW,
        parser_name="fixture-markdown",
        parser_version="1",
        text=text,
        fact_ids=[f"fact-{number:04d}"],
        variant="canonical",
    )


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _rebind_file(root: Path, name: str, payload: object) -> None:
    content = _canonical_json(payload)
    (root / name).write_bytes(content)
    manifest_path = root / "manifest.json"
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest_payload["files"]:
        if item["path"] == name:
            item["byte_count"] = len(content)
            item["sha256"] = hashlib.sha256(content).hexdigest()
    manifest = PerformanceBundleManifest.model_validate(manifest_payload)
    manifest_path.write_bytes(
        canonical_performance_bundle_manifest_bytes(manifest)
    )


def _small_bundle(root: Path):
    return generate_performance_bundle(
        [_document(number) for number in range(1, 13)],
        root,
        content_update_count=3,
        acl_only_count=2,
        delete_count=1,
    )


def test_generation_is_byte_identical_and_uses_disjoint_categories(
    tmp_path: Path,
) -> None:
    documents = [_document(number) for number in range(1, 13)]
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"

    generate_performance_bundle(
        documents,
        first_root,
        content_update_count=3,
        acl_only_count=2,
        delete_count=1,
    )
    generate_performance_bundle(
        list(reversed(documents)),
        second_root,
        content_update_count=3,
        acl_only_count=2,
        delete_count=1,
    )
    first = load_performance_bundle(first_root)
    second = load_performance_bundle(second_root)

    assert _tree_bytes(first_root) == _tree_bytes(second_root)
    assert first.manifest == second.manifest
    assert first.manifest.counts.base_document_count == 12
    assert first.manifest.counts.target_live_document_count == 11
    assert first.manifest.counts.content_update_count == 3
    assert first.manifest.counts.acl_only_count == 2
    assert first.manifest.counts.delete_count == 1
    assert first.manifest.counts.unchanged_count == 6
    categories = first.change_descriptor.categories
    identities = (
        *categories.content_updates,
        *categories.acl_only_updates,
        *categories.deletes,
        *categories.unchanged,
    )
    assert len(identities) == len(set(identities)) == 12


def test_generation_canonicalizes_set_lists_and_normalized_text_hash(
    tmp_path: Path,
) -> None:
    documents = [_document(number) for number in range(1, 13)]
    first = documents[0].model_copy(
        update={
            "acl_groups": ["z-readers", "a-readers"],
            "fact_ids": ["z-fact", "a-fact"],
            "text": f"  {documents[0].text}  ",
            "checksum": "1" * 64,
            "normalized_text_hash": "2" * 64,
        },
        deep=True,
    )
    bundle = generate_performance_bundle(
        [first, *documents[1:]],
        tmp_path / "canonicalized",
        content_update_count=3,
        acl_only_count=2,
        delete_count=1,
    )
    entry = next(
        item
        for item in bundle.base_documents.entries
        if item.document.doc_id == first.doc_id
    )
    oracle_token = entry.document.text.split()[-1]
    assert oracle_token.startswith("g10oracle")
    expected_text = f"{first.text.strip()}\n\n{oracle_token}"
    expected_sha256 = hashlib.sha256(
        expected_text.encode("utf-8")
    ).hexdigest()

    assert entry.document.acl_groups == ["a-readers", "z-readers"]
    assert entry.document.fact_ids == ["a-fact", "z-fact"]
    assert entry.document.text == expected_text
    assert entry.document.checksum == expected_sha256
    assert entry.document.normalized_text_hash == expected_sha256


def test_linear_bundle_catalog_matches_public_per_event_oracle(
    tmp_path: Path,
) -> None:
    bundle = _small_bundle(tmp_path / "bundle")
    base_entries = {
        entry.source_key: entry for entry in bundle.base_documents.entries
    }
    base_revisions = {
        revision.revision_id: revision
        for revision in bundle.base_catalog.revisions
    }
    oracle_base = empty_revision_catalog_snapshot()
    for event in bundle.change_descriptor.base_events:
        entry = base_entries[event.source_key]
        oracle_base = apply_revision_catalog_snapshot(
            oracle_base,
            event,
            materialization=base_revisions[entry.revision_id].materialization,
        ).snapshot
    assert oracle_base == bundle.base_catalog

    target_entries = {
        entry.source_key: entry for entry in bundle.target_documents.entries
    }
    target_revisions = {
        revision.revision_id: revision
        for revision in bundle.target_catalog.revisions
    }
    oracle_target = oracle_base
    for event in bundle.change_descriptor.change_events:
        materialization = None
        if event.operation == "UPSERT":
            entry = target_entries[event.source_key]
            materialization = target_revisions[
                entry.revision_id
            ].materialization
        oracle_target = apply_revision_catalog_snapshot(
            oracle_target,
            event,
            materialization=materialization,
        ).snapshot
    assert oracle_target == bundle.target_catalog


def test_load_rejects_hash_rebound_payload_that_disagrees_with_catalog(
    tmp_path: Path,
) -> None:
    original = tmp_path / "original"
    tampered = tmp_path / "tampered"
    generate_performance_bundle(
        [_document(number) for number in range(1, 13)],
        original,
        content_update_count=3,
        acl_only_count=2,
        delete_count=1,
    )
    shutil.copytree(original, tampered)
    descriptor = json.loads(
        (tampered / "change_descriptor.json").read_text(encoding="utf-8")
    )
    unchanged_source = descriptor["categories"]["unchanged"][0]
    target = json.loads(
        (tampered / "target_documents.json").read_text(encoding="utf-8")
    )
    entry = next(
        item for item in target["entries"] if item["source_key"] == unchanged_source
    )
    entry["document"]["acl_groups"].append("tampered-group")
    entry["document"]["acl_groups"].sort()
    _rebind_file(tampered, "target_documents.json", target)

    with pytest.raises(PerformanceBundleError) as captured:
        load_performance_bundle(tampered)

    assert captured.value.code == "bundle_payload_catalog_mismatch"


def test_read_only_materializer_reuses_acl_only_content(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bundle"
    bundle = generate_performance_bundle(
        [_document(number) for number in range(1, 13)],
        root,
        content_update_count=3,
        acl_only_count=2,
        delete_count=1,
    )
    source_key = bundle.change_descriptor.categories.acl_only_updates[0]
    base_heads = {
        head.source_key: head for head in bundle.base_catalog.ledger.source_heads
    }
    target_heads = {
        head.source_key: head for head in bundle.target_catalog.ledger.source_heads
    }
    base_revisions = {
        revision.revision_id: revision
        for revision in bundle.base_catalog.revisions
    }
    target_revisions = {
        revision.revision_id: revision
        for revision in bundle.target_catalog.revisions
    }
    base_revision = base_revisions[base_heads[source_key].current_revision_id]
    target_revision = target_revisions[target_heads[source_key].current_revision_id]
    before = _tree_bytes(root)
    base_materializer = PerformanceBundleRevisionContentMaterializer(
        bundle,
        role="base",
    )
    target_materializer = PerformanceBundleRevisionContentMaterializer(
        bundle,
        role="target",
    )

    base_parsed = base_materializer.parse_content(base_revision)
    target_parsed = target_materializer.parse_content(target_revision)
    base_normalized = base_materializer.normalize_content(
        base_revision,
        base_parsed,
    )
    target_normalized = target_materializer.normalize_content(
        target_revision,
        target_parsed,
    )
    base_document = base_materializer.materialize_document(
        base_revision,
        base_normalized,
    )
    target_document = target_materializer.materialize_document(
        target_revision,
        target_normalized,
    )

    parser_fingerprint = base_materializer.parser_fingerprint(base_revision)
    assert parser_fingerprint.name == base_revision.materialization.parser_name
    assert parser_fingerprint.semantic_version == (
        base_revision.materialization.parser_version
    )
    assert parser_fingerprint.implementation_sha256 == (
        bundle.manifest.pipeline.parser.implementation_sha256
    )
    assert base_parsed == target_parsed
    assert base_normalized == target_normalized
    assert base_document.text == target_document.text
    assert base_document.checksum == target_document.checksum
    assert base_document.acl_groups != target_document.acl_groups
    assert base_revision.revision_id != target_revision.revision_id
    assert _tree_bytes(root) == before


def test_load_rejects_rebound_generator_identity(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    generate_performance_bundle(
        [_document(number) for number in range(1, 13)],
        root,
        content_update_count=3,
        acl_only_count=2,
        delete_count=1,
    )
    manifest_path = root / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["generator"]["implementation_sha256"] = "0" * 64
    manifest = PerformanceBundleManifest.model_validate(payload)
    manifest_path.write_bytes(
        canonical_performance_bundle_manifest_bytes(manifest)
    )

    with pytest.raises(PerformanceBundleError) as captured:
        load_performance_bundle(root)

    assert captured.value.code == "bundle_identity_mismatch"


@pytest.mark.parametrize("mutation", ["extra", "missing"])
def test_load_rejects_extra_and_missing_files(
    tmp_path: Path,
    mutation: str,
) -> None:
    root = tmp_path / "bundle"
    _small_bundle(root)
    if mutation == "extra":
        (root / "extra.json").write_bytes(b"{}")
    else:
        (root / "query_descriptor.json").unlink()

    with pytest.raises(PerformanceBundleError):
        load_performance_bundle(root)


@pytest.mark.parametrize("mutation", ["hash", "size"])
def test_load_rejects_hash_and_size_mismatch(
    tmp_path: Path,
    mutation: str,
) -> None:
    root = tmp_path / "bundle"
    _small_bundle(root)
    target = root / "query_descriptor.json"
    content = target.read_bytes()
    target.write_bytes(
        (b"X" + content[1:]) if mutation == "hash" else (content + b"\n")
    )

    with pytest.raises(PerformanceBundleError) as captured:
        load_performance_bundle(root)

    assert captured.value.code == "bundle_file_integrity_failed"


def test_load_rejects_schema_extra_and_rebound_count_mismatch(
    tmp_path: Path,
) -> None:
    schema_root = tmp_path / "schema"
    count_root = tmp_path / "count"
    _small_bundle(schema_root)
    shutil.copytree(schema_root, count_root)

    query_payload = json.loads(
        (schema_root / "query_descriptor.json").read_text(encoding="utf-8")
    )
    query_payload["unexpected"] = True
    _rebind_file(schema_root, "query_descriptor.json", query_payload)
    with pytest.raises(PerformanceBundleError) as schema_error:
        load_performance_bundle(schema_root)
    assert schema_error.value.code == "bundle_query_descriptor_invalid"

    manifest_path = count_root / "manifest.json"
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    counts = manifest_payload["counts"]
    counts["base_document_count"] = 13
    counts["target_live_document_count"] = 12
    counts["base_event_count"] = 13
    counts["target_event_count"] = 19
    counts["unchanged_count"] = 7
    manifest = PerformanceBundleManifest.model_validate(manifest_payload)
    manifest_path.write_bytes(
        canonical_performance_bundle_manifest_bytes(manifest)
    )
    with pytest.raises(PerformanceBundleError) as count_error:
        load_performance_bundle(count_root)
    assert count_error.value.code == "bundle_count_mismatch"


def test_load_rejects_category_overlap_after_hash_rebinding(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bundle"
    bundle = _small_bundle(root)
    payload = json.loads(
        (root / "change_descriptor.json").read_text(encoding="utf-8")
    )
    payload["categories"]["deletes"][0] = (
        bundle.change_descriptor.categories.content_updates[0]
    )
    payload["categories"]["deletes"].sort()
    _rebind_file(root, "change_descriptor.json", payload)

    with pytest.raises(PerformanceBundleError) as captured:
        load_performance_bundle(root)

    assert captured.value.code == "bundle_change_descriptor_invalid"


def test_load_rejects_manifest_path_escape(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    _small_bundle(root)
    manifest_path = root / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["files"][0]["path"] = "../outside.json"
    manifest_path.write_bytes(_canonical_json(payload))

    with pytest.raises(PerformanceBundleError) as captured:
        load_performance_bundle(root)

    assert captured.value.code == "bundle_manifest_invalid"


def test_load_rejects_internal_file_hardlink(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    _small_bundle(root)
    target = root / "base_catalog.json"
    outside = tmp_path / "outside.json"
    target.replace(outside)
    try:
        os.link(outside, target)
    except OSError:
        pytest.skip("hardlink creation is unavailable on this platform")

    with pytest.raises(PerformanceBundleError) as captured:
        load_performance_bundle(root)

    assert captured.value.code == "bundle_file_unsafe"


def test_load_rejects_internal_file_symlink(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    _small_bundle(root)
    target = root / "base_catalog.json"
    outside = tmp_path / "outside.json"
    target.replace(outside)
    try:
        os.symlink(outside, target)
    except OSError:
        pytest.skip("symlink creation is unavailable on this platform")

    with pytest.raises(PerformanceBundleError) as captured:
        load_performance_bundle(root)

    assert captured.value.code == "bundle_file_unsafe"


def test_load_rejects_redirected_parent_component(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    _small_bundle(real_parent / "bundle")
    redirected_parent = tmp_path / "redirected"
    try:
        os.symlink(real_parent, redirected_parent, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink creation is unavailable on this platform")

    with pytest.raises(PerformanceBundleError) as captured:
        load_performance_bundle(redirected_parent / "bundle")

    assert captured.value.code == "bundle_root_unsafe"


def test_generation_rejects_nonempty_target_without_overwrite(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    sentinel = root / "sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")

    with pytest.raises(PerformanceBundleError) as captured:
        _small_bundle(root)

    assert captured.value.code == "bundle_target_exists"
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_default_contract_builds_1225_document_shape(tmp_path: Path) -> None:
    root = tmp_path / "bundle"

    started = time.perf_counter()
    bundle = generate_performance_bundle(
        [_document(number) for number in range(1, 1226)],
        root,
    )
    elapsed_seconds = time.perf_counter() - started

    counts = bundle.manifest.counts
    assert elapsed_seconds < 60.0
    assert counts.base_document_count == 1225
    assert counts.target_live_document_count == 1215
    assert counts.base_event_count == 1225
    assert counts.target_event_count == 1286
    assert counts.content_update_count == 31
    assert counts.acl_only_count == 20
    assert counts.delete_count == 10
    assert counts.unchanged_count == 1164
    assert counts.query_count == 13


def test_deletion_oracle_and_runner_pipeline_identity_are_explicit(
    tmp_path: Path,
) -> None:
    bundle = _small_bundle(tmp_path / "bundle")

    oracle = bundle.change_descriptor.deletion_oracles[0]
    delete_case = next(
        case
        for case in bundle.query_descriptor.cases
        if case.category == "delete"
    )
    assert oracle.source_key in bundle.change_descriptor.categories.deletes
    assert delete_case.expected_source_key == oracle.source_key
    assert delete_case.expected_doc_id == oracle.base_doc_id
    assert delete_case.expectation == "absent_from_target"
    assert delete_case.denial_dimension == "none"
    assert delete_case.request.mode == "bm25"
    base_entries = {
        entry.source_key: entry for entry in bundle.base_documents.entries
    }
    target_entries = {
        entry.source_key: entry for entry in bundle.target_documents.entries
    }
    acl_denials = {
        case.denial_dimension
        for case in bundle.query_descriptor.cases
        if case.category == "acl_only"
        and case.expectation == "denied_by_acl"
    }
    assert acl_denials == {"removed_group", "tenant", "region"}
    for case in bundle.query_descriptor.cases:
        oracle_token = case.request.query.split()[-1]
        expected_entry = (
            base_entries[case.expected_source_key]
            if case.category == "delete"
            else target_entries[case.expected_source_key]
        )
        assert oracle_token.startswith("g10oracle")
        assert oracle_token in expected_entry.document.text.split()
        assert case.request.filters.statuses == [
            expected_entry.document.document_version.status
        ]
        assert case.request.filters.temporal_scope == "all"
        if case.denial_dimension == "removed_group":
            assert not set(case.request.user.groups).intersection(
                expected_entry.document.acl_groups
            )
            base_entry = base_entries[case.expected_source_key]
            assert set(case.request.user.groups) == (
                set(base_entry.document.acl_groups)
                - set(expected_entry.document.acl_groups)
            )
        elif case.denial_dimension == "tenant":
            assert (
                case.request.user.tenant_id
                != expected_entry.document.tenant_id
            )
        elif case.denial_dimension == "region":
            assert case.request.user.region != expected_entry.document.region
        else:
            assert (
                case.request.user.groups
                == expected_entry.document.acl_groups
            )
    pipeline = bundle.manifest.pipeline
    assert pipeline.chunker_name == "fixed"
    assert pipeline.chunk_size == 500
    assert pipeline.chunk_overlap == 80
    assert pipeline.embedding_backend == "deterministic"
    assert pipeline.embedding_model == "deterministic-shake256"
    assert pipeline.embedding_dimension == 128


def test_load_rejects_hash_rebound_deletion_oracle(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bundle"
    _small_bundle(root)
    payload = json.loads(
        (root / "change_descriptor.json").read_text(encoding="utf-8")
    )
    payload["deletion_oracles"][0]["base_doc_id"] = "different-doc"
    _rebind_file(root, "change_descriptor.json", payload)

    with pytest.raises(PerformanceBundleError) as captured:
        load_performance_bundle(root)

    assert captured.value.code == "bundle_deletion_oracle_invalid"


def test_load_rejects_query_without_bound_retrieval_oracle(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bundle"
    _small_bundle(root)
    payload = json.loads(
        (root / "query_descriptor.json").read_text(encoding="utf-8")
    )
    payload["cases"][0]["request"]["query"] = "generic benchmark query"
    _rebind_file(root, "query_descriptor.json", payload)

    with pytest.raises(PerformanceBundleError) as captured:
        load_performance_bundle(root)

    assert captured.value.code == "bundle_query_binding_invalid"


def test_load_rejects_query_filter_not_bound_to_expected_revision(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bundle"
    _small_bundle(root)
    payload = json.loads(
        (root / "query_descriptor.json").read_text(encoding="utf-8")
    )
    payload["cases"][0]["request"]["filters"]["temporal_scope"] = "current"
    _rebind_file(root, "query_descriptor.json", payload)

    with pytest.raises(PerformanceBundleError) as captured:
        load_performance_bundle(root)

    assert captured.value.code == "bundle_query_binding_invalid"
