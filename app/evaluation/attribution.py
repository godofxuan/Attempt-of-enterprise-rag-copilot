from __future__ import annotations

from collections.abc import Sequence

from app.evaluation.contracts import FailureSignal, FailureStage


_STAGE_PRIORITY: tuple[FailureStage, ...] = (
    "system_runtime",
    "evaluation_label",
    "acl",
    "parse",
    "chunking",
    "metadata",
    "query_analysis",
    "decomposition_rewrite",
    "retrieval",
    "ranking",
    "dedup_diversity",
    "evidence_assessment",
    "conflict_resolution",
    "generation",
    "citation_verification",
)
_PRIORITY = {stage: index for index, stage in enumerate(_STAGE_PRIORITY)}


def attribute_failures(
    signals: Sequence[FailureSignal],
) -> tuple[FailureStage | None, list[FailureStage]]:
    stages = sorted(
        {signal.stage for signal in signals},
        key=lambda stage: _PRIORITY[stage],
    )
    if not stages:
        return None, []
    return stages[0], stages[1:]


__all__ = ["attribute_failures"]
