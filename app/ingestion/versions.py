from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.documents import DocumentRecord


class GovernedCorpus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_document_count: int = Field(ge=0)
    documents: list[DocumentRecord]
    duplicate_aliases: dict[str, str]
    version_heads: dict[str, str]
    retired_doc_ids: list[str]

    @model_validator(mode="after")
    def validate_aliases(self) -> GovernedCorpus:
        canonical_ids = {document.doc_id for document in self.documents}
        if not set(self.duplicate_aliases.values()).issubset(canonical_ids):
            raise ValueError("duplicate aliases must point to canonical documents")
        if set(self.duplicate_aliases) & canonical_ids:
            raise ValueError("duplicate aliases must not also be canonical documents")
        return self


def _canonical_rank(document: DocumentRecord) -> tuple[int, int, str]:
    variant_rank = {
        "authoritative": 0,
        "supporting": 1,
        "misfiled": 2,
        "stale": 2,
        "near_duplicate": 3,
        "duplicate": 4,
    }.get(document.variant, 3)
    return (variant_rank, -document.authority_level, document.doc_id)


def _dedup_domain(document: DocumentRecord) -> tuple:
    return (
        document.tenant_id,
        document.region,
        tuple(sorted(document.acl_groups)),
        document.policy_id,
        document.document_version.version_id,
        document.filed_department,
    )


def _deduplicate(
    documents: list[DocumentRecord],
) -> tuple[list[DocumentRecord], dict[str, str]]:
    canonical: list[DocumentRecord] = []
    aliases: dict[str, str] = {}
    exact_seen: dict[tuple, str] = {}
    normalized_seen: dict[tuple, str] = {}

    for document in sorted(documents, key=_canonical_rank):
        domain = _dedup_domain(document)
        exact_key = (*domain, document.checksum)
        normalized_key = (*domain, document.normalized_text_hash)
        canonical_id = exact_seen.get(exact_key) or normalized_seen.get(normalized_key)
        if canonical_id is not None:
            aliases[document.doc_id] = canonical_id
            continue
        canonical.append(document)
        exact_seen[exact_key] = document.doc_id
        normalized_seen[normalized_key] = document.doc_id
    canonical.sort(key=lambda document: document.doc_id)
    return canonical, dict(sorted(aliases.items()))


def _validate_version_graph(
    documents: list[DocumentRecord],
) -> dict[str, str]:
    authoritative_by_policy: dict[str, list[DocumentRecord]] = defaultdict(list)
    for document in documents:
        if document.policy_id and document.variant == "authoritative":
            authoritative_by_policy[document.policy_id].append(document)

    heads: dict[str, str] = {}
    for policy_id, policy_documents in sorted(authoritative_by_policy.items()):
        by_version: dict[str, DocumentRecord] = {}
        for document in policy_documents:
            version_id = document.document_version.version_id
            if version_id in by_version:
                raise ValueError(
                    f"policy {policy_id!r} has duplicate authoritative version {version_id!r}"
                )
            by_version[version_id] = document

        parent_by_version = {
            version_id: document.document_version.supersedes_version_id
            for version_id, document in by_version.items()
        }
        for version_id, parent_id in parent_by_version.items():
            if parent_id is not None and parent_id not in by_version:
                raise ValueError(
                    f"unknown supersedes version {parent_id!r} from {version_id!r}"
                )

        for start in by_version:
            visited: set[str] = set()
            current: str | None = start
            while current is not None:
                if current in visited:
                    raise ValueError(f"version chain for {policy_id!r} contains a cycle")
                visited.add(current)
                current = parent_by_version[current]

        for version_id, document in by_version.items():
            parent_id = document.document_version.supersedes_version_id
            if parent_id is None:
                continue
            predecessor = by_version[parent_id]
            expected_doc_id = predecessor.doc_id
            actual_doc_id = document.document_version.supersedes_doc_id
            if actual_doc_id is not None and actual_doc_id != expected_doc_id:
                raise ValueError(
                    f"supersedes document mismatch for {version_id!r}: "
                    f"expected {expected_doc_id!r}, got {actual_doc_id!r}"
                )
            predecessor_end = predecessor.document_version.effective_to
            if (
                predecessor_end is None
                or document.document_version.effective_from < predecessor_end
            ):
                raise ValueError(
                    f"successive version intervals overlap for {policy_id!r}"
                )

        active = [
            document
            for document in policy_documents
            if document.document_version.status == "active"
        ]
        if len(active) != 1:
            raise ValueError(
                f"policy {policy_id!r} must have exactly one active authoritative version"
            )
        heads[policy_id] = active[0].doc_id
    return heads


def govern_documents(documents: list[DocumentRecord]) -> GovernedCorpus:
    doc_ids = [document.doc_id for document in documents]
    if len(doc_ids) != len(set(doc_ids)):
        raise ValueError("source document IDs must be unique")
    canonical, aliases = _deduplicate(documents)
    heads = _validate_version_graph(canonical)
    retired = sorted(
        document.doc_id
        for document in canonical
        if document.document_version.status == "retired"
    )
    return GovernedCorpus(
        source_document_count=len(documents),
        documents=canonical,
        duplicate_aliases=aliases,
        version_heads=heads,
        retired_doc_ids=retired,
    )
