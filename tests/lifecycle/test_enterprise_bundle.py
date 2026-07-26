from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

import pytest

from app.lifecycle.enterprise_bundle import (
    EnterpriseBundleError,
    EnterpriseBundleManifest,
    EnterpriseLifecyclePublicSummary,
    canonical_enterprise_bundle_manifest_bytes,
    canonical_enterprise_lifecycle_summary_bytes,
    load_enterprise_bundle,
)


ROOT = Path(__file__).resolve().parents[2]
BUNDLE_ROOT = ROOT / "data" / "enterprise_bundle"
PUBLIC_EVIDENCE_ROOT = ROOT / "data" / "v2" / "public" / "lifecycle_g9"
_CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64})  ([a-zA-Z0-9_./-]+)$")


def _rebind_asset(copied_root: Path, relative_path: str) -> None:
    manifest_path = copied_root / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    content = copied_root.joinpath(*relative_path.split("/")).read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    for asset in payload["assets"]:
        if asset["path"] == relative_path:
            asset["byte_count"] = len(content)
            asset["sha256"] = digest
    for item in payload["events"]:
        event = item["event"]
        if event.get("content_relpath") == relative_path:
            event["content_sha256"] = digest
    manifest = EnterpriseBundleManifest.model_validate(payload)
    manifest_path.write_bytes(canonical_enterprise_bundle_manifest_bytes(manifest))


def test_fictional_enterprise_bundle_is_canonical_and_hash_complete() -> None:
    bundle = load_enterprise_bundle(BUNDLE_ROOT)

    assert bundle.manifest.bundle_id == "northstar-harbor-lifecycle-v1"
    assert bundle.manifest.synthetic is True
    assert bundle.manifest.identity_policy == "fictional-example-invalid-v1"
    assert len(bundle.manifest.assets) == 5
    assert len(bundle.batch("initial")) == 4
    assert sum(
        item.batch == "change" for item in bundle.manifest.events
    ) == 2
    assert {asset.domain for asset in bundle.manifest.assets} == {
        "email",
        "operations",
        "policy",
        "project",
    }


def test_bundle_detects_source_tamper_before_returning_events(
    tmp_path: Path,
) -> None:
    copied = tmp_path / "bundle"
    shutil.copytree(BUNDLE_ROOT, copied)
    source = copied / "sources" / "operations" / "vendor_onboarding.txt"
    source.write_text("tampered", encoding="utf-8")

    with pytest.raises(EnterpriseBundleError) as captured:
        load_enterprise_bundle(copied)

    assert captured.value.code == "bundle_asset_integrity_failed"


def test_bundle_rejects_noncanonical_manifest_bytes(tmp_path: Path) -> None:
    copied = tmp_path / "bundle"
    shutil.copytree(BUNDLE_ROOT, copied)
    manifest = copied / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    manifest.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with pytest.raises(EnterpriseBundleError) as captured:
        load_enterprise_bundle(copied)

    assert captured.value.code == "bundle_manifest_noncanonical"


def test_bundle_rejects_private_windows_user_root_after_valid_hash_binding(
    tmp_path: Path,
) -> None:
    copied = tmp_path / "bundle"
    shutil.copytree(BUNDLE_ROOT, copied)
    relative = "sources/operations/vendor_onboarding.txt"
    separator = bytes((92,))
    content = b"Fictional record: c:" + separator + b"users" + separator + b"x"
    copied.joinpath(*relative.split("/")).write_bytes(content)
    _rebind_asset(copied, relative)

    with pytest.raises(EnterpriseBundleError) as captured:
        load_enterprise_bundle(copied)

    assert captured.value.code == "bundle_private_marker_detected"


def test_bundle_rejects_nonfictional_email_identity_after_valid_hash_binding(
    tmp_path: Path,
) -> None:
    copied = tmp_path / "bundle"
    shutil.copytree(BUNDLE_ROOT, copied)
    relative = "sources/mail/security_drill.eml"
    copied.joinpath(*relative.split("/")).write_bytes(
        b"From: employee@" + b"real.example\n"
        b"To: reviewer@example.invalid\n"
        b"Subject: Fictional test\n\n"
        b"No private content.\n"
    )
    _rebind_asset(copied, relative)

    with pytest.raises(EnterpriseBundleError) as captured:
        load_enterprise_bundle(copied)

    assert captured.value.code == "bundle_identity_policy_failed"


def test_bundle_rejects_base64_encoded_nonfictional_email_identity(
    tmp_path: Path,
) -> None:
    copied = tmp_path / "bundle"
    shutil.copytree(BUNDLE_ROOT, copied)
    relative = "sources/mail/security_drill.eml"
    private_address = b"employee@" + b"real.example"
    encoded_body = base64.b64encode(b"Contact " + private_address)
    copied.joinpath(*relative.split("/")).write_bytes(
        b"From: reviewer@example.invalid\n"
        b"To: security@example.invalid\n"
        b"Subject: Fictional test\n"
        b"MIME-Version: 1.0\n"
        b"Content-Type: text/plain; charset=utf-8\n"
        b"Content-Transfer-Encoding: base64\n\n"
        + encoded_body
        + b"\n"
    )
    _rebind_asset(copied, relative)

    with pytest.raises(EnterpriseBundleError) as captured:
        load_enterprise_bundle(copied)

    assert captured.value.code == "bundle_identity_policy_failed"


def test_bundle_rejects_internal_asset_symlink_before_resolution(
    tmp_path: Path,
) -> None:
    copied = tmp_path / "bundle"
    shutil.copytree(BUNDLE_ROOT, copied)
    source = copied / "sources" / "operations" / "vendor_onboarding.txt"
    target = source.with_name("vendor_onboarding.real.txt")
    source.rename(target)
    try:
        os.symlink(target.name, source)
    except OSError:
        pytest.skip("local account cannot create symbolic links")

    with pytest.raises(EnterpriseBundleError) as captured:
        load_enterprise_bundle(copied)

    assert captured.value.code == "bundle_asset_path_invalid"


def test_manifest_query_must_reference_an_initial_upsert_source() -> None:
    payload = json.loads((BUNDLE_ROOT / "manifest.json").read_text("utf-8"))
    payload["fixed_queries"][0]["expected_source_key_in_initial"] = (
        "missing/source"
    )

    with pytest.raises(ValueError):
        EnterpriseBundleManifest.model_validate(payload)


def test_change_batch_resolves_expected_revision_from_accepted_event() -> None:
    bundle = load_enterprise_bundle(BUNDLE_ROOT)

    changes = bundle.resolve_batch(
        "change",
        accepted_revisions={
            "evt-g9-policy-v1": f"rev_{'1' * 64}",
            "evt-g9-vendor-v1": f"rev_{'2' * 64}",
        },
    )

    assert changes[0].expected_revision_id == f"rev_{'1' * 64}"
    assert changes[1].expected_revision_id == f"rev_{'2' * 64}"
    assert changes[0].operation == "UPSERT"
    assert changes[1].operation == "DELETE"


def test_public_evidence_checksums_bind_the_exact_g9_fixture() -> None:
    checksum_file = PUBLIC_EVIDENCE_ROOT / "checksums.sha256"
    lines = checksum_file.read_text(encoding="ascii").splitlines()
    expected_paths = {
        "data/enterprise_bundle/manifest.json",
        "data/enterprise_bundle/sources/mail/security_drill.eml",
        "data/enterprise_bundle/sources/operations/vendor_onboarding.txt",
        "data/enterprise_bundle/sources/policies/remote_access_v1.md",
        "data/enterprise_bundle/sources/policies/remote_access_v2.md",
        "data/enterprise_bundle/sources/projects/atlas_release.csv",
        "data/v2/public/lifecycle_g9/summary.json",
    }
    observed_paths: set[str] = set()

    for line in lines:
        match = _CHECKSUM_LINE.fullmatch(line)
        assert match is not None
        expected_sha256, relative_path = match.groups()
        assert relative_path not in observed_paths
        observed_paths.add(relative_path)
        candidate = (ROOT / relative_path).resolve(strict=True)
        candidate.relative_to(ROOT.resolve(strict=True))
        assert candidate.is_file()
        assert hashlib.sha256(candidate.read_bytes()).hexdigest() == (
            expected_sha256
        )

    assert observed_paths == expected_paths


def test_public_summary_is_strict_canonical_and_sanitized() -> None:
    summary_path = PUBLIC_EVIDENCE_ROOT / "summary.json"
    raw = summary_path.read_bytes()
    summary = EnterpriseLifecyclePublicSummary.model_validate_json(raw)

    assert raw == canonical_enterprise_lifecycle_summary_bytes(summary)
    assert summary.synthetic is True
    assert summary.embedding_backend == "deterministic-test"
    assert summary.active_index_deleted_residual_count == 0
    lowered = raw.lower()
    windows_separator = bytes((92,))
    for forbidden in (
        b"c:" + windows_separator + b"users" + windows_separator,
        b"d:" + windows_separator,
        b"/home/",
        b"authorization",
        b"bearer",
        b"@",
        b"asset_id",
        b"publication_id",
        b"catalog_sha256",
    ):
        assert forbidden not in lowered
