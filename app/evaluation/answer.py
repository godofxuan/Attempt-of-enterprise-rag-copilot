from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from app.corpus.schemas import EvalCase
from app.domain.evidence import AnswerResponse, ClaimCitation
from app.evaluation.contracts import FailureSignal, LayerResult
from app.evaluation.metrics import unique_ranked_doc_ids


@dataclass(frozen=True)
class AnswerEvaluation:
    layer: LayerResult
    cited_fact_ids: list[str]
    source_doc_ids: list[str]


def evaluate_answer_case(
    case: EvalCase,
    response: AnswerResponse,
    chunks_by_id: Mapping[str, Any],
) -> AnswerEvaluation:
    source_doc_ids = unique_ranked_doc_ids(
        source.doc_id for source in response.sources
    )
    source_chunk_ids = {source.chunk_id for source in response.sources}
    citations = {citation.claim_id: citation for citation in response.citations}
    cited_fact_ids: set[str] = set()
    correct_claim_citations = 0
    present_claim_citations = 0
    unsupported_claims = 0
    unsupported_critical = 0

    for claim in response.claims:
        citation = citations.get(claim.claim_id)
        present = citation is not None and citation.citation_present
        present_claim_citations += int(present)
        correct = _citation_is_correct(citation, source_chunk_ids)
        correct_claim_citations += int(correct)
        if not correct:
            unsupported_claims += 1
            unsupported_critical += int(claim.critical)
            continue
        for chunk_id in citation.cited_chunk_ids:
            chunk = chunks_by_id.get(chunk_id)
            if chunk is None:
                continue
            fact_ids = (
                chunk.get("fact_ids", [])
                if isinstance(chunk, dict)
                else getattr(chunk, "fact_ids", [])
            )
            cited_fact_ids.update(str(fact_id) for fact_id in fact_ids)

    required_facts = set(case.required_fact_ids)
    fact_coverage = (
        None
        if not required_facts
        else len(required_facts.intersection(cited_fact_ids)) / len(required_facts)
    )
    claim_count = len(response.claims)
    citation_coverage = (
        None if claim_count == 0 else present_claim_citations / claim_count
    )
    citation_correctness = (
        None if claim_count == 0 else correct_claim_citations / claim_count
    )
    unsupported_claim_rate = (
        None if claim_count == 0 else unsupported_claims / claim_count
    )
    expected_answer_signal = _expected_answer_signal(
        response.answer,
        [claim.text for claim in response.claims],
        case.expected_answer,
    )
    expected_gold = set(case.gold_doc_ids)
    gold_source_coverage = (
        None
        if not expected_gold
        else len(expected_gold.intersection(source_doc_ids)) / len(expected_gold)
    )
    conflict_accuracy = _conflict_accuracy(case, source_doc_ids)
    mode_correct = response.mode == case.answer_mode
    source_free = not response.sources and not response.claims and not response.citations
    refusal_accuracy = (
        mode_correct and source_free
        if case.answer_mode in {"permission", "not_found", "unsafe"}
        else None
    )
    partial_quality = fact_coverage if response.mode == "partial" else None

    if case.answer_mode == "answered":
        correctness = bool(
            mode_correct
            and fact_coverage == 1.0
            and gold_source_coverage == 1.0
            and unsupported_critical == 0
            and conflict_accuracy is not False
        )
    else:
        correctness = bool(mode_correct and source_free)

    failures = _answer_failures(
        case,
        response,
        mode_correct=mode_correct,
        fact_coverage=fact_coverage,
        gold_source_coverage=gold_source_coverage,
        unsupported_critical=unsupported_critical,
        conflict_accuracy=conflict_accuracy,
        source_free=source_free,
    )
    metrics = {
        "mode_correct": mode_correct,
        "correctness": correctness,
        "atomic_fact_completeness": fact_coverage,
        "expected_answer_signal": expected_answer_signal,
        "gold_source_coverage": gold_source_coverage,
        "citation_coverage": citation_coverage,
        "citation_correctness": citation_correctness,
        "unsupported_claim_rate": unsupported_claim_rate,
        "conflict_resolution_accuracy": conflict_accuracy,
        "refusal_accuracy": refusal_accuracy,
        "partial_answer_quality": partial_quality,
        "claim_count": claim_count,
        "source_count": len(response.sources),
    }
    return AnswerEvaluation(
        layer=LayerResult(
            layer="answer",
            applicable=True,
            passed=not failures,
            metrics=metrics,
            failures=failures,
        ),
        cited_fact_ids=sorted(cited_fact_ids),
        source_doc_ids=source_doc_ids,
    )


def _citation_is_correct(
    citation: ClaimCitation | None,
    source_chunk_ids: set[str],
) -> bool:
    return bool(
        citation is not None
        and citation.citation_present
        and citation.references_visible_evidence
        and citation.supported
        and set(citation.cited_chunk_ids).issubset(source_chunk_ids)
    )


def _conflict_accuracy(
    case: EvalCase,
    source_doc_ids: list[str],
) -> bool | None:
    if case.task_type != "version_conflict":
        return None
    sources = set(source_doc_ids)
    return set(case.expected_authority_doc_ids).issubset(sources) and not set(
        case.distractor_doc_ids
    ).intersection(sources)


def _answer_failures(
    case: EvalCase,
    response: AnswerResponse,
    *,
    mode_correct: bool,
    fact_coverage: float | None,
    gold_source_coverage: float | None,
    unsupported_critical: int,
    conflict_accuracy: bool | None,
    source_free: bool,
) -> list[FailureSignal]:
    failures: list[FailureSignal] = []
    if response.mode == "system":
        failures.append(
            FailureSignal(
                stage="system_runtime",
                code="answer_system_error",
                message="The answer runtime returned a system outcome.",
            )
        )
    if not mode_correct:
        failures.append(
            FailureSignal(
                stage="evidence_assessment",
                code="answer_mode_mismatch",
                message="The predicted answer mode did not match the evaluation label.",
            )
        )
    if case.answer_mode == "answered" and fact_coverage != 1.0:
        failures.append(
            FailureSignal(
                stage="generation",
                code="required_fact_omission",
                message="One or more required facts were not supported by cited chunks.",
            )
        )
    if case.answer_mode == "answered" and gold_source_coverage != 1.0:
        failures.append(
            FailureSignal(
                stage="citation_verification",
                code="gold_source_not_cited",
                message="The cited source set did not cover all gold documents.",
            )
        )
    if unsupported_critical:
        failures.append(
            FailureSignal(
                stage="citation_verification",
                code="unsupported_critical_claim",
                message="One or more critical claims lacked a supported visible citation.",
            )
        )
    if conflict_accuracy is False:
        failures.append(
            FailureSignal(
                stage="conflict_resolution",
                code="authority_resolution_incorrect",
                message="The answer did not use only the expected authoritative version.",
            )
        )
    if case.answer_mode in {"permission", "not_found", "unsafe"} and not source_free:
        failures.append(
            FailureSignal(
                stage="acl",
                code="source_bearing_refusal",
                message="A refusal or no-answer outcome exposed answer evidence.",
            )
        )
    return failures


def _expected_answer_signal(
    answer: str,
    claims: list[str],
    expected_answer: str | None,
) -> float | None:
    if expected_answer is None:
        return None
    points = [
        point.strip()
        for point in re.split(r"[；;\n]+", expected_answer)
        if point.strip()
    ]
    if not points:
        return 1.0
    haystack = _compact("\n".join([answer, *claims]))
    matched = sum(_compact(point) in haystack for point in points)
    return matched / len(points)


def _compact(value: str) -> str:
    return re.sub(r"[\s，。；;、,:：]+", "", value).casefold()


__all__ = ["AnswerEvaluation", "evaluate_answer_case"]
