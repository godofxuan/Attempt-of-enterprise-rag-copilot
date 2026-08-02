from __future__ import annotations

import time

from app.external_datasets.finqa_descriptor_retriever_v1 import (
    DescriptorRankV1,
    DeterministicDescriptorRetrieverResultV1,
    RoleDescriptorRankingV1,
)
from app.external_datasets.finqa_descriptor_retriever_v2 import (
    DeterministicFinQADescriptorRetrieverV2,
    _financial_tokens,
)
from app.external_datasets.finqa_descriptor_selector_v1 import (
    DescriptorSelectionsV1,
    RoleDescriptorSelectionV1,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v1 import (
    SafeDescriptorCatalogV1,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
    SemanticRoleRefV2,
)


RETRIEVER_VERSION = "finqa_structured_descriptor_retriever_v4"
MAX_DESCRIPTOR_REFS_PER_ROLE = 4
STRUCTURAL_BONUS = 120.0
_BALANCE_TOKENS = frozenset(
    {"balance", "begin", "beginning", "end", "ending"}
)


def _operation_by_role(
    skeleton: SemanticProgramSkeletonV2,
) -> dict[str, str]:
    result = {}
    for step in skeleton.steps:
        for argument in step.arguments:
            if isinstance(argument, SemanticRoleRefV2):
                result.setdefault(argument.role_id, step.operation)
    return result


class StructuredFinQADescriptorRetrieverV4:
    model = "deterministic-typed-structural-retriever-v4"

    def select(
        self,
        *,
        question: str,
        skeleton: SemanticProgramSkeletonV2,
        catalog: SafeDescriptorCatalogV1,
    ) -> DeterministicDescriptorRetrieverResultV1:
        started = time.perf_counter()
        lexical = DeterministicFinQADescriptorRetrieverV2().select(
            question=question,
            skeleton=skeleton,
            catalog=catalog,
        )
        descriptors = {
            item.descriptor_id: item for item in catalog.descriptors
        }
        operation_by_role = _operation_by_role(skeleton)
        role_count = len(skeleton.roles)
        rankings = []
        selections = []
        for base_ranking in lexical.rankings:
            operation = operation_by_role[base_ranking.role_id]
            rescored = []
            for rank in base_ranking.ranked_descriptors:
                descriptor = descriptors[rank.descriptor_id]
                text_tokens = _financial_tokens(
                    " ".join(
                        value
                        for value in (
                            descriptor.metric,
                            descriptor.entity,
                            descriptor.row_header,
                            descriptor.column_header,
                        )
                        if value
                    )
                )
                score = rank.score
                reasons = list(rank.score_reasons)
                if (
                    operation == "PERCENT_CHANGE"
                    and text_tokens & _BALANCE_TOKENS
                ):
                    score += STRUCTURAL_BONUS
                    reasons.append("percent_change_balance_prior")
                if (
                    operation in {"ADD", "AVERAGE"}
                    and role_count >= 3
                    and descriptor.candidate_count >= role_count
                ):
                    score += STRUCTURAL_BONUS
                    reasons.append("multi_operand_cardinality_prior")
                rescored.append(
                    DescriptorRankV1(
                        descriptor_id=rank.descriptor_id,
                        score=score,
                        score_reasons=tuple(reasons),
                    )
                )
            rescored.sort(key=lambda item: (-item.score, item.descriptor_id))
            ranked = tuple(rescored)
            rankings.append(
                RoleDescriptorRankingV1(
                    role_id=base_ranking.role_id,
                    ranked_descriptors=ranked,
                )
            )
            selections.append(
                RoleDescriptorSelectionV1(
                    role_id=base_ranking.role_id,
                    descriptor_ids=tuple(
                        item.descriptor_id
                        for item in ranked[:MAX_DESCRIPTOR_REFS_PER_ROLE]
                    ),
                )
            )
        return DeterministicDescriptorRetrieverResultV1(
            retriever_version=RETRIEVER_VERSION,
            model=self.model,
            selections=DescriptorSelectionsV1(selections=tuple(selections)),
            rankings=tuple(rankings),
            generation_calls=0,
            latency_ms=(time.perf_counter() - started) * 1_000,
        )


__all__ = [
    "RETRIEVER_VERSION",
    "STRUCTURAL_BONUS",
    "StructuredFinQADescriptorRetrieverV4",
]
