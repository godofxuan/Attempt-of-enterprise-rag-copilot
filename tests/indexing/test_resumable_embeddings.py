from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.corpus.artifacts import write_corpus
from app.corpus.generator import load_facts, load_profile
from app.domain.documents import ChunkRecord
from app.indexing.resumable_embeddings import ResumableBatchEmbedder
from app.ingestion.chunking import ChunkerConfig, chunk_document
from app.ingestion.normalize import ingest_corpus
from app.ingestion.versions import govern_documents


ROOT = Path(__file__).resolve().parents[2]
FACTS = ROOT / "data" / "v2" / "facts" / "company_facts_v1.json"
PROFILE = ROOT / "data" / "v2" / "config" / "demo.json"


class FakeBatchClient:
    def __init__(
        self,
        *,
        model_sha256: str = "a" * 64,
        fail_after: int | None = None,
    ) -> None:
        self.model_identifier = "fake-batch"
        self.model_sha256 = model_sha256
        self.dimension = 3
        self.fail_after = fail_after
        self.calls: list[list[str]] = []

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise RuntimeError("injected batch failure")
        self.calls.append(list(texts))
        return np.asarray(
            [
                [
                    float(len(text) + 1),
                    float((sum(map(ord, text)) % 101) + 1),
                    1.0,
                ]
                for text in texts
            ],
            dtype="float32",
        )


class FailOnUseClient(FakeBatchClient):
    def embed_batch(self, texts: list[str]) -> np.ndarray:
        raise AssertionError("complete cache hit must not call the model")


def _chunks(tmp_path: Path, count: int = 5) -> list[ChunkRecord]:
    corpus = tmp_path / "corpus"
    write_corpus(corpus, load_facts(FACTS), load_profile(PROFILE))
    governed = govern_documents(ingest_corpus(corpus))
    config = ChunkerConfig(mode="fixed", chunk_size=500, overlap=80)
    chunks = [
        chunk
        for document in governed.documents
        for chunk in chunk_document(document, config)
        if chunk.indexable
    ]
    return chunks[:count]


def _provider(
    *,
    cache_root: Path,
    client: FakeBatchClient,
    batch_size: int = 2,
) -> ResumableBatchEmbedder:
    return ResumableBatchEmbedder(
        cache_root=cache_root,
        client=client,
        corpus_manifest_sha256="b" * 64,
        parser_versions={"markdown": "1"},
        chunker_config=ChunkerConfig(mode="fixed", chunk_size=500, overlap=80),
        batch_size=batch_size,
        max_batch_chars=100_000,
    )


def test_resumable_embedder_reuses_complete_hash_bound_shards(
    tmp_path: Path,
) -> None:
    chunks = _chunks(tmp_path)
    cache_root = tmp_path / "cache"
    first_client = FakeBatchClient()
    first = _provider(cache_root=cache_root, client=first_client)

    expected = first(chunks)

    assert len(first_client.calls) == 3
    assert first.summary is not None
    assert first.summary.computed_batches == 3
    assert first.summary.cache_hit_batches == 0
    np.testing.assert_allclose(np.linalg.norm(expected, axis=1), 1.0)

    second = _provider(
        cache_root=cache_root,
        client=FailOnUseClient(),
    )
    actual = second(chunks)

    np.testing.assert_array_equal(actual, expected)
    assert second.summary is not None
    assert second.summary.cache_hit_batches == 3
    assert second.summary.computed_batches == 0
    assert second.summary.build_id == first.summary.build_id


def test_resumable_embedder_continues_after_interrupted_batch(
    tmp_path: Path,
) -> None:
    chunks = _chunks(tmp_path)
    cache_root = tmp_path / "cache"
    interrupted_client = FakeBatchClient(fail_after=1)
    interrupted = _provider(
        cache_root=cache_root,
        client=interrupted_client,
    )

    with pytest.raises(RuntimeError, match="injected"):
        interrupted(chunks)

    assert len(interrupted_client.calls) == 1
    resumed_client = FakeBatchClient()
    resumed = _provider(cache_root=cache_root, client=resumed_client)
    result = resumed(chunks)

    assert result.shape == (5, 3)
    assert len(resumed_client.calls) == 2
    assert resumed.summary is not None
    assert resumed.summary.cache_hit_batches == 1
    assert resumed.summary.computed_batches == 2


def test_resumable_embedder_recomputes_a_corrupt_shard_only(
    tmp_path: Path,
) -> None:
    chunks = _chunks(tmp_path)
    cache_root = tmp_path / "cache"
    first = _provider(cache_root=cache_root, client=FakeBatchClient())
    first(chunks)
    assert first.summary is not None
    shard = sorted(first.summary.cache_dir.glob("*.npy"))[1]
    shard.write_bytes(b"corrupt")

    repair_client = FakeBatchClient()
    repaired = _provider(cache_root=cache_root, client=repair_client)
    repaired(chunks)

    assert len(repair_client.calls) == 1
    assert repaired.summary is not None
    assert repaired.summary.cache_hit_batches == 2
    assert repaired.summary.recomputed_batches == 1


def test_resumable_embedder_model_digest_changes_build_identity(
    tmp_path: Path,
) -> None:
    chunks = _chunks(tmp_path)
    cache_root = tmp_path / "cache"
    first = _provider(cache_root=cache_root, client=FakeBatchClient())
    first(chunks)
    changed_client = FakeBatchClient(model_sha256="c" * 64)
    changed = _provider(cache_root=cache_root, client=changed_client)
    changed(chunks)

    assert first.summary is not None
    assert changed.summary is not None
    assert changed.summary.build_id != first.summary.build_id
    assert len(changed_client.calls) == 3


def test_resumable_embedder_rejects_chunk_over_character_budget(
    tmp_path: Path,
) -> None:
    chunks = _chunks(tmp_path, count=1)
    provider = ResumableBatchEmbedder(
        cache_root=tmp_path / "cache",
        client=FakeBatchClient(),
        corpus_manifest_sha256="b" * 64,
        parser_versions={"markdown": "1"},
        chunker_config=ChunkerConfig(mode="fixed", chunk_size=500, overlap=80),
        batch_size=2,
        max_batch_chars=1,
    )

    with pytest.raises(ValueError, match="exceeds max_batch_chars"):
        provider(chunks)
