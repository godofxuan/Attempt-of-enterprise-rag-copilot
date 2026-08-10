import hashlib
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path

import pytest

import app.indexing.computation_cache as cache_module
from app.domain.documents import ParseResult, ParsedSection, SourceLocator
from app.indexing.computation_cache import (
    ChunkArtifactKey,
    ChunkLayoutArtifact,
    ChunkLayoutItem,
    ComponentFingerprint,
    ComputationCacheError,
    EmbeddingArtifactKey,
    EmbeddingFingerprint,
    EmbeddingVectorArtifact,
    NormalizedArtifactKey,
    NormalizedContentArtifact,
    ParsedArtifactKey,
    ParsedContentArtifact,
    PersistentComputationCache,
    cache_payload_sha256,
    chunker_config_sha256,
    pipeline_fingerprint_sha256,
)
from app.ingestion.chunking import ChunkerConfig


CONTENT_SHA = "1" * 64


def _parsed_key(*, tenant_id: str = "tenant-a") -> ParsedArtifactKey:
    return ParsedArtifactKey(
        tenant_id=tenant_id,
        source_system="sharepoint",
        source_key="policy/leave",
        document_id="doc-leave",
        content_sha256=CONTENT_SHA,
        declared_media_type="text/markdown",
        parser=ComponentFingerprint(
            name="markdown",
            semantic_version="1",
            implementation_sha256="3" * 64,
            dependency_versions=("stdlib=3.13",),
        ),
    )


def _parsed_result() -> ParseResult:
    return ParseResult(
        text="Employees receive ten days of annual leave.",
        sections=[
            ParsedSection(
                heading="Leave",
                level=1,
                path=["Leave"],
                text="Employees receive ten days of annual leave.",
                locator=SourceLocator(kind="line", start=1, end=1),
            )
        ],
        headings=["Leave"],
        source_location="staged-asset",
        parser_name="markdown",
        parser_version="1",
    )


def _store_parsed_in_process(root_text: str, start_at: float) -> str:
    while time.time() < start_at:
        time.sleep(0.005)
    cache = PersistentComputationCache(Path(root_text))
    result = cache.store_parsed(
        _parsed_key(),
        ParsedContentArtifact.from_parse_result(_parsed_result()),
    )
    return result.status


def test_parsed_cache_exact_replay_is_a_hit_but_other_tenant_is_a_miss(
    tmp_path: Path,
) -> None:
    cache = PersistentComputationCache(tmp_path / "private-cache")
    key = _parsed_key()
    parsed = ParsedContentArtifact.from_parse_result(_parsed_result())

    assert cache.load_parsed(key) is None
    assert cache.store_parsed(key, parsed).status == "STORED"
    assert cache.load_parsed(key) == parsed
    assert cache.store_parsed(key, parsed).status == "REUSED"

    assert cache.load_parsed(_parsed_key(tenant_id="tenant-b")) is None


def test_transaction_reuses_secure_acl_without_rewriting_every_entry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cache = PersistentComputationCache(tmp_path / "private-cache")
    parsed = ParsedContentArtifact.from_parse_result(_parsed_result())
    original_harden = cache_module.harden_private_directory
    original_held_harden = cache_module.harden_held_private_directory
    harden_calls = 0
    held_harden_calls = 0

    def counted_harden(path: Path) -> None:
        nonlocal harden_calls
        harden_calls += 1
        original_harden(path)

    def counted_held_harden(*args, **kwargs) -> None:
        nonlocal held_harden_calls
        held_harden_calls += 1
        original_held_harden(*args, **kwargs)

    monkeypatch.setattr(
        cache_module,
        "harden_private_directory",
        counted_harden,
    )
    monkeypatch.setattr(
        cache_module,
        "harden_held_private_directory",
        counted_held_harden,
    )

    with cache.transaction():
        assert cache.store_parsed(_parsed_key(), parsed).status == "STORED"
        assert cache.load_parsed(_parsed_key()) == parsed
        with cache.transaction():
            assert (
                cache.store_parsed(
                    _parsed_key(tenant_id="tenant-b"),
                    parsed,
                ).status
                == "STORED"
            )

    assert held_harden_calls == 1
    assert harden_calls == 0
    assert cache.load_parsed(_parsed_key(tenant_id="tenant-b")) == parsed
    assert held_harden_calls == 1
    assert harden_calls == 0


def test_normalized_cache_binds_parsed_output_and_normalizer_fingerprint(
    tmp_path: Path,
) -> None:
    cache = PersistentComputationCache(tmp_path / "private-cache")
    parsed = ParsedContentArtifact.from_parse_result(_parsed_result())
    normalizer = ComponentFingerprint(
        name="enterprise-normalizer",
        semantic_version="1",
        implementation_sha256="4" * 64,
        dependency_versions=("pydantic=2",),
    )
    normalized_sha256 = hashlib.sha256(parsed.text.encode("utf-8")).hexdigest()
    key = NormalizedArtifactKey(
        tenant_id="tenant-a",
        source_system="sharepoint",
        source_key="policy/leave",
        document_id="doc-leave",
        content_sha256=CONTENT_SHA,
        expected_normalized_sha256=normalized_sha256,
        parsed_artifact_sha256=cache_payload_sha256(parsed),
        parser=_parsed_key().parser,
        normalizer=normalizer,
    )
    normalized = NormalizedContentArtifact(
        title="Leave",
        text=parsed.text,
        sections=parsed.sections,
        tables=parsed.tables,
        parse_warnings=parsed.parse_warnings,
        normalized_sha256=normalized_sha256,
    )

    assert cache.load_normalized(key) is None
    assert cache.store_normalized(key, normalized).status == "STORED"
    assert cache.load_normalized(key) == normalized

    changed = key.model_copy(
        update={
            "normalizer": normalizer.model_copy(
                update={"implementation_sha256": "7" * 64}
            )
        }
    )
    assert cache.load_normalized(changed) is None


def test_chunk_layout_cache_binds_chunker_implementation_and_config(
    tmp_path: Path,
) -> None:
    cache = PersistentComputationCache(tmp_path / "private-cache")
    config = ChunkerConfig(mode="fixed", chunk_size=64, overlap=8)
    chunker = ComponentFingerprint(
        name="enterprise-chunker",
        semantic_version="1",
        implementation_sha256="8" * 64,
        dependency_versions=("pydantic=2",),
    )
    parser = _parsed_key().parser
    normalizer = ComponentFingerprint(
        name="enterprise-normalizer",
        semantic_version="1",
        implementation_sha256="4" * 64,
        dependency_versions=("pydantic=2",),
    )
    key = ChunkArtifactKey(
        tenant_id="tenant-a",
        source_system="sharepoint",
        source_key="policy/leave",
        document_id="doc-leave",
        normalized_sha256="6" * 64,
        normalized_artifact_sha256="9" * 64,
        parser=parser,
        normalizer=normalizer,
        chunker=chunker,
        chunker_config_sha256=chunker_config_sha256(config),
    )
    layout = ChunkLayoutArtifact(
        chunks=(
            ChunkLayoutItem(
                ordinal=1,
                chunk_id="doc-leave::fixed::abc",
                kind="fixed",
                indexable=True,
                text="Employees receive ten days of annual leave.",
                section_path=("Leave",),
                locator=SourceLocator(kind="character", start=1, end=44),
            ),
        )
    )

    assert cache.store_chunks(key, layout).status == "STORED"
    assert cache.load_chunks(key) == layout

    changed_config = ChunkerConfig(mode="fixed", chunk_size=80, overlap=8)
    assert cache.load_chunks(
        key.model_copy(
            update={
                "chunker_config_sha256": chunker_config_sha256(changed_config)
            }
        )
    ) is None
    assert cache.load_chunks(
        key.model_copy(
            update={
                "chunker": chunker.model_copy(
                    update={"implementation_sha256": "a" * 64}
                )
            }
        )
    ) is None
    assert cache.load_chunks(
        key.model_copy(
            update={
                "normalizer": normalizer.model_copy(
                    update={"implementation_sha256": "b" * 64}
                )
            }
        )
    ) is None


def test_embedding_cache_binds_model_digest_backend_dimension_and_pipeline(
    tmp_path: Path,
) -> None:
    cache = PersistentComputationCache(tmp_path / "private-cache")
    embedding = EmbeddingFingerprint(
        component=ComponentFingerprint(
            name="ollama-embed-client",
            semantic_version="1",
            implementation_sha256="b" * 64,
            dependency_versions=("requests=2",),
        ),
        backend="ollama",
        model_identifier="bge-m3",
        model_sha256="c" * 64,
        dimension=4,
        normalization="l2",
    )
    parser = _parsed_key().parser
    normalizer = ComponentFingerprint(
        name="enterprise-normalizer",
        semantic_version="1",
        implementation_sha256="4" * 64,
        dependency_versions=("pydantic=2",),
    )
    chunker = ComponentFingerprint(
        name="enterprise-chunker",
        semantic_version="1",
        implementation_sha256="8" * 64,
        dependency_versions=("pydantic=2",),
    )
    chunker_config = ChunkerConfig(mode="fixed", chunk_size=64, overlap=8)
    pipeline_sha256 = pipeline_fingerprint_sha256(
        parser=parser,
        normalizer=normalizer,
        chunker=chunker,
        chunker_config=chunker_config,
    )
    text = "Employees receive ten days of annual leave."
    key = EmbeddingArtifactKey(
        tenant_id="tenant-a",
        source_system="sharepoint",
        source_key="policy/leave",
        document_id="doc-leave",
        chunk_text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        content_pipeline_sha256=pipeline_sha256,
        embedding=embedding,
    )
    vector = EmbeddingVectorArtifact(vector=(1.0, 0.0, 0.0, 0.0))

    assert cache.store_embedding(key, vector).status == "STORED"
    assert cache.load_embedding(key) == vector
    assert cache.load_embedding(
        key.model_copy(
            update={
                "embedding": embedding.model_copy(
                    update={"model_sha256": "d" * 64}
                )
            }
        )
    ) is None
    assert cache.load_embedding(
        key.model_copy(
            update={"content_pipeline_sha256": "e" * 64}
        )
    ) is None
    assert cache.load_embedding(
        key.model_copy(
            update={
                "embedding": embedding.model_copy(
                    update={"backend": "local-test"}
                )
            }
        )
    ) is None
    assert cache.load_embedding(
        key.model_copy(
            update={
                "embedding": embedding.model_copy(
                    update={"model_identifier": "bge-m3-v2"}
                )
            }
        )
    ) is None
    assert cache.load_embedding(
        key.model_copy(
            update={
                "embedding": embedding.model_copy(update={"dimension": 3})
            }
        )
    ) is None
    assert cache.load_embedding(
        key.model_copy(update={"tenant_id": "tenant-b"})
    ) is None

    with pytest.raises(ValueError, match="finite"):
        EmbeddingVectorArtifact(vector=(float("nan"), 0.0, 0.0, 0.0))
    with pytest.raises(ValueError, match="non-zero"):
        EmbeddingVectorArtifact(vector=(0.0, 0.0, 0.0, 0.0))
    with pytest.raises(ValueError, match="dimension"):
        cache.store_embedding(
            key,
            EmbeddingVectorArtifact(vector=(1.0, 0.0, 0.0)),
        )


def test_equal_python_vectors_with_different_canonical_bytes_conflict(
    tmp_path: Path,
) -> None:
    cache = PersistentComputationCache(tmp_path / "private-cache")
    embedding = EmbeddingFingerprint(
        component=ComponentFingerprint(
            name="fixture-embedder",
            semantic_version="1",
            implementation_sha256="b" * 64,
        ),
        backend="deterministic-test",
        model_identifier="fixture-4d",
        model_sha256="c" * 64,
        dimension=4,
        normalization="none",
    )
    key = EmbeddingArtifactKey(
        tenant_id="tenant-a",
        source_system="sharepoint",
        source_key="policy/leave",
        document_id="doc-leave",
        chunk_text_sha256="d" * 64,
        content_pipeline_sha256="e" * 64,
        embedding=embedding,
    )
    negative_zero = EmbeddingVectorArtifact(
        vector=(1.0, -0.0, 0.0, 0.0)
    )
    positive_zero = EmbeddingVectorArtifact(
        vector=(1.0, 0.0, 0.0, 0.0)
    )

    assert negative_zero == positive_zero
    cache.store_embedding(key, negative_zero)
    with pytest.raises(ComputationCacheError) as collision:
        cache.store_embedding(key, positive_zero)
    assert collision.value.code == "cache_key_collision"


def test_tampered_or_noncanonical_cache_entry_fails_without_payload_leak(
    tmp_path: Path,
) -> None:
    cache = PersistentComputationCache(tmp_path / "private-cache")
    key = _parsed_key()
    payload = ParsedContentArtifact.from_parse_result(_parsed_result())
    cache.store_parsed(key, payload)
    path = cache.entry_path(key)
    original = path.read_bytes()

    path.write_bytes(original.replace(b"Employees", b"Contractors", 1))
    with pytest.raises(ComputationCacheError) as tampered:
        cache.load_parsed(key)
    assert tampered.value.code == "cache_entry_invalid"
    assert "Employees" not in str(tampered.value)
    assert "Contractors" not in str(tampered.value)

    path.write_bytes(
        (json.dumps(json.loads(original), indent=2, sort_keys=True) + "\n").encode(
            "ascii"
        )
    )
    with pytest.raises(ComputationCacheError) as noncanonical:
        cache.load_parsed(key)
    assert noncanonical.value.code == "cache_entry_noncanonical"


def test_cache_entry_at_another_keys_path_fails_manifest_binding(
    tmp_path: Path,
) -> None:
    cache = PersistentComputationCache(tmp_path / "private-cache")
    key = _parsed_key()
    other_key = _parsed_key(tenant_id="tenant-b")
    payload = ParsedContentArtifact.from_parse_result(_parsed_result())
    cache.store_parsed(key, payload)
    cache.entry_path(other_key).write_bytes(cache.entry_path(key).read_bytes())

    with pytest.raises(ComputationCacheError) as mismatch:
        cache.load_parsed(other_key)
    assert mismatch.value.code == "cache_key_mismatch"


def test_linked_and_oversized_cache_state_fails_closed(tmp_path: Path) -> None:
    cache = PersistentComputationCache(tmp_path / "private-cache")
    key = _parsed_key()
    payload = ParsedContentArtifact.from_parse_result(_parsed_result())
    cache.store_parsed(key, payload)
    linked = cache.root / "linked-entry.json"
    os.link(cache.entry_path(key), linked)

    with pytest.raises(ComputationCacheError) as unsafe:
        cache.load_parsed(key)
    assert unsafe.value.code == "cache_root_unsafe"

    linked.unlink()
    small = PersistentComputationCache(
        tmp_path / "small-cache",
        max_entry_bytes=128,
    )
    with pytest.raises(ComputationCacheError) as oversized:
        small.store_parsed(key, payload)
    assert oversized.value.code == "cache_entry_too_large"


def test_concurrent_same_key_writers_converge_to_one_canonical_entry(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "concurrent-cache").absolute()
    start_at = time.time() + 1.0
    with ProcessPoolExecutor(
        max_workers=4,
        mp_context=get_context("spawn"),
    ) as executor:
        statuses = list(
            executor.map(
                _store_parsed_in_process,
                [str(root)] * 4,
                [start_at] * 4,
            )
        )

    assert statuses.count("STORED") == 1
    assert statuses.count("REUSED") == 3
    cache = PersistentComputationCache(root)
    assert cache.load_parsed(_parsed_key()) == (
        ParsedContentArtifact.from_parse_result(_parsed_result())
    )
    assert sorted(path.name for path in root.iterdir()) == [
        ".cache.lock",
        cache.entry_path(_parsed_key()).name,
    ]


def test_lock_byte_is_initialized_only_after_exclusive_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = (tmp_path / "ordered-lock-cache").absolute()
    cache = PersistentComputationCache(root)
    original_lock_descriptor = cache_module._lock_descriptor
    observed_sizes: list[int] = []

    def checked_lock_descriptor(
        descriptor: int,
        *,
        timeout_seconds: float,
    ) -> None:
        observed_sizes.append(os.fstat(descriptor).st_size)
        original_lock_descriptor(
            descriptor,
            timeout_seconds=timeout_seconds,
        )

    monkeypatch.setattr(
        cache_module,
        "_lock_descriptor",
        checked_lock_descriptor,
    )

    with cache._locked():
        assert (root / ".cache.lock").stat().st_size == 1

    assert observed_sizes == [0]


def test_cache_revalidates_copied_request_models_before_filesystem_access(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private-cache"
    cache = PersistentComputationCache(root)
    tampered = _parsed_key().model_copy(update={"tenant_id": ""})

    with pytest.raises(ComputationCacheError) as invalid:
        cache.load_parsed(tampered)
    assert invalid.value.code == "cache_request_invalid"
    assert not root.exists()


def test_owned_orphan_is_cleaned_and_post_replace_uncertainty_is_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "private-cache"
    root.mkdir()
    orphan = root / ".cache.tmp-0123456789abcdef"
    orphan.write_bytes(b"incomplete")
    cache = PersistentComputationCache(root)
    key = _parsed_key()
    payload = ParsedContentArtifact.from_parse_result(_parsed_result())
    original_harden = cache_module.harden_private_directory

    def fail_after_replace(path: Path) -> None:
        if cache.entry_path(key).exists():
            raise OSError("injected post-replace failure")
        original_harden(path)

    monkeypatch.setattr(cache_module, "harden_private_directory", fail_after_replace)
    with pytest.raises(ComputationCacheError) as uncertain:
        cache.store_parsed(key, payload)
    assert uncertain.value.code == "cache_commit_outcome_unknown"
    assert not orphan.exists()
    assert cache.entry_path(key).is_file()

    monkeypatch.setattr(cache_module, "harden_private_directory", original_harden)
    assert cache.store_parsed(key, payload).status == "REUSED"
