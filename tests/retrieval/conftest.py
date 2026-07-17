from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from pathlib import Path
from types import MappingProxyType

import faiss
import numpy as np
import pytest
from rank_bm25 import BM25Okapi

from app.corpus.artifacts import write_corpus
from app.corpus.generator import load_facts, load_profile
from app.domain.documents import (
    ChunkRecord,
    DocumentRecord,
    DocumentVersion,
    SourceLocator,
)
from app.indexing.manifest import (
    ArtifactFile,
    BM25Spec,
    EmbeddingSpec,
    FaissSpec,
    IndexManifest,
)
from app.indexing.store import build_index_version
from app.indexing.store import LoadedIndexVersion
from app.ingestion.chunking import ChunkerConfig
from app.retrieval.snapshot import V2IndexSnapshot
from app.utils import tokenize_for_bm25


ROOT = Path(__file__).resolve().parents[2]
FACTS = ROOT / "data" / "v2" / "facts" / "company_facts_v1.json"
PROFILE = ROOT / "data" / "v2" / "config" / "demo.json"


def fake_embedding(text: str) -> list[float]:
    total = sum(ord(character) for character in text)
    return [
        float((total % 97) + 1),
        float((len(text) % 31) + 1),
        float((total % 17) + 1),
        1.0,
    ]


@pytest.fixture(scope="session")
def v2_index_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("e3-snapshot")
    corpus = base / "corpus"
    index_root = base / "indexes-v2"
    write_corpus(corpus, load_facts(FACTS), load_profile(PROFILE))
    build_index_version(
        root=index_root,
        input_dir=corpus,
        run_id="parent-child-run",
        chunker_config=ChunkerConfig(
            mode="parent_child",
            parent_size=1000,
            child_size=250,
            overlap=80,
        ),
        embedding_model="fake-4d",
        embed_text=fake_embedding,
        activate=True,
    )
    return index_root


@pytest.fixture
def chunk_factory():
    def build(**updates) -> ChunkRecord:
        text = updates.pop("text", "Policy text")
        values = {
            "chunk_id": "doc-a::fixed::001",
            "doc_id": "doc-a",
            "parent_chunk_id": None,
            "kind": "fixed",
            "indexable": True,
            "text": text,
            "section_path": ["Policy"],
            "locator": SourceLocator(kind="document", start=1),
            "source_path": "documents/doc-a.md",
            "format": "md",
            "source_type": "policy",
            "policy_id": "policy-a",
            "department": "hr",
            "filed_department": "hr",
            "tenant_id": "tenant-one",
            "region": "cn",
            "acl_groups": ["employees"],
            "version_id": "policy-a@2026",
            "version": "2026",
            "status": "active",
            "effective_from": date(2026, 1, 1),
            "effective_to": None,
            "supersedes_doc_id": None,
            "authority_level": 100,
            "fact_ids": ["fact-a"],
            "variant": "authoritative",
            "checksum": hashlib.sha256(b"doc-a").hexdigest(),
            "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
        values.update(updates)
        if "text" in updates and "text_hash" not in updates:
            values["text_hash"] = hashlib.sha256(
                str(updates["text"]).encode("utf-8")
            ).hexdigest()
        return ChunkRecord(**values)

    return build


@pytest.fixture
def document_factory():
    def build(**updates) -> DocumentRecord:
        text = updates.pop("text", "Policy document text")
        values = {
            "doc_id": "doc-a",
            "title": "Policy A",
            "source_type": "policy",
            "source_path": "documents/doc-a.md",
            "format": "md",
            "department": "hr",
            "filed_department": "hr",
            "project_id": None,
            "policy_id": "policy-a",
            "region": "cn",
            "tenant_id": "tenant-one",
            "acl_groups": ["employees"],
            "document_version": DocumentVersion(
                version_id="policy-a@2026",
                version="2026",
                status="active",
                effective_from=date(2026, 1, 1),
                effective_to=None,
                authority_level=100,
            ),
            "authority_level": 100,
            "checksum": hashlib.sha256(b"doc-a").hexdigest(),
            "normalized_text_hash": hashlib.sha256(
                text.encode("utf-8")
            ).hexdigest(),
            "ingested_at": datetime(2026, 7, 16, tzinfo=timezone.utc),
            "parser_name": "synthetic",
            "parser_version": "1.0",
            "text": text,
            "sections": [],
            "tables": [],
            "parse_warnings": [],
            "fact_ids": ["fact-a"],
            "variant": "authoritative",
            "duplicate_of": None,
        }
        values.update(updates)
        if "text" in updates and "normalized_text_hash" not in updates:
            values["normalized_text_hash"] = hashlib.sha256(
                str(updates["text"]).encode("utf-8")
            ).hexdigest()
        return DocumentRecord(**values)

    return build


@pytest.fixture
def snapshot_factory(tmp_path: Path):
    def build(
        chunks: list[ChunkRecord],
        *,
        parents: list[ChunkRecord] | None = None,
        documents: list[DocumentRecord] | None = None,
        vectors: list[list[float]] | None = None,
        tokens: list[list[str]] | None = None,
        run_id: str = "synthetic-run",
    ) -> V2IndexSnapshot:
        parents = parents or []
        documents = documents or []
        vectors = vectors or [
            [float(index + 1), 1.0] for index in range(len(chunks))
        ]
        if len(vectors) != len(chunks) or not vectors:
            raise ValueError("vectors must align with non-empty chunks")
        array = np.asarray(vectors, dtype="float32")
        norms = np.linalg.norm(array, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        array = array / norms
        index = faiss.IndexFlatIP(array.shape[1])
        index.add(array)
        raw_tokens = tokens or [tokenize_for_bm25(chunk.text) for chunk in chunks]
        bm25_tokens = tuple(tuple(token for token in row) for row in raw_tokens)
        bm25 = BM25Okapi([list(row) for row in bm25_tokens])
        doc_count = len(documents) or len(
            {chunk.doc_id for chunk in [*chunks, *parents]}
        )
        now = datetime(2026, 7, 16, tzinfo=timezone.utc)
        manifest = IndexManifest(
            schema_version="enterprise_index_manifest_v1",
            producer="enterprise_agentic_rag_v2",
            index_version="v2",
            run_id=run_id,
            profile_id="synthetic",
            corpus_manifest_hash="a" * 64,
            embedding=EmbeddingSpec(
                model="fake",
                dimension=array.shape[1],
                normalization="l2",
            ),
            faiss=FaissSpec(index_type="IndexFlatIP", metric="inner_product"),
            bm25=BM25Spec(tokenizer="jieba", parameters={}),
            chunker_config={"mode": "synthetic"},
            parser_versions={"synthetic": "1.0"},
            source_document_count=doc_count,
            canonical_document_count=doc_count,
            duplicate_count=0,
            chunk_count=len(chunks) + len(parents),
            indexed_chunk_count=len(chunks),
            parent_chunk_count=len(parents),
            table_chunk_count=sum(chunk.kind == "table" for chunk in chunks),
            started_at=now,
            finished_at=now,
            duration_ms=0,
            artifacts=[
                ArtifactFile(path="synthetic.bin", sha256="b" * 64, byte_count=0)
            ],
        )
        version = LoadedIndexVersion(
            path=tmp_path / "versions" / run_id,
            manifest=manifest,
            manifest_sha256="c" * 64,
        )
        parent_map = {parent.chunk_id: parent for parent in parents}
        document_map = {document.doc_id: document for document in documents}
        chunk_index = {chunk.chunk_id: offset for offset, chunk in enumerate(chunks)}
        all_chunks = {**parent_map, **{chunk.chunk_id: chunk for chunk in chunks}}
        return V2IndexSnapshot(
            version=version,
            faiss_index=index,
            bm25=bm25,
            bm25_tokens=bm25_tokens,
            chunks=tuple(chunks),
            parents_by_id=MappingProxyType(parent_map),
            documents_by_id=MappingProxyType(document_map),
            chunk_index_by_id=MappingProxyType(chunk_index),
            all_chunks_by_id=MappingProxyType(all_chunks),
        )

    return build
