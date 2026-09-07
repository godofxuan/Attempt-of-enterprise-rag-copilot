"""Retrieval-only adapter. Reuses exact vectors/text; does not enable document open.

Public WixQA articles receive explicit benchmark-only ACL/version metadata.
No labels enter retrieval metadata. Original artifact hashes remain attached.
"""

import hashlib
from datetime import UTC, date, datetime
from pathlib import Path
from types import MappingProxyType

from app.domain.documents import ChunkRecord, SourceLocator
from app.indexing.manifest import IndexManifest, serialize_index_manifest
from app.indexing.store import LoadedIndexVersion
from app.retrieval.snapshot import V2IndexSnapshot


def adapt_wixqa_snapshot(index, source_path: Path) -> V2IndexSnapshot:
    chunks = []
    for item in index.chunks:
        if hashlib.sha256(item.text.encode()).hexdigest() != item.text_hash:
            raise ValueError("source chunk text hash mismatch")
        chunks.append(
            ChunkRecord(
                chunk_id=item.chunk_id,
                doc_id=item.article_id,
                kind="fixed",
                indexable=True,
                text=item.text,
                section_path=["WixQA article"],
                locator=SourceLocator(
                    kind="paragraph",
                    start=item.ordinal,
                    label="source chunk ordinal; not original paragraph",
                ),
                source_path=f"wixqa/{item.article_id}",
                format="text",
                source_type="public_benchmark",
                policy_id=item.article_id,
                department="benchmark",
                filed_department="benchmark",
                tenant_id="wixqa-benchmark",
                region="global",
                acl_groups=["benchmark"],
                version_id=index.manifest.run_id,
                version="frozen",
                status="active",
                effective_from=date(2026, 1, 1),
                authority_level=50,
                variant="authoritative",
                checksum=item.text_hash,
                text_hash=item.text_hash,
            )
        )
    original = index.manifest
    stamp = datetime(2026, 9, 5, tzinfo=UTC)
    manifest = IndexManifest(
        schema_version="enterprise_index_manifest_v1",
        producer="enterprise_agentic_rag_v2",
        index_version="retrieval-only-wixqa-adapter-v1",
        run_id=original.run_id,
        profile_id="public-wixqa-retrieval-only",
        corpus_manifest_hash=original.dataset_manifest_sha256,
        embedding={
            "model": original.embedding_model,
            "dimension": original.embedding_dimension,
            "normalization": "l2",
        },
        faiss={"index_type": "IndexFlatIP", "metric": "inner_product"},
        bm25={"tokenizer": "jieba", "parameters": {"k1": 1.5, "b": 0.75}},
        chunker_config={
            "source": "unchanged",
            "size": original.chunk_size,
            "overlap": original.overlap,
        },
        parser_versions={"adapter": "retrieval-only-v1"},
        source_document_count=original.article_count,
        canonical_document_count=original.article_count,
        duplicate_count=0,
        chunk_count=len(chunks),
        indexed_chunk_count=len(chunks),
        parent_chunk_count=0,
        table_chunk_count=0,
        started_at=stamp,
        finished_at=stamp,
        duration_ms=0,
        artifacts=[item.model_dump() for item in original.artifacts],
    )
    version = LoadedIndexVersion(
        path=source_path,
        manifest=manifest,
        manifest_sha256=hashlib.sha256(serialize_index_manifest(manifest)).hexdigest(),
    )
    return V2IndexSnapshot(
        version=version,
        faiss_index=index.faiss_index,
        bm25=index.bm25,
        bm25_tokens=(),
        chunks=tuple(chunks),
        parents_by_id=MappingProxyType({}),
        documents_by_id=MappingProxyType({}),
        chunk_index_by_id=MappingProxyType({item.chunk_id: i for i, item in enumerate(chunks)}),
        all_chunks_by_id=MappingProxyType({item.chunk_id: item for item in chunks}),
    )
