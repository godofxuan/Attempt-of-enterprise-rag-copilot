import hashlib
import re
from datetime import date, datetime, timezone

import pytest

from app.domain.documents import (
    DocumentRecord,
    DocumentVersion,
    ParsedSection,
    SourceLocator,
)
from app.ingestion.versions import govern_documents


def normalized_hash(text: str) -> str:
    value = re.sub(r"\s+", " ", text).strip().casefold()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def record(
    doc_id: str,
    *,
    text: str = "Policy text",
    raw_bytes: bytes | None = None,
    policy_id: str = "policy",
    version_id: str = "policy@2026",
    version: str = "2026.1",
    status: str = "active",
    effective_from: date = date(2026, 1, 1),
    effective_to: date | None = None,
    supersedes_version_id: str | None = None,
    supersedes_doc_id: str | None = None,
    authority: int = 100,
    acl_groups: list[str] | None = None,
    variant: str = "authoritative",
) -> DocumentRecord:
    payload = raw_bytes if raw_bytes is not None else text.encode("utf-8")
    return DocumentRecord(
        doc_id=doc_id,
        title=doc_id,
        source_type="policy",
        source_path=f"documents/{doc_id}.md",
        format="md",
        department="hr",
        filed_department="hr",
        project_id=None,
        policy_id=policy_id,
        region="cn",
        tenant_id="tenant-cn",
        acl_groups=acl_groups or ["all_employees"],
        document_version=DocumentVersion(
            version_id=version_id,
            version=version,
            status=status,
            effective_from=effective_from,
            effective_to=effective_to,
            supersedes_version_id=supersedes_version_id,
            supersedes_doc_id=supersedes_doc_id,
            authority_level=authority,
        ),
        authority_level=authority,
        checksum=hashlib.sha256(payload).hexdigest(),
        normalized_text_hash=normalized_hash(text),
        ingested_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
        parser_name="markdown",
        parser_version="1",
        text=text,
        sections=[
            ParsedSection(
                heading="Policy",
                level=1,
                path=["Policy"],
                text=text,
                locator=SourceLocator(kind="line", start=1, end=1),
            )
        ],
        tables=[],
        parse_warnings=[],
        fact_ids=[f"fact-{version_id}"],
        variant=variant,
        duplicate_of=None,
    )


def valid_chain() -> list[DocumentRecord]:
    retired = record(
        "auth_policy_2025",
        text="Old policy",
        version_id="policy@2025",
        version="2025.1",
        status="retired",
        effective_from=date(2025, 1, 1),
        effective_to=date(2026, 1, 1),
    )
    active = record(
        "auth_policy_2026",
        text="Current policy",
        supersedes_version_id="policy@2025",
        supersedes_doc_id="auth_policy_2025",
    )
    return [retired, active]


def test_exact_duplicate_is_collapsed_with_alias() -> None:
    documents = valid_chain()
    duplicate = documents[1].model_copy(
        update={
            "doc_id": "duplicate_policy_2026",
            "source_path": "documents/duplicate_policy_2026.md",
            "variant": "duplicate",
            "duplicate_of": "auth_policy_2026",
        },
        deep=True,
    )

    governed = govern_documents([*documents, duplicate])

    assert [doc.doc_id for doc in governed.documents] == [
        "auth_policy_2025",
        "auth_policy_2026",
    ]
    assert governed.duplicate_aliases == {
        "duplicate_policy_2026": "auth_policy_2026"
    }


def test_supporting_source_is_preferred_over_duplicate_variant() -> None:
    documents = valid_chain()
    supporting = documents[1].model_copy(
        update={
            "doc_id": "support_0001",
            "source_path": "documents/support_0001.md",
            "text": "Operational note",
            "checksum": hashlib.sha256(b"Operational note").hexdigest(),
            "normalized_text_hash": normalized_hash("Operational note"),
            "variant": "supporting",
        },
        deep=True,
    )
    duplicate = supporting.model_copy(
        update={
            "doc_id": "duplicate_0001",
            "source_path": "documents/duplicate_0001.md",
            "variant": "duplicate",
            "duplicate_of": "support_0001",
        },
        deep=True,
    )

    governed = govern_documents([*documents, supporting, duplicate])

    assert governed.duplicate_aliases == {"duplicate_0001": "support_0001"}
    assert "support_0001" in {document.doc_id for document in governed.documents}


def test_normalized_duplicate_collapses_whitespace_and_case_changes() -> None:
    documents = valid_chain()
    canonical = documents[1].model_copy(
        update={"text": "Policy   TEXT", "normalized_text_hash": normalized_hash("Policy TEXT")},
        deep=True,
    )
    duplicate = canonical.model_copy(
        update={
            "doc_id": "support_policy_2026",
            "source_path": "documents/support_policy_2026.md",
            "text": " policy text ",
            "checksum": hashlib.sha256(b"different bytes").hexdigest(),
            "normalized_text_hash": normalized_hash(" policy text "),
            "variant": "supporting",
        },
        deep=True,
    )

    governed = govern_documents([documents[0], canonical, duplicate])

    assert governed.duplicate_aliases["support_policy_2026"] == "auth_policy_2026"


def test_dedup_does_not_cross_acl_or_version_boundary() -> None:
    old, active = valid_chain()
    old = old.model_copy(
        update={
            "text": active.text,
            "checksum": active.checksum,
            "normalized_text_hash": active.normalized_text_hash,
        },
        deep=True,
    )
    restricted = active.model_copy(
        update={
            "doc_id": "restricted_policy_2026",
            "source_path": "documents/restricted_policy_2026.md",
            "acl_groups": ["hr_confidential"],
            "variant": "supporting",
        },
        deep=True,
    )

    governed = govern_documents([old, active, restricted])

    assert {doc.doc_id for doc in governed.documents} == {
        "auth_policy_2025",
        "auth_policy_2026",
        "restricted_policy_2026",
    }
    assert governed.duplicate_aliases == {}


def test_valid_version_chain_selects_active_head_and_retains_retired() -> None:
    governed = govern_documents(valid_chain())

    assert governed.version_heads == {"policy": "auth_policy_2026"}
    assert governed.retired_doc_ids == ["auth_policy_2025"]


def test_missing_supersedes_version_is_rejected() -> None:
    active = record(
        "auth_policy_2026",
        supersedes_version_id="policy@missing",
    )

    with pytest.raises(ValueError, match="unknown supersedes version"):
        govern_documents([active])


def test_version_cycle_is_rejected() -> None:
    first = record(
        "auth_policy_2024",
        version_id="policy@2024",
        version="2024.1",
        status="retired",
        effective_from=date(2024, 1, 1),
        effective_to=date(2025, 1, 1),
        supersedes_version_id="policy@2025",
    )
    second = record(
        "auth_policy_2025",
        version_id="policy@2025",
        version="2025.1",
        status="retired",
        effective_from=date(2025, 1, 1),
        effective_to=date(2026, 1, 1),
        supersedes_version_id="policy@2024",
    )
    active = record("auth_policy_2026")

    with pytest.raises(ValueError, match="cycle"):
        govern_documents([first, second, active])


def test_overlapping_successive_versions_are_rejected() -> None:
    retired = record(
        "auth_policy_2025",
        version_id="policy@2025",
        version="2025.1",
        status="retired",
        effective_from=date(2025, 1, 1),
        effective_to=date(2026, 6, 1),
    )
    active = record(
        "auth_policy_2026",
        supersedes_version_id="policy@2025",
        supersedes_doc_id="auth_policy_2025",
    )

    with pytest.raises(ValueError, match="overlap"):
        govern_documents([retired, active])


def test_multiple_active_authoritative_versions_are_rejected() -> None:
    first = record(
        "auth_policy_v1",
        version_id="policy@v1",
        version="v1",
        effective_from=date(2025, 1, 1),
    )
    second = record(
        "auth_policy_v2",
        version_id="policy@v2",
        version="v2",
        effective_from=date(2026, 1, 1),
    )

    with pytest.raises(ValueError, match="exactly one active"):
        govern_documents([first, second])
