from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from app.external_datasets.finqa_descriptor_retriever_v1 import (
    DescriptorRankV1,
    RoleDescriptorRankingV1,
)
from app.external_datasets.finqa_descriptor_retriever_v2 import (
    DeterministicFinQADescriptorRetrieverV2,
    _role_anchor_tokens_v2,
)
from app.external_datasets.finqa_descriptor_selector_v1 import (
    DescriptorSelectionsV1,
    RoleDescriptorSelectionV1,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v1 import (
    SafeCandidateDescriptorV1,
    SafeDescriptorCatalogV1,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)


RETRIEVER_VERSION = "finqa_hybrid_descriptor_retriever_v3"
MAX_DESCRIPTOR_REFS_PER_ROLE = 4
MAX_QUESTION_CHARS = 2_000
RRF_K = 60.0
DENSE_WEIGHT = 0.8
LEXICAL_WEIGHT = 0.2
EmbedBatch = Callable[[list[str]], np.ndarray]


@dataclass(frozen=True)
class HybridDescriptorRetrieverResultV3:
    retriever_version: str
    model: str
    model_sha256: str
    embedding_dimension: int
    selections: DescriptorSelectionsV1
    rankings: tuple[RoleDescriptorRankingV1, ...]
    embedding_request_count: int
    generation_calls: int
    latency_ms: float


def _descriptor_embedding_text(
    descriptor: SafeCandidateDescriptorV1,
) -> str:
    fields = [
        f"metric: {descriptor.metric}" if descriptor.metric else None,
        f"entity: {descriptor.entity}" if descriptor.entity else None,
        f"row: {descriptor.row_header}" if descriptor.row_header else None,
        f"column: {descriptor.column_header}"
        if descriptor.column_header
        else None,
        f"periods: {' '.join(descriptor.periods)}"
        if descriptor.periods
        else None,
        f"source: {descriptor.source_kind}",
    ]
    return "descriptor: " + "; ".join(item for item in fields if item)


def _role_embedding_query(*, question: str, role) -> str:
    anchors = sorted(_role_anchor_tokens_v2(question, role.semantic_role))
    focus = " ".join(anchors) if anchors else role.semantic_role.replace("_", " ")
    return (
        f"query: {question}; evidence role: {role.semantic_role}; "
        f"period role: {role.period_role}; focus: {focus}"
    )


def _normalized_rows(
    vectors: np.ndarray,
    *,
    expected_rows: int,
    expected_dimension: int,
) -> np.ndarray:
    array = np.asarray(vectors, dtype="float32")
    if array.shape != (expected_rows, expected_dimension):
        raise ValueError("hybrid descriptor embedding shape is invalid")
    if not np.isfinite(array).all():
        raise ValueError("hybrid descriptor embedding contains non-finite values")
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("hybrid descriptor embedding contains a zero vector")
    return array / norms


class HybridFinQADescriptorRetrieverV3:
    def __init__(
        self,
        *,
        embed_batch: EmbedBatch,
        model_identifier: str,
        model_sha256: str,
        embedding_dimension: int,
    ) -> None:
        if (
            not model_identifier.strip()
            or len(model_identifier) > 200
            or len(model_sha256) != 64
            or any(char not in "0123456789abcdef" for char in model_sha256)
            or not 1 <= embedding_dimension <= 65_536
        ):
            raise ValueError("hybrid descriptor model identity is invalid")
        self.embed_batch = embed_batch
        self.model = model_identifier.strip()
        self.model_sha256 = model_sha256
        self.embedding_dimension = embedding_dimension

    def select(
        self,
        *,
        question: str,
        skeleton: SemanticProgramSkeletonV2,
        catalog: SafeDescriptorCatalogV1,
    ) -> HybridDescriptorRetrieverResultV3:
        normalized_question = " ".join(question.split())
        if (
            not normalized_question
            or len(normalized_question) > MAX_QUESTION_CHARS
        ):
            raise ValueError("hybrid descriptor question is outside budget")
        started = time.perf_counter()
        descriptors = tuple(
            sorted(catalog.descriptors, key=lambda item: item.descriptor_id)
        )
        lexical = DeterministicFinQADescriptorRetrieverV2().select(
            question=normalized_question,
            skeleton=skeleton,
            catalog=catalog,
        )
        lexical_rank_by_role = {
            item.role_id: {
                rank.descriptor_id: index
                for index, rank in enumerate(
                    item.ranked_descriptors, start=1
                )
            }
            for item in lexical.rankings
        }
        queries = [
            _role_embedding_query(question=normalized_question, role=role)
            for role in skeleton.roles
        ]
        descriptor_texts = [
            _descriptor_embedding_text(item) for item in descriptors
        ]
        vectors = _normalized_rows(
            self.embed_batch([*queries, *descriptor_texts]),
            expected_rows=len(queries) + len(descriptors),
            expected_dimension=self.embedding_dimension,
        )
        query_vectors = vectors[: len(queries)]
        descriptor_vectors = vectors[len(queries) :]
        similarities = query_vectors @ descriptor_vectors.T
        if not np.isfinite(similarities).all():
            raise ValueError("hybrid descriptor similarity is invalid")

        rankings = []
        selections = []
        for role_index, role in enumerate(skeleton.roles):
            dense_order = sorted(
                range(len(descriptors)),
                key=lambda index: (
                    -float(similarities[role_index, index]),
                    descriptors[index].descriptor_id,
                ),
            )
            dense_rank = {
                descriptors[index].descriptor_id: rank
                for rank, index in enumerate(dense_order, start=1)
            }
            lexical_rank = lexical_rank_by_role[role.role_id]
            fused = []
            for descriptor in descriptors:
                score = (
                    DENSE_WEIGHT
                    / (RRF_K + dense_rank[descriptor.descriptor_id])
                    + LEXICAL_WEIGHT
                    / (RRF_K + lexical_rank[descriptor.descriptor_id])
                )
                if not math.isfinite(score):
                    raise ValueError("hybrid descriptor score is invalid")
                fused.append(
                    DescriptorRankV1(
                        descriptor_id=descriptor.descriptor_id,
                        score=score,
                        score_reasons=("dense_lexical_rrf",),
                    )
                )
            fused.sort(key=lambda item: (-item.score, item.descriptor_id))
            ranked = tuple(fused)
            rankings.append(
                RoleDescriptorRankingV1(
                    role_id=role.role_id,
                    ranked_descriptors=ranked,
                )
            )
            selections.append(
                RoleDescriptorSelectionV1(
                    role_id=role.role_id,
                    descriptor_ids=tuple(
                        item.descriptor_id
                        for item in ranked[:MAX_DESCRIPTOR_REFS_PER_ROLE]
                    ),
                )
            )
        return HybridDescriptorRetrieverResultV3(
            retriever_version=RETRIEVER_VERSION,
            model=self.model,
            model_sha256=self.model_sha256,
            embedding_dimension=self.embedding_dimension,
            selections=DescriptorSelectionsV1(selections=tuple(selections)),
            rankings=tuple(rankings),
            embedding_request_count=1,
            generation_calls=1,
            latency_ms=(time.perf_counter() - started) * 1_000,
        )


__all__ = [
    "DENSE_WEIGHT",
    "HybridDescriptorRetrieverResultV3",
    "HybridFinQADescriptorRetrieverV3",
    "LEXICAL_WEIGHT",
    "RETRIEVER_VERSION",
    "RRF_K",
]
