from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.security.identity import FeedbackActorHasher, IdentityConfigurationError, Principal
from tests.security.identity_test_support import write_standalone_private_file


def _principal(subject: str = "employee-one") -> Principal:
    issued_at = datetime.now(timezone.utc)
    return Principal(
        subject=subject,
        tenant_id="tenant-one",
        region="cn",
        groups=["employees"],
        roles=[],
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        key_id="test-key-1",
        issued_at=issued_at,
        expires_at=issued_at + timedelta(minutes=5),
    )


def test_feedback_actor_pseudonym_is_keyed_stable_and_domain_separated(
    tmp_path: Path,
) -> None:
    key_path = tmp_path / "actor.key"
    write_standalone_private_file(key_path, b"a" * 32)
    hasher = FeedbackActorHasher.load(
        key_path,
        max_bytes=256,
        allow_standalone=True,
    )

    first = hasher.pseudonym(_principal())
    second = hasher.pseudonym(_principal())
    other_subject = hasher.pseudonym(_principal("employee-two"))
    other_key_path = tmp_path / "other.key"
    write_standalone_private_file(other_key_path, b"b" * 32)
    other_key = FeedbackActorHasher.load(
        other_key_path,
        max_bytes=256,
        allow_standalone=True,
    ).pseudonym(_principal())

    assert first == second
    assert first != other_subject
    assert first != other_key
    assert len(first) == 64
    assert first != hashlib.sha256(b"employee-one").hexdigest()
    assert "employee-one" not in first
    assert "aaaaaaaa" not in repr(hasher)


def test_feedback_content_digests_are_keyed_and_domain_separated(
    tmp_path: Path,
) -> None:
    key_path = tmp_path / "actor.key"
    write_standalone_private_file(key_path, b"a" * 32)
    hasher = FeedbackActorHasher.load(
        key_path,
        max_bytes=256,
        allow_standalone=True,
    )

    question_digest = hasher.content_digest("question", "same text")
    answer_digest = hasher.content_digest("answer", "same text")

    assert question_digest != answer_digest
    assert question_digest != hashlib.sha256(b"same text").hexdigest()
    assert len(question_digest) == 64


def test_feedback_receipt_binds_actor_target_and_exact_content(tmp_path: Path) -> None:
    key_path = tmp_path / "actor.key"
    write_standalone_private_file(key_path, b"a" * 32)
    hasher = FeedbackActorHasher.load(
        key_path,
        max_bytes=256,
        allow_standalone=True,
    )
    principal = _principal()
    receipt = hasher.issue_feedback_receipt(
        principal,
        target_request_id="req-answer-1",
        question="What is the policy?",
        answer="The approved answer.",
    )

    assert hasher.verify_feedback_receipt(
        principal,
        target_request_id="req-answer-1",
        question="What is the policy?",
        answer="The approved answer.",
        receipt=receipt,
    )
    assert not hasher.verify_feedback_receipt(
        _principal("employee-two"),
        target_request_id="req-answer-1",
        question="What is the policy?",
        answer="The approved answer.",
        receipt=receipt,
    )
    assert not hasher.verify_feedback_receipt(
        principal,
        target_request_id="req-answer-2",
        question="What is the policy?",
        answer="The approved answer.",
        receipt=receipt,
    )
    assert not hasher.verify_feedback_receipt(
        principal,
        target_request_id="req-answer-1",
        question="What is the policy?",
        answer="A modified answer.",
        receipt=receipt,
    )
    assert not hasher.verify_feedback_receipt(
        principal,
        target_request_id="req-answer-1",
        question="What is the policy?",
        answer="The approved answer.",
        receipt="not-a-receipt",
    )


@pytest.mark.parametrize("size", [0, 31, 257])
def test_feedback_actor_key_rejects_unsafe_sizes(tmp_path: Path, size: int) -> None:
    key_path = tmp_path / "actor.key"
    write_standalone_private_file(key_path, b"a" * size)

    with pytest.raises(IdentityConfigurationError):
        FeedbackActorHasher.load(
            key_path,
            max_bytes=256,
            allow_standalone=True,
        )


def test_managed_feedback_key_never_falls_back_without_manifest(
    tmp_path: Path,
) -> None:
    key_path = write_standalone_private_file(
        tmp_path / "actor.key",
        b"a" * 32,
    )

    with pytest.raises(IdentityConfigurationError, match="not committed"):
        FeedbackActorHasher.load(key_path, max_bytes=256)


def test_managed_feedback_key_rejects_reserved_manifest_filename_without_commit_metadata(
    tmp_path: Path,
) -> None:
    key_path = write_standalone_private_file(
        tmp_path / "identity_manifest.json",
        b"a" * 32,
    )

    with pytest.raises(IdentityConfigurationError, match="not committed"):
        FeedbackActorHasher.load(key_path, max_bytes=256)
