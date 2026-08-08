from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_uda_finance_pages import (
    claim_frozen_test_execution,
    complete_frozen_test_execution,
)


def test_frozen_test_execution_is_one_shot_and_result_bound(tmp_path: Path) -> None:
    kwargs = {
        "run_id": "uda-test-dense-v1",
        "code_revision": "a" * 40,
        "protocol_sha256": "b" * 64,
        "cases_sha256": "c" * 64,
        "retrieval_arm": "dense",
    }
    marker = claim_frozen_test_execution(tmp_path, **kwargs)

    with pytest.raises(FileExistsError):
        claim_frozen_test_execution(tmp_path, **kwargs)

    complete_frozen_test_execution(marker, result_manifest_sha256="d" * 64)
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["status"] == "COMPLETED"
    assert payload["result_manifest_sha256"] == "d" * 64
    with pytest.raises(FileExistsError):
        claim_frozen_test_execution(tmp_path, **kwargs)


def test_frozen_test_completion_rejects_invalid_result_hash(tmp_path: Path) -> None:
    marker = claim_frozen_test_execution(
        tmp_path,
        run_id="uda-test-dense-v1",
        code_revision="a" * 40,
        protocol_sha256="b" * 64,
        cases_sha256="c" * 64,
        retrieval_arm="dense",
    )
    with pytest.raises(ValueError, match="hash is invalid"):
        complete_frozen_test_execution(marker, result_manifest_sha256="bad")
