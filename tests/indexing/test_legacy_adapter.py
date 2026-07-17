from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import faiss
import numpy as np
import pytest
from rank_bm25 import BM25Okapi

import app.retriever as retriever
from app.config import BASE_DIR, Settings
from app.corpus.artifacts import write_corpus
from app.corpus.generator import load_facts, load_profile
from app.indexing.store import build_index_version
from app.ingestion.chunking import ChunkerConfig


ROOT = Path(__file__).resolve().parents[2]
FACTS = ROOT / "data" / "v2" / "facts" / "company_facts_v1.json"
PROFILE = ROOT / "data" / "v2" / "config" / "demo.json"


def fake_embedding(text: str) -> list[float]:
    total = sum(ord(character) for character in text)
    return [float((total % 17) + 1), float((len(text) % 11) + 1)]


def test_v2_config_is_separate_from_legacy_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.indexes_dir == BASE_DIR / "data" / "indexes"
    assert settings.v2_indexes_dir == BASE_DIR / "data" / "indexes_v2"
    assert settings.v2_indexes_dir != settings.indexes_dir
    assert settings.v2_corpus_profile == "demo"
    assert settings.v2_chunker_mode == "fixed"


def test_load_v2_indexes_reads_validated_active_version(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    root = tmp_path / "indexes-v2"
    write_corpus(corpus, load_facts(FACTS), load_profile(PROFILE))
    manifest = build_index_version(
        root=root,
        input_dir=corpus,
        run_id="run-one",
        chunker_config=ChunkerConfig(mode="fixed", chunk_size=500, overlap=80),
        embedding_model="fake-2d",
        embed_text=fake_embedding,
        activate=True,
    )

    faiss_index, bm25, chunks = retriever.load_v2_indexes(root)

    assert faiss_index.ntotal == manifest.indexed_chunk_count == len(chunks) == 64
    assert faiss_index.d == manifest.embedding.dimension == 2
    assert len(bm25.get_scores(["政策"])) == 64
    assert chunks[0]["tenant_id"]
    assert chunks[0]["acl_groups"]


def test_hybrid_search_keeps_using_legacy_loader_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = faiss.IndexFlatIP(2)
    index.add(np.asarray([[1.0, 0.0]], dtype="float32"))
    bm25 = BM25Okapi([["legacy", "policy"]])
    chunks = [
        {
            "source": "legacy.md",
            "section": "Policy",
            "chunk_id": "legacy::0",
            "text": "legacy policy",
        }
    ]
    calls: list[str] = []

    def load_legacy():
        calls.append("legacy")
        return index, bm25, chunks

    def fail_v2(*args, **kwargs):
        raise AssertionError("hybrid_search must not switch to v2 during E2")

    monkeypatch.setattr(retriever, "load_indexes", load_legacy)
    monkeypatch.setattr(retriever, "load_v2_indexes", fail_v2)
    monkeypatch.setattr(retriever, "_embed_text", lambda model, text: [1.0, 0.0])
    monkeypatch.setattr(
        retriever,
        "get_settings",
        lambda: SimpleNamespace(
            embedding_model="fake-2d",
            retrieval_top_k=1,
            retrieval_candidate_k=1,
        ),
    )

    results = retriever.hybrid_search("legacy policy", top_k=1)

    assert calls == ["legacy"]
    assert results[0]["source"] == "legacy.md"
