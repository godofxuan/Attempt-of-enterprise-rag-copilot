from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.evaluation.trusted_identity import (
    EXPECTED_MATRIX_SHA256,
    TRUSTED_IDENTITY_SOURCE_FILES,
    TrustedIdentityCase,
    TrustedIdentityEvaluationResult,
    _contains_credential_leak,
    evaluate_trusted_identity,
    load_trusted_identity_matrix,
)
from scripts.eval_trusted_identity import _write_new_result


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "data" / "v2" / "security" / "r2_s5_identity_matrix_v1.json"
PUBLIC_RESULT = (
    ROOT
    / "docs"
    / "security"
    / "r2_s5"
    / "evidence"
    / "identity_matrix_result.json"
)


def test_trusted_identity_source_contract_covers_the_filesystem_boundary() -> None:
    assert TRUSTED_IDENTITY_SOURCE_FILES == (
        "app/api/identity.py",
        "app/db.py",
        "app/evaluation/trusted_identity.py",
        "app/main.py",
        "app/runtime/resources.py",
        "app/schemas.py",
        "app/security/demo_identity.py",
        "app/security/identity.py",
        "app/security/private_fs.py",
        "app/security/token_source.py",
        "scripts/eval_trusted_identity.py",
    )


def test_frozen_trusted_identity_matrix_passes_without_side_effect_or_leak() -> None:
    result = evaluate_trusted_identity(MATRIX)

    assert result.matrix_sha256 == EXPECTED_MATRIX_SHA256
    assert result.schema_version == "trusted-identity-evaluation-v2"
    assert re.fullmatch(
        r"trusted-identity-contract-[0-9a-f]{16}",
        result.evaluation_contract_id,
    )
    assert result.source_sha256 == {
        relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        for relative in TRUSTED_IDENTITY_SOURCE_FILES
    }
    assert result.total_cases == 20
    assert result.passed_cases == 20
    assert result.failed_cases == 0
    assert result.denied_cases == 14
    assert result.denied_side_effect_violations == 0
    assert result.credential_leaks == 0
    assert result.release_pass is True
    assert all(case.passed for case in result.cases)
    chat = next(case for case in result.cases if case.case_id == "chat_verified_user")
    feedback = next(
        case for case in result.cases
        if case.case_id == "feedback_verified_user"
    )
    assert chat.chat_receipt_match is True
    assert feedback.feedback_binding_match is True
    assert feedback.feedback_privacy_match is True


def test_public_trusted_identity_result_recomputes_exactly() -> None:
    published = TrustedIdentityEvaluationResult.model_validate_json(
        PUBLIC_RESULT.read_text(encoding="utf-8")
    )

    assert published == evaluate_trusted_identity(MATRIX)


def test_trusted_identity_matrix_hash_drift_fails_before_execution(
    tmp_path: Path,
) -> None:
    payload = json.loads(MATRIX.read_text(encoding="utf-8"))
    payload["cases"][0]["expected_status"] = 503
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="hash mismatch"):
        load_trusted_identity_matrix(changed)


def test_trusted_identity_result_writer_never_overwrites(tmp_path: Path) -> None:
    output = tmp_path / "result.json"

    _write_new_result(output, "first\n")
    with pytest.raises(FileExistsError):
        _write_new_result(output, "second\n")

    assert output.read_text(encoding="utf-8") == "first\n"


def test_leak_detector_covers_token_segments_keys_and_identity_claims() -> None:
    case = _case("/agent/v2/chat")
    user_token = "header.user-payload.user-signature"
    operator_token = "header.operator-payload.operator-signature"
    hmac_key = b"k" * 32

    for leaked in (
        user_token,
        "operator-payload",
        hmac_key.hex(),
        "BEGIN PRIVATE KEY",
        "load-demo-employee",
    ):
        response = SimpleNamespace(text=f"unsafe:{leaked}", headers={})
        assert _contains_credential_leak(
            response,
            case=case,
            user_token=user_token,
            operator_token=operator_token,
            hmac_key=hmac_key,
        )


def test_identity_me_allows_documented_claims_but_not_credentials() -> None:
    user_token = "header.user-payload.user-signature"
    operator_token = "header.operator-payload.operator-signature"
    hmac_key = b"k" * 32
    claims = SimpleNamespace(
        text='{"subject":"load-demo-employee","tenant_id":"starbridge-cn"}',
        headers={},
    )
    token = SimpleNamespace(text=user_token, headers={})

    assert not _contains_credential_leak(
        claims,
        case=_case("/identity/me"),
        user_token=user_token,
        operator_token=operator_token,
        hmac_key=hmac_key,
    )
    assert _contains_credential_leak(
        token,
        case=_case("/identity/me"),
        user_token=user_token,
        operator_token=operator_token,
        hmac_key=hmac_key,
    )


def _case(path: str) -> TrustedIdentityCase:
    return TrustedIdentityCase(
        case_id="test_case",
        method="GET",
        path=path,
        credential="none",
        body_kind="none",
        expected_status=200,
        expected_code=None,
        expected_agent_calls=0,
        expected_feedback_writes=0,
    )
