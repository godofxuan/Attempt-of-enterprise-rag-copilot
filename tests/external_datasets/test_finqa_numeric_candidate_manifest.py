from __future__ import annotations

import json
from pathlib import Path

from scripts.build_finqa_numeric_candidate_manifest import (
    DEFAULT_OUTPUT,
    DEFAULT_SOURCE,
    build_manifest_bytes,
    main,
)


def test_checked_in_numeric_candidate_manifest_is_recomputable() -> None:
    assert DEFAULT_OUTPUT.read_bytes() == build_manifest_bytes(DEFAULT_SOURCE)


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
