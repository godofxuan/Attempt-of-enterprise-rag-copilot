from __future__ import annotations

import json
import shutil
from pathlib import Path

from scripts.verify_enterprise_bundle import main


ROOT = Path(__file__).resolve().parents[2]
BUNDLE_ROOT = ROOT / "data" / "enterprise_bundle"


def test_verify_enterprise_bundle_cli_emits_content_free_result(
    capsys,
) -> None:
    result = main(["--root", str(BUNDLE_ROOT)])

    assert result == 0
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload == {
        "schema_version": "enterprise_bundle_verification_v1",
        "status": "VERIFIED",
        "bundle_id": "northstar-harbor-lifecycle-v1",
        "manifest_sha256": (
            "e52d8d2e700615267680108d72de35af"
            "9e522720c38d07ce9ec1604c5d761cac"
        ),
        "synthetic": True,
        "identity_policy": "fictional-example-invalid-v1",
        "asset_count": 5,
        "asset_byte_count": 2041,
        "event_count": 6,
        "initial_event_count": 4,
        "change_event_count": 2,
        "query_count": 1,
        "domains": ["email", "operations", "policy", "project"],
    }
    assert "vendor@example.invalid" not in output


def test_verify_enterprise_bundle_cli_reports_tamper_without_content(
    tmp_path: Path,
    capsys,
) -> None:
    copied = tmp_path / "bundle"
    shutil.copytree(BUNDLE_ROOT, copied)
    source = copied / "sources" / "operations" / "vendor_onboarding.txt"
    source.write_text("private replacement", encoding="utf-8")

    result = main(["--root", str(copied)])

    assert result == 2
    assert json.loads(capsys.readouterr().out) == {
        "schema_version": "enterprise_bundle_verification_v1",
        "status": "FAILED",
        "error": {"code": "bundle_asset_integrity_failed"},
    }
