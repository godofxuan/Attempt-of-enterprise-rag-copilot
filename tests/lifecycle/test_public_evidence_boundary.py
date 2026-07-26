from __future__ import annotations

import shutil
from pathlib import Path

from scripts.audit_public_repo import audit_repository


ROOT = Path(__file__).resolve().parents[2]
SECURITY_CORPUS_PATHS = (
    "data/v2/security/indirect_injection_dev_v1.json",
    "data/v2/security/indirect_injection_test_v1.json",
    "data/v2/security/fixtures_v1/dev/manifest.json",
    "data/v2/security/fixtures_v1/test/manifest.json",
)


def test_public_evidence_scanner_detects_sensitive_fixture(
    tmp_path: Path,
) -> None:
    for relative in SECURITY_CORPUS_PATHS:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)

    relative = "docs/lifecycle/public.log"
    public_log = tmp_path / relative
    public_log.parent.mkdir(parents=True)
    credential_name = "client_" + "secret"
    credential_value = "Live" + "CredentialValue42"
    public_log.write_text(
        f"{credential_name}={credential_value}\n",
        encoding="utf-8",
    )

    report = audit_repository(tmp_path, candidate_files=[relative])

    assert ("credential_assignment", relative) in {
        (finding.code, finding.path) for finding in report.findings
    }
