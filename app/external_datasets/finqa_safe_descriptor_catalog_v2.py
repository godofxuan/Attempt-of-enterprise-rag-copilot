from __future__ import annotations

from collections.abc import Mapping

from app.external_datasets.finqa_numeric_evidence_v2 import NumericCandidateV2
from app.external_datasets.finqa_safe_descriptor_catalog_v1 import (
    MAX_SOURCE_CANDIDATES,
    SafeDescriptorCatalogBuildV1,
    _safe_field,
    build_safe_descriptor_catalog_v1,
)
from app.security.retrieved_content import RetrievedContentGuard


CONTEXT_WINDOW_CHARS = 240


def _safe_context_window(
    *,
    context: str,
    raw_text: str,
) -> str | None:
    position = context.casefold().find(raw_text.casefold())
    if position < 0:
        window = context[:CONTEXT_WINDOW_CHARS]
    else:
        radius = CONTEXT_WINDOW_CHARS // 2
        start = max(0, position - radius)
        end = min(len(context), position + len(raw_text) + radius)
        window = context[start:end]
    return _safe_field(window)


def build_contextual_safe_descriptor_catalog_v2(
    *,
    candidates: tuple[NumericCandidateV2, ...],
    admitted_evidence_ids: set[str],
    evidence_context_by_id: Mapping[str, str],
    guard: RetrievedContentGuard,
) -> SafeDescriptorCatalogBuildV1:
    if not candidates or len(candidates) > MAX_SOURCE_CANDIDATES:
        raise ValueError("contextual descriptor source budget is invalid")
    if set(evidence_context_by_id) - admitted_evidence_ids:
        raise ValueError("contextual descriptor text is not admitted")

    enriched = []
    for candidate in candidates:
        if any(
            value
            for value in (
                _safe_field(candidate.metric),
                _safe_field(candidate.entity),
                _safe_field(candidate.row_header),
                _safe_field(candidate.column_header),
            )
        ):
            enriched.append(candidate)
            continue
        context = evidence_context_by_id.get(candidate.evidence_id)
        if context is None or guard.scan(context).disposition != "ADMIT":
            enriched.append(candidate)
            continue
        fallback_metric = _safe_context_window(
            context=context,
            raw_text=candidate.raw_text,
        )
        if (
            fallback_metric is None
            or guard.scan(fallback_metric).disposition != "ADMIT"
        ):
            enriched.append(candidate)
            continue
        enriched.append(
            candidate.model_copy(update={"metric": fallback_metric})
        )
    return build_safe_descriptor_catalog_v1(
        candidates=tuple(enriched),
        admitted_evidence_ids=admitted_evidence_ids,
        guard=guard,
    )


__all__ = [
    "CONTEXT_WINDOW_CHARS",
    "build_contextual_safe_descriptor_catalog_v2",
]
