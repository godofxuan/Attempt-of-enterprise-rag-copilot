from __future__ import annotations

import hashlib
import json
import pickle
import re
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import faiss
import numpy as np
from pydantic import BaseModel

from app.domain.documents import (
    ChunkRecord,
    DocumentRecord,
    DocumentVersion,
    SourceLocator,
)
from app.evaluation.indirect_injection_contracts import (
    FixtureCandidate,
    FixtureCase,
    FixtureManifest,
    IndirectInjectionDataset,
    validate_dataset_fixture_alignment,
)
from app.indexing.builder import validate_index_directory
from app.indexing.manifest import (
    ArtifactFile,
    BM25Spec,
    EmbeddingSpec,
    FaissSpec,
    IndexManifest,
    serialize_index_manifest,
)
from app.indexing.store import activate_version
from app.retrieval.snapshot import V2IndexSnapshot
from app.utils import tokenize_for_bm25


EmbedText = Callable[[str], list[float]]
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_FIXTURE_EFFECTIVE_FROM = date(2026, 1, 1)
_AUTHORITY_LEVEL = 50
_TENANT_ID = "synthetic-tenant"
_REGION = "global"
_ACL_GROUPS = ["synthetic-employees"]
_DEPARTMENT = "synthetic-security"
_VARIANT = "authoritative"


@dataclass(frozen=True)
class LiveFixtureIndexBuild:
    index_root: Path
    version_path: Path
    manifest: IndexManifest
    manifest_sha256: str
    snapshot: V2IndexSnapshot
    embedding_call_count: int


def build_live_fixture_index(
    *,
    dataset: IndirectInjectionDataset,
    fixtures: FixtureManifest,
    root: Path,
    run_id: str,
    fixture_sha256: str,
    embedding_model: str,
    embed_text: EmbedText,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> LiveFixtureIndexBuild:
    """Project frozen post-parser fixtures into an isolated production-format index."""
    validate_dataset_fixture_alignment(dataset, fixtures)
    safe_run_id = _validate_run_id(run_id)
    if re.fullmatch(r"[0-9a-f]{64}", fixture_sha256) is None:
        raise ValueError("fixture SHA-256 must be a lowercase hexadecimal digest")
    if not embedding_model.strip():
        raise ValueError("embedding model is required")

    index_root = Path(root).resolve()
    versions_root = index_root / "versions"
    version_path = versions_root / safe_run_id
    if version_path.exists():
        raise FileExistsError(f"live fixture index already exists: {safe_run_id}")

    build_started = started_at or datetime.now(timezone.utc)
    _require_aware(build_started, "started_at")
    documents, chunks, parents = _project_records(dataset, fixtures, build_started)
    artifacts, dimension, embedding_call_count = _build_artifacts(
        documents,
        chunks,
        parents,
        embed_text,
    )
    build_finished = finished_at or datetime.now(timezone.utc)
    _require_aware(build_finished, "finished_at")
    if build_finished < build_started:
        raise ValueError("finished_at must not precede started_at")

    manifest = IndexManifest(
        schema_version="enterprise_index_manifest_v1",
        producer="enterprise_agentic_rag_v2",
        index_version="v2-security-fixture-projection-v1",
        run_id=safe_run_id,
        profile_id=f"r2-s1-d7-{dataset.split}-security-fixtures-v1",
        corpus_manifest_hash=fixture_sha256,
        embedding=EmbeddingSpec(
            model=embedding_model,
            dimension=dimension,
            normalization="l2",
        ),
        faiss=FaissSpec(index_type="IndexFlatIP", metric="inner_product"),
        bm25=BM25Spec(
            tokenizer="jieba",
            parameters={"k1": 1.5, "b": 0.75, "epsilon": 0.25},
        ),
        chunker_config={
            "mode": "post-parser-security-fixture-projection-v1",
            "chunk_size": 20_000,
            "overlap": 0,
        },
        parser_versions={"security_fixture_projection": "1"},
        source_document_count=len(documents),
        canonical_document_count=len(documents),
        duplicate_count=0,
        chunk_count=len(chunks) + len(parents),
        indexed_chunk_count=len(chunks),
        parent_chunk_count=len(parents),
        table_chunk_count=0,
        started_at=build_started,
        finished_at=build_finished,
        duration_ms=max(
            0,
            round((build_finished - build_started).total_seconds() * 1000),
        ),
        artifacts=_artifact_records(artifacts),
    )

    versions_root.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(prefix=f".{safe_run_id}.staging-", dir=versions_root)
    )
    try:
        for name, content in artifacts.items():
            (stage / name).write_bytes(content)
        manifest_bytes = serialize_index_manifest(manifest)
        (stage / "manifest.json").write_bytes(manifest_bytes)
        validate_index_directory(stage, manifest)
        if version_path.exists():
            raise FileExistsError(f"live fixture index already exists: {safe_run_id}")
        stage.rename(version_path)
    finally:
        if stage.exists():
            shutil.rmtree(stage)

    activate_version(index_root, safe_run_id, activated_at=build_finished)
    snapshot = V2IndexSnapshot.load(index_root)
    manifest_sha256 = hashlib.sha256(
        (version_path / "manifest.json").read_bytes()
    ).hexdigest()
    return LiveFixtureIndexBuild(
        index_root=index_root,
        version_path=version_path,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        snapshot=snapshot,
        embedding_call_count=embedding_call_count,
    )


def _project_records(
    dataset: IndirectInjectionDataset,
    fixtures: FixtureManifest,
    ingested_at: datetime,
) -> tuple[list[DocumentRecord], list[ChunkRecord], list[ChunkRecord]]:
    case_ids = {case.case_id for case in dataset.cases}
    fixture_by_id = {case.case_id: case for case in fixtures.cases}
    if set(fixture_by_id) != case_ids:
        raise ValueError("dataset and fixture case IDs differ")

    candidates_by_document: dict[str, list[tuple[str, FixtureCandidate]]] = defaultdict(list)
    opens_by_document: dict[str, list[tuple[str, object]]] = defaultdict(list)
    document_case: dict[str, str] = {}
    for case in fixtures.cases:
        for candidate in case.candidates:
            _bind_document_case(document_case, candidate.document_id, case.case_id)
            candidates_by_document[candidate.document_id].append(
                (case.case_id, candidate)
            )
        for opened in case.open_results:
            _bind_document_case(document_case, opened.document_id, case.case_id)
            opens_by_document[opened.document_id].append((case.case_id, opened))

    documents: list[DocumentRecord] = []
    document_by_id: dict[str, DocumentRecord] = {}
    for document_id in sorted(document_case):
        candidates = candidates_by_document[document_id]
        opened = opens_by_document[document_id]
        document = _document_record(
            document_id=document_id,
            case_id=document_case[document_id],
            candidates=candidates,
            opened=opened,
            ingested_at=ingested_at,
        )
        documents.append(document)
        document_by_id[document_id] = document

    chunks: list[ChunkRecord] = []
    parents: list[ChunkRecord] = []
    for fixture_case in fixtures.cases:
        for candidate in fixture_case.candidates:
            document = document_by_id[candidate.document_id]
            chunks.append(
                _chunk_record(
                    candidate,
                    document,
                    case_id=fixture_case.case_id,
                )
            )
        parents.extend(
            _parent_records(
                fixture_case,
                document_by_id,
            )
        )
    return documents, chunks, parents


def _bind_document_case(
    document_case: dict[str, str],
    document_id: str,
    case_id: str,
) -> None:
    previous = document_case.setdefault(document_id, case_id)
    if previous != case_id:
        raise ValueError("a live fixture document cannot belong to multiple cases")


def _document_record(
    *,
    document_id: str,
    case_id: str,
    candidates: list[tuple[str, FixtureCandidate]],
    opened: list[tuple[str, object]],
    ingested_at: datetime,
) -> DocumentRecord:
    if not candidates:
        raise ValueError("fixture document requires at least one indexed candidate")
    candidate_values = [item for _, item in candidates]
    titles = {
        item.document_title for item in candidate_values if item.document_title is not None
    }
    if len(titles) > 1:
        raise ValueError("fixture document has inconsistent titles")
    versions = {item.version for item in candidate_values}
    if len(versions) != 1:
        raise ValueError("fixture document has inconsistent versions")
    if len({item.content for _, item in opened}) > 1:
        raise ValueError("fixture document has inconsistent open content")

    text = (
        opened[0][1].content
        if opened
        else "\n".join(
            item.matched_text
            for item in sorted(
                candidate_values,
                key=lambda value: (
                    value.locator_start,
                    value.locator_end or value.locator_start,
                    value.chunk_id,
                ),
            )
        )
    )
    source_path = candidate_values[0].source_path
    source_format = Path(source_path).suffix.lstrip(".").casefold() or "txt"
    version = next(iter(versions))
    checksum = _digest(source_path + "\0" + text)
    text_hash = _digest(text)
    fact_ids = sorted(
        {fact_id for item in candidate_values for fact_id in item.fact_ids}
    )
    return DocumentRecord(
        doc_id=document_id,
        title=next(iter(titles), "Synthetic security fixture"),
        source_type="security_fixture",
        source_path=source_path,
        format=source_format,
        department=_DEPARTMENT,
        filed_department=_DEPARTMENT,
        policy_id=case_id,
        region=_REGION,
        tenant_id=_TENANT_ID,
        acl_groups=list(_ACL_GROUPS),
        document_version=DocumentVersion(
            version_id=f"{document_id}-version",
            version=version,
            status="active",
            effective_from=_FIXTURE_EFFECTIVE_FROM,
            authority_level=_AUTHORITY_LEVEL,
        ),
        authority_level=_AUTHORITY_LEVEL,
        checksum=checksum,
        normalized_text_hash=text_hash,
        ingested_at=ingested_at,
        parser_name="security_fixture_projection",
        parser_version="1",
        text=text,
        fact_ids=fact_ids,
        variant=_VARIANT,
    )


def _chunk_record(
    candidate: FixtureCandidate,
    document: DocumentRecord,
    *,
    case_id: str,
) -> ChunkRecord:
    locator_kind = {
        "paragraph": "paragraph",
        "table": "row",
        "document": "document",
    }[candidate.locator_kind]
    return ChunkRecord(
        chunk_id=candidate.chunk_id,
        doc_id=candidate.document_id,
        parent_chunk_id=candidate.parent_chunk_id,
        kind="child" if candidate.parent_chunk_id else "section",
        indexable=True,
        text=candidate.matched_text,
        section_path=list(candidate.section_path),
        locator=SourceLocator(
            kind=locator_kind,
            start=candidate.locator_start,
            end=candidate.locator_end,
        ),
        source_path=candidate.source_path,
        format=document.format,
        source_type=document.source_type,
        policy_id=case_id,
        department=document.department,
        filed_department=document.filed_department,
        tenant_id=document.tenant_id,
        region=document.region,
        acl_groups=list(document.acl_groups),
        version_id=document.document_version.version_id,
        version=candidate.version,
        status="active",
        effective_from=_FIXTURE_EFFECTIVE_FROM,
        authority_level=_AUTHORITY_LEVEL,
        fact_ids=list(candidate.fact_ids),
        variant=_VARIANT,
        checksum=document.checksum,
        text_hash=_digest(candidate.matched_text),
    )


def _parent_records(
    fixture: FixtureCase,
    document_by_id: dict[str, DocumentRecord],
) -> list[ChunkRecord]:
    result: list[ChunkRecord] = []
    candidate_by_id = {item.chunk_id: item for item in fixture.candidates}
    for link in fixture.parent_links:
        children = [candidate_by_id[chunk_id] for chunk_id in link.child_chunk_ids]
        parent_expansion_flags = {item.context_from_parent for item in children}
        if len(parent_expansion_flags) != 1:
            raise ValueError("fixture parent children mix parent-expansion semantics")
        first = children[0]
        document = document_by_id[link.document_id]
        if first.context_from_parent:
            contexts = {item.context_text for item in children}
            if len(contexts) != 1:
                raise ValueError("fixture parent children have inconsistent context")
            text = next(iter(contexts))
        else:
            # The deterministic fixture keeps split payload fragments as separate
            # child contexts. Production retrieval reconstructs their shared parent.
            text = "\n".join(item.matched_text for item in children)
        result.append(
            ChunkRecord(
                chunk_id=link.parent_chunk_id,
                doc_id=link.document_id,
                kind="parent",
                indexable=False,
                text=text,
                section_path=list(first.section_path),
                locator=SourceLocator(
                    kind="paragraph",
                    start=first.locator_start,
                    end=children[-1].locator_end or children[-1].locator_start,
                ),
                source_path=first.source_path,
                format=document.format,
                source_type=document.source_type,
                policy_id=fixture.case_id,
                department=document.department,
                filed_department=document.filed_department,
                tenant_id=document.tenant_id,
                region=document.region,
                acl_groups=list(document.acl_groups),
                version_id=document.document_version.version_id,
                version=first.version,
                status="active",
                effective_from=_FIXTURE_EFFECTIVE_FROM,
                authority_level=_AUTHORITY_LEVEL,
                fact_ids=sorted(
                    {fact_id for item in children for fact_id in item.fact_ids}
                ),
                variant=_VARIANT,
                checksum=document.checksum,
                text_hash=_digest(text),
            )
        )
    return result


def _build_artifacts(
    documents: list[DocumentRecord],
    chunks: list[ChunkRecord],
    parents: list[ChunkRecord],
    embed_text: EmbedText,
) -> tuple[dict[str, bytes], int, int]:
    if not chunks:
        raise ValueError("live fixture index has no indexed chunks")
    vectors: list[list[float]] = []
    dimension: int | None = None
    for chunk in chunks:
        vector = list(embed_text(chunk.text))
        if not vector:
            raise ValueError(f"embedding is empty for chunk {chunk.chunk_id!r}")
        if dimension is None:
            dimension = len(vector)
        elif len(vector) != dimension:
            raise ValueError("live fixture embeddings have inconsistent dimensions")
        vectors.append(vector)
    array = np.asarray(vectors, dtype="float32")
    if not np.isfinite(array).all():
        raise ValueError("live fixture embedding contains non-finite values")
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("live fixture embedding cannot be a zero vector")
    array = array / norms
    index = faiss.IndexFlatIP(array.shape[1])
    index.add(array)
    tokens = [tokenize_for_bm25(chunk.text) for chunk in chunks]
    if any(not row for row in tokens):
        raise ValueError("live fixture BM25 rows cannot be empty")
    artifacts = {
        "documents.json": _model_json_bytes(documents),
        "chunks.json": _model_json_bytes(chunks),
        "parents.json": _model_json_bytes(parents),
        "bm25_tokens.pkl": pickle.dumps(tokens, protocol=pickle.HIGHEST_PROTOCOL),
        "faiss.index": faiss.serialize_index(index).tobytes(),
    }
    return artifacts, int(array.shape[1]), len(vectors)


def _model_json_bytes(models: list[BaseModel]) -> bytes:
    payload = [model.model_dump(mode="json") for model in models]
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _artifact_records(artifacts: dict[str, bytes]) -> list[ArtifactFile]:
    return [
        ArtifactFile(
            path=name,
            sha256=hashlib.sha256(content).hexdigest(),
            byte_count=len(content),
        )
        for name, content in sorted(artifacts.items())
    ]


def _validate_run_id(value: str) -> str:
    if _RUN_ID_PATTERN.fullmatch(value) is None or value in {".", ".."}:
        raise ValueError("live fixture index run ID contains unsafe characters")
    return value


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = ["LiveFixtureIndexBuild", "build_live_fixture_index"]
