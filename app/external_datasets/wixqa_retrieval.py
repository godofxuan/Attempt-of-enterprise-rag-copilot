from __future__ import annotations

import hashlib
import json
import math
import os
import pickle
import shutil
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

import faiss
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from rank_bm25 import BM25Okapi

from app.domain.enterprise_documents import EnterpriseDocument
from app.external_datasets.wixqa import WixQAQuestion, canonical_json_bytes
from app.utils import tokenize_for_bm25

WixQARetrievalArm = Literal["bm25", "dense", "hybrid_rrf", "dense_cross_encoder"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class WixQAFlatChunk(_StrictModel):
    chunk_id: str = Field(min_length=1)
    article_id: str = Field(min_length=1)
    ordinal: int = Field(ge=1)
    text: str = Field(min_length=1)
    text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class WixQAArticleCandidate(_StrictModel):
    article_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    dense_score: float


class WixQAIndexArtifact(_StrictModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(ge=1)


class WixQAFlatIndexManifest(_StrictModel):
    schema_version: Literal["wixqa_flat_index_v1"] = "wixqa_flat_index_v1"
    producer: Literal["enterprise_agentic_rag_v2"] = "enterprise_agentic_rag_v2"
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    dataset_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ordered_articles_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    article_count: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    chunk_size: int = Field(ge=1)
    overlap: int = Field(ge=0)
    embedding_model: str = Field(min_length=1)
    embedding_model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_dimension: int = Field(ge=1)
    embedding_cache_build_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    bm25_tokenizer: Literal["jieba"] = "jieba"
    rrf_k: int = Field(default=60, ge=1)
    build_duration_ms: float = Field(ge=0)
    artifacts: list[WixQAIndexArtifact] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_artifacts(self) -> WixQAFlatIndexManifest:
        if {item.path for item in self.artifacts} != {
            "chunks.jsonl",
            "bm25_tokens.pkl",
            "faiss.index",
        }:
            raise ValueError("WixQA index artifact set is invalid")
        if self.overlap >= self.chunk_size:
            raise ValueError("WixQA overlap must be smaller than chunk size")
        return self


class WixQACaseScore(_StrictModel):
    question_id: str = Field(min_length=1)
    arm: WixQARetrievalArm
    gold_article_count: int = Field(ge=1)
    ranked_article_ids: list[str] = Field(max_length=5)
    hit_at_1: float = Field(ge=0, le=1)
    recall_at_1: float = Field(ge=0, le=1)
    recall_at_3: float = Field(ge=0, le=1)
    recall_at_5: float = Field(ge=0, le=1)
    reciprocal_rank_at_5: float = Field(ge=0, le=1)
    ndcg_at_5: float = Field(ge=0, le=1)
    complete_at_5: float | None = Field(default=None, ge=0, le=1)
    latency_ms: float = Field(ge=0)


class WixQARetrievalSummary(_StrictModel):
    schema_version: Literal["wixqa_retrieval_summary_v1"] = "wixqa_retrieval_summary_v1"
    cohort: Literal["synthetic", "simulated", "expertwritten"]
    arm: WixQARetrievalArm
    case_count: int = Field(ge=1)
    multi_article_case_count: int = Field(ge=0)
    article_hit_at_1: float = Field(ge=0, le=1)
    article_recall_at_1: float = Field(ge=0, le=1)
    article_recall_at_3: float = Field(ge=0, le=1)
    article_recall_at_5: float = Field(ge=0, le=1)
    mrr_at_5: float = Field(ge=0, le=1)
    ndcg_at_5: float = Field(ge=0, le=1)
    multi_article_completeness_at_5: float | None = Field(default=None, ge=0, le=1)
    latency_ms_mean: float = Field(ge=0)
    latency_ms_p50: float = Field(ge=0)
    latency_ms_p95: float = Field(ge=0)


class LoadedWixQAFlatIndex:
    def __init__(
        self,
        *,
        manifest: WixQAFlatIndexManifest,
        chunks: list[WixQAFlatChunk],
        bm25_tokens: list[list[str]],
        faiss_index,
    ) -> None:
        self.manifest = manifest
        self.chunks = chunks
        self.bm25 = BM25Okapi(bm25_tokens)
        self.faiss_index = faiss_index

    def bm25_article_ranking(self, query: str, *, candidate_k: int) -> list[str]:
        scores = np.asarray(self.bm25.get_scores(tokenize_for_bm25(query)))
        indices = sorted(
            range(len(self.chunks)),
            key=lambda index: (-float(scores[index]), self.chunks[index].chunk_id),
        )[:candidate_k]
        return _unique_articles(indices, self.chunks)

    def dense_article_ranking(
        self,
        query_vector: np.ndarray,
        *,
        candidate_k: int,
    ) -> list[str]:
        return [
            item.article_id
            for item in self.dense_article_candidates(
                query_vector,
                candidate_k=candidate_k,
            )
        ]

    def dense_article_candidates(
        self,
        query_vector: np.ndarray,
        *,
        candidate_k: int,
    ) -> list[WixQAArticleCandidate]:
        return self.dense_article_chunk_candidates(
            query_vector,
            candidate_k=candidate_k,
            max_articles=candidate_k,
            chunks_per_article=1,
        )

    def dense_article_chunk_candidates(
        self,
        query_vector: np.ndarray,
        *,
        candidate_k: int,
        max_articles: int,
        chunks_per_article: int,
    ) -> list[WixQAArticleCandidate]:
        if candidate_k < 1 or max_articles < 1:
            raise ValueError("WixQA candidate limits must be positive")
        if not 1 <= chunks_per_article <= 2:
            raise ValueError("WixQA chunks per article must be one or two")
        vector = _normalize_matrix(np.asarray(query_vector, dtype="float32"))
        if vector.shape != (1, self.manifest.embedding_dimension):
            raise ValueError("WixQA query embedding dimension mismatch")
        scores, indices = self.faiss_index.search(vector, candidate_k)
        selected_articles: list[str] = []
        by_article: dict[str, list[WixQAArticleCandidate]] = {}
        for raw_score, raw_index in zip(scores[0], indices[0], strict=True):
            index = int(raw_index)
            if index < 0:
                continue
            chunk = self.chunks[index]
            if chunk.article_id not in by_article:
                if len(selected_articles) >= max_articles:
                    continue
                selected_articles.append(chunk.article_id)
                by_article[chunk.article_id] = []
            article_candidates = by_article[chunk.article_id]
            if len(article_candidates) >= chunks_per_article:
                continue
            article_candidates.append(
                WixQAArticleCandidate(
                    article_id=chunk.article_id,
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    dense_score=float(raw_score),
                )
            )
        return [item for article_id in selected_articles for item in by_article[article_id]]


def build_flat_chunks(
    articles: Sequence[EnterpriseDocument],
    *,
    chunk_size: int = 1800,
    overlap: int = 150,
) -> list[WixQAFlatChunk]:
    if chunk_size < 1 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("invalid WixQA flat chunk configuration")
    chunks: list[WixQAFlatChunk] = []
    seen_articles: set[str] = set()
    for article in articles:
        article_id = article.source_native_id
        if article_id in seen_articles:
            raise ValueError(f"duplicate WixQA article ID: {article_id}")
        seen_articles.add(article_id)
        body = article.text.strip()
        start = 0
        ordinal = 0
        while start < len(body):
            end = min(start + chunk_size, len(body))
            piece = body[start:end].strip()
            if piece:
                ordinal += 1
                text = f"{article.title}\n{piece}"
                text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                chunks.append(
                    WixQAFlatChunk(
                        chunk_id=f"wixqa:{article_id}:flat:{ordinal:04d}:{text_hash[:12]}",
                        article_id=article_id,
                        ordinal=ordinal,
                        text=text,
                        text_hash=text_hash,
                    )
                )
            if end == len(body):
                break
            start = end - overlap
    if not chunks:
        raise ValueError("WixQA flat chunker produced no chunks")
    return chunks


def ordered_articles_sha256(articles: Sequence[EnterpriseDocument]) -> str:
    payload = [
        {
            "article_id": item.source_native_id,
            "raw_record_sha256": item.raw_provenance.raw_record_sha256,
        }
        for item in articles
    ]
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def build_wixqa_flat_index(
    *,
    output_root: Path,
    run_id: str,
    articles: Sequence[EnterpriseDocument],
    dataset_manifest_sha256: str,
    embedding_model: str,
    embedding_model_sha256: str,
    embed_chunks: Callable[[list[WixQAFlatChunk]], np.ndarray],
    embedding_cache_build_id: Callable[[], str],
    chunk_size: int = 1800,
    overlap: int = 150,
    rrf_k: int = 60,
) -> WixQAFlatIndexManifest:
    root = Path(output_root).resolve()
    target = root / "versions" / run_id
    if target.exists():
        raise FileExistsError(f"WixQA index version already exists: {run_id}")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{run_id}.staging-", dir=target.parent))
    started = time.perf_counter()
    try:
        chunks = build_flat_chunks(articles, chunk_size=chunk_size, overlap=overlap)
        matrix = _normalize_matrix(np.asarray(embed_chunks(chunks), dtype="float32"))
        if matrix.shape[0] != len(chunks):
            raise ValueError("WixQA embedding row count mismatch")
        index = faiss.IndexFlatIP(matrix.shape[1])
        index.add(matrix)
        chunk_bytes = b"".join(
            canonical_json_bytes(item.model_dump(mode="json")) for item in chunks
        )
        token_bytes = pickle.dumps(
            [tokenize_for_bm25(item.text) for item in chunks],
            protocol=pickle.HIGHEST_PROTOCOL,
        )
        faiss_bytes = faiss.serialize_index(index).tobytes()
        artifacts = {
            "chunks.jsonl": chunk_bytes,
            "bm25_tokens.pkl": token_bytes,
            "faiss.index": faiss_bytes,
        }
        for name, content in artifacts.items():
            (stage / name).write_bytes(content)
        manifest = WixQAFlatIndexManifest(
            run_id=run_id,
            dataset_manifest_sha256=dataset_manifest_sha256,
            ordered_articles_sha256=ordered_articles_sha256(articles),
            article_count=len(articles),
            chunk_count=len(chunks),
            chunk_size=chunk_size,
            overlap=overlap,
            embedding_model=embedding_model,
            embedding_model_sha256=embedding_model_sha256,
            embedding_dimension=int(matrix.shape[1]),
            embedding_cache_build_id=embedding_cache_build_id(),
            rrf_k=rrf_k,
            build_duration_ms=(time.perf_counter() - started) * 1000,
            artifacts=[
                WixQAIndexArtifact(
                    path=name,
                    sha256=hashlib.sha256(content).hexdigest(),
                    byte_count=len(content),
                )
                for name, content in sorted(artifacts.items())
            ],
        )
        (stage / "manifest.json").write_bytes(
            canonical_json_bytes(manifest.model_dump(mode="json"))
        )
        verify_wixqa_flat_index(stage)
        os.replace(stage, target)
        active = root / "active.json"
        active.parent.mkdir(parents=True, exist_ok=True)
        active_stage = active.with_suffix(".tmp")
        active_stage.write_bytes(
            canonical_json_bytes(
                {
                    "run_id": run_id,
                    "manifest_sha256": hashlib.sha256(
                        (target / "manifest.json").read_bytes()
                    ).hexdigest(),
                }
            )
        )
        os.replace(active_stage, active)
        return manifest
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def verify_wixqa_flat_index(path: Path) -> WixQAFlatIndexManifest:
    root = Path(path).resolve()
    manifest = WixQAFlatIndexManifest.model_validate_json((root / "manifest.json").read_bytes())
    for artifact in manifest.artifacts:
        content = (root / artifact.path).read_bytes()
        if len(content) != artifact.byte_count:
            raise ValueError(f"WixQA index byte count mismatch: {artifact.path}")
        if hashlib.sha256(content).hexdigest() != artifact.sha256:
            raise ValueError(f"WixQA index hash mismatch: {artifact.path}")
    chunks = _load_chunks(root / "chunks.jsonl")
    if len(chunks) != manifest.chunk_count:
        raise ValueError("WixQA index chunk count mismatch")
    with (root / "bm25_tokens.pkl").open("rb") as handle:
        tokens = pickle.load(handle)
    if len(tokens) != manifest.chunk_count:
        raise ValueError("WixQA BM25 row count mismatch")
    index = faiss.deserialize_index(
        np.frombuffer((root / "faiss.index").read_bytes(), dtype=np.uint8).copy()
    )
    if index.ntotal != manifest.chunk_count or index.d != manifest.embedding_dimension:
        raise ValueError("WixQA FAISS shape mismatch")
    return manifest


def load_wixqa_flat_index(output_root: Path) -> LoadedWixQAFlatIndex:
    root = Path(output_root).resolve()
    active = json.loads((root / "active.json").read_text(encoding="utf-8"))
    version = root / "versions" / active["run_id"]
    manifest_bytes = (version / "manifest.json").read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != active["manifest_sha256"]:
        raise ValueError("WixQA active index manifest hash mismatch")
    manifest = verify_wixqa_flat_index(version)
    chunks = _load_chunks(version / "chunks.jsonl")
    with (version / "bm25_tokens.pkl").open("rb") as handle:
        tokens = pickle.load(handle)
    index = faiss.deserialize_index(
        np.frombuffer((version / "faiss.index").read_bytes(), dtype=np.uint8).copy()
    )
    return LoadedWixQAFlatIndex(
        manifest=manifest,
        chunks=chunks,
        bm25_tokens=tokens,
        faiss_index=index,
    )


def reciprocal_rank_fusion(
    bm25_articles: Sequence[str],
    dense_articles: Sequence[str],
    *,
    rrf_k: int = 60,
) -> list[str]:
    scores: dict[str, float] = {}
    ranks: dict[str, tuple[int, int]] = {}
    for source_index, ranking in enumerate((bm25_articles, dense_articles)):
        for rank, article_id in enumerate(ranking, start=1):
            scores[article_id] = scores.get(article_id, 0.0) + 1.0 / (rrf_k + rank)
            previous = ranks.get(article_id, (10**9, 10**9))
            value = list(previous)
            value[source_index] = rank
            ranks[article_id] = (value[0], value[1])
    return sorted(
        scores,
        key=lambda item: (-scores[item], min(ranks[item]), ranks[item], item),
    )


def merge_reranked_article_ids(
    *,
    dense_article_ids: Sequence[str],
    reranked_article_ids: Sequence[str],
    reranker_top_n: int,
    dense_head_count: int,
) -> list[str]:
    dense = list(dense_article_ids)
    reranked = list(reranked_article_ids)
    if len(dense) != len(set(dense)):
        raise ValueError("dense article IDs must be unique")
    if len(reranked) != len(set(reranked)):
        raise ValueError("reranked article IDs must be unique")
    if not 1 <= reranker_top_n <= len(dense):
        raise ValueError("reranker top-N must fit the dense candidate list")
    if not 0 <= dense_head_count <= reranker_top_n:
        raise ValueError("dense head count must be between zero and reranker top-N")

    window = dense[:reranker_top_n]
    unknown = set(reranked).difference(window)
    if unknown:
        raise ValueError("reranked article IDs contain unknown candidates")

    head = window[:dense_head_count]
    ordered = head + [item for item in reranked if item not in head]
    ordered.extend(item for item in window if item not in ordered)
    ordered.extend(dense[reranker_top_n:])
    return ordered


def score_wixqa_ranking(
    question: WixQAQuestion,
    *,
    arm: WixQARetrievalArm,
    ranked_article_ids: Sequence[str],
    latency_ms: float,
) -> WixQACaseScore:
    top = list(ranked_article_ids[:5])
    gold = set(question.article_ids)
    recalls = {cutoff: len(gold.intersection(top[:cutoff])) / len(gold) for cutoff in (1, 3, 5)}
    first = next((rank for rank, item in enumerate(top, start=1) if item in gold), None)
    dcg = sum((1.0 / math.log2(rank + 1)) for rank, item in enumerate(top, start=1) if item in gold)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(5, len(gold)) + 1))
    return WixQACaseScore(
        question_id=question.question_id,
        arm=arm,
        gold_article_count=len(gold),
        ranked_article_ids=top,
        hit_at_1=float(bool(top and top[0] in gold)),
        recall_at_1=recalls[1],
        recall_at_3=recalls[3],
        recall_at_5=recalls[5],
        reciprocal_rank_at_5=0.0 if first is None else 1.0 / first,
        ndcg_at_5=dcg / ideal,
        complete_at_5=(float(gold <= set(top)) if len(gold) > 1 else None),
        latency_ms=latency_ms,
    )


def summarize_wixqa_scores(
    scores: Sequence[WixQACaseScore],
    *,
    cohort: Literal["synthetic", "simulated", "expertwritten"],
    arm: WixQARetrievalArm,
) -> WixQARetrievalSummary:
    rows = [item for item in scores if item.arm == arm]
    if not rows:
        raise ValueError(f"WixQA summary has no {arm} rows")
    multi = [item.complete_at_5 for item in rows if item.complete_at_5 is not None]
    latencies = sorted(item.latency_ms for item in rows)

    def mean(name: str) -> float:
        return sum(float(getattr(item, name)) for item in rows) / len(rows)

    return WixQARetrievalSummary(
        cohort=cohort,
        arm=arm,
        case_count=len(rows),
        multi_article_case_count=len(multi),
        article_hit_at_1=mean("hit_at_1"),
        article_recall_at_1=mean("recall_at_1"),
        article_recall_at_3=mean("recall_at_3"),
        article_recall_at_5=mean("recall_at_5"),
        mrr_at_5=mean("reciprocal_rank_at_5"),
        ndcg_at_5=mean("ndcg_at_5"),
        multi_article_completeness_at_5=(sum(multi) / len(multi) if multi else None),
        latency_ms_mean=sum(latencies) / len(latencies),
        latency_ms_p50=latencies[max(0, math.ceil(0.50 * len(latencies)) - 1)],
        latency_ms_p95=latencies[max(0, math.ceil(0.95 * len(latencies)) - 1)],
    )


def _load_chunks(path: Path) -> list[WixQAFlatChunk]:
    with Path(path).open(encoding="utf-8") as handle:
        return [WixQAFlatChunk.model_validate_json(line) for line in handle if line.strip()]


def _unique_articles(indices: Sequence[int], chunks: Sequence[WixQAFlatChunk]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for index in indices:
        article_id = chunks[index].article_id
        if article_id not in seen:
            seen.add(article_id)
            result.append(article_id)
    return result


def _normalize_matrix(matrix: np.ndarray) -> np.ndarray:
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2 or not matrix.size or not np.isfinite(matrix).all():
        raise ValueError("WixQA embeddings must be a finite non-empty matrix")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("WixQA embeddings must not contain zero vectors")
    return np.asarray(matrix / norms, dtype="float32")


__all__ = [
    "LoadedWixQAFlatIndex",
    "WixQAArticleCandidate",
    "WixQACaseScore",
    "WixQAFlatChunk",
    "WixQAFlatIndexManifest",
    "WixQARetrievalSummary",
    "build_flat_chunks",
    "build_wixqa_flat_index",
    "load_wixqa_flat_index",
    "merge_reranked_article_ids",
    "reciprocal_rank_fusion",
    "score_wixqa_ranking",
    "summarize_wixqa_scores",
    "verify_wixqa_flat_index",
]
