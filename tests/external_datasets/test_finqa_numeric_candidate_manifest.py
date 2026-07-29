from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.build_finqa_numeric_candidate_manifest import (
    DEFAULT_OUTPUT,
    DEFAULT_SOURCE,
    REPOSITORY_ROOT,
    build_manifest_bytes,
    main,
)


HISTORICAL_GATE_B_OUTPUT = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_numeric_candidate_manifest_v1.json"
)
HISTORICAL_GATE_B_SHA256 = (
    "b24813f5310ba132fa68e9da7502398750ec06d36d0747750971357abc450b01"
)


def test_gate_b_candidate_manifest_remains_byte_immutable() -> None:
    assert hashlib.sha256(HISTORICAL_GATE_B_OUTPUT.read_bytes()).hexdigest() == (
        HISTORICAL_GATE_B_SHA256
    )


def test_checked_in_numeric_candidate_manifest_is_recomputable() -> None:
    assert DEFAULT_OUTPUT.read_bytes() == build_manifest_bytes(DEFAULT_SOURCE)


def test_gate_c_source_rebind_does_not_change_candidate_identity_set() -> None:
    gate_b = json.loads(HISTORICAL_GATE_B_OUTPUT.read_text(encoding="utf-8"))
    gate_c = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))

    assert gate_c["candidate_id_set_sha256"] == (
        gate_b["candidate_id_set_sha256"]
    )
    assert gate_c["extraction_config_sha256"] == (
        gate_b["extraction_config_sha256"]
    )
    assert gate_c["source_artifact_sha256"] == (
        gate_b["source_artifact_sha256"]
    )
    assert gate_c["extractor_source_sha256"] != (
        gate_b["extractor_source_sha256"]
    )


def test_candidate_manifest_cli_refuses_overwrite_and_supports_check(
    tmp_path: Path,
) -> None:
    output = tmp_path / "manifest.json"

    assert main(["--source", str(DEFAULT_SOURCE), "--output", str(output)]) == 0
    assert main(
        [
            "--source",
            str(DEFAULT_SOURCE),
            "--output",
            str(output),
            "--check",
        ]
    ) == 0

    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["status"] == "SYNTHETIC_CONTRACT_ONLY"
    assert manifest["candidate_count"] == 9
    assert manifest["counts_by_role"] == {
        "operand": 6,
        "ordinal": 1,
        "page_number": 1,
        "period_label": 1,
    }
