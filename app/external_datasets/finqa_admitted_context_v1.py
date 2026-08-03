from __future__ import annotations

import re
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.agent.controller_v2 import ControllerState
from app.domain.evidence import AnswerResponse
from app.domain.retrieved_security import AdmittedEvidenceChunk
from app.external_datasets.finqa_numeric_evidence_v2 import (
    NumericCandidateV2,
    extract_numeric_candidates_v2,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    build_retrievable_safe_descriptor_catalog_v3,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
    SemanticProgramStepV2,
    SemanticRoleRefV2,
    SemanticRoleSpecV2,
)
from app.external_datasets.finqa_service_adapter_v1 import (
    FinQAEphemeralContextResolverV1,
    FinQATypedServiceAdapterV1,
    FinQATypedServiceContextV1,
    FinQATypedServiceResolutionV1,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    extract_financial_question_intent_v2,
)
from app.runtime.dark_observation import (
    DarkObservationOfferOutcome,
    DarkObservationService,
)
from app.runtime.request_context import current_request_id
from app.security.retrieved_content import RetrievedContentGuard


ADMITTED_CONTEXT_VERSION = "finqa_admitted_context_v1"
MAX_EVIDENCE_UNITS = 32
MAX_TOTAL_EVIDENCE_CHARS = 16_000
MAX_NUMERIC_CANDIDATES = 128
MAX_QUESTION_CHARS = 2_000

OperationFamilyV1 = Literal[
    "average",
    "exact_add",
    "exact_divide",
    "exact_multiply",
    "exact_subtract",
    "percent_change",
    "ratio",
]
PreparationReasonV1 = Literal[
    "TYPED_CONTEXT_COMPLETE",
    "NOT_FINANCIAL_NUMERIC",
    "MISSING_TYPED_SKELETON",
    "MISSING_SAFE_CATALOG",
    "POLICY_DENIED",
    "UNSUPPORTED_TYPED_CONTRACT",
    "NOT_EVALUATED_DEFAULT_OFF",
]

_CHINESE_FAMILY_PATTERNS: tuple[tuple[OperationFamilyV1, re.Pattern[str]], ...] = (
    (
        "percent_change",
        re.compile(r"(?:百分比?变化|增长率|增幅|降幅|同比增长|同比下降)"),
    ),
    ("ratio", re.compile(r"(?:占比|比率|比例|利润率)")),
    ("exact_subtract", re.compile(r"(?:差额|相差|多多少|少多少|绝对变化)")),
    ("average", re.compile(r"(?:平均值|均值|平均为多少)")),
    ("exact_add", re.compile(r"(?:合计|总和|相加|加总)")),
    ("exact_multiply", re.compile(r"(?:乘积|相乘)")),
    ("exact_divide", re.compile(r"(?:相除|除以|商是多少)")),
)
_FINANCIAL_NUMERIC_SIGNAL = re.compile(
    r"(?:\d|revenue|income|profit|expense|asset|liabilit|cash|margin|"
    r"percent|financial|fiscal|quarter|year|收入|利润|费用|资产|负债|"
    r"现金|财务|季度|年度|百分比)",
    re.IGNORECASE,
)

_SKELETON_SHAPES: dict[
    OperationFamilyV1,
    tuple[
        str,
        tuple[tuple[str, str], ...],
    ],
] = {
    "average": (
        "AVERAGE",
        (("component", "target"), ("component", "target")),
    ),
    "exact_add": (
        "ADD",
        (("component", "target"), ("component", "target")),
    ),
    "exact_divide": (
        "DIV",
        (("value", "target"), ("divisor", "target")),
    ),
    "exact_multiply": (
        "MUL",
        (("factor", "target"), ("factor", "target")),
    ),
    "exact_subtract": (
        "SUB",
        (("comparison_left", "target"), ("comparison_right", "target")),
    ),
    "percent_change": (
        "PERCENT_CHANGE",
        (("new_value", "end"), ("old_value", "start")),
    ),
    "ratio": (
        "RATIO",
        (("part", "target"), ("total", "target")),
    ),
}


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


class TypedObservationOfferReceiptV1(_StrictFrozenModel):
    schema_version: Literal[
        "finqa_typed_observation_offer_receipt_v1"
    ] = "finqa_typed_observation_offer_receipt_v1"
    offer_outcome: DarkObservationOfferOutcome
    preparation_reason: PreparationReasonV1
    admitted_evidence_count: int = Field(ge=0, le=MAX_EVIDENCE_UNITS)
    numeric_candidate_count: int = Field(ge=0, le=MAX_NUMERIC_CANDIDATES)
    resolver_registered: bool
    resolver_discarded: bool
    secondary_retrieval_calls: Literal[0] = 0
    model_calls: Literal[0] = 0


@dataclass(frozen=True)
class FinQAAdmittedContextBuildV1:
    resolution: FinQATypedServiceResolutionV1
    admitted_evidence_count: int
    numeric_candidate_count: int
    operation_family: OperationFamilyV1 | None


class _ResponseBuilder(Protocol):
    def build(
        self,
        *,
        question: str,
        state: ControllerState,
        mode: str,
        stop_reason: str | None,
        trace: dict,
    ) -> AnswerResponse: ...


def _operation_family(question: str) -> OperationFamilyV1 | None:
    if not isinstance(question, str):
        return None
    bounded = question.strip()
    if not bounded or len(bounded) > MAX_QUESTION_CHARS:
        return None
    for family, pattern in _CHINESE_FAMILY_PATTERNS:
        if pattern.search(bounded):
            return family
    try:
        family = extract_financial_question_intent_v2(
            bounded
        ).operation_family
    except (TypeError, ValueError):
        return None
    if family in _SKELETON_SHAPES:
        return family
    return None


def build_online_rule_skeleton_v1(
    question: str,
) -> tuple[OperationFamilyV1, SemanticProgramSkeletonV2] | None:
    family = _operation_family(question)
    if family is None:
        return None
    operation, role_shapes = _SKELETON_SHAPES[family]
    roles = tuple(
        SemanticRoleSpecV2(
            role_id=f"role-{index:02d}",
            semantic_role=semantic_role,
            period_role=period_role,
        )
        for index, (semantic_role, period_role) in enumerate(
            role_shapes,
            start=1,
        )
    )
    step = SemanticProgramStepV2(
        step_id="step-01",
        operation=operation,
        arguments=tuple(
            SemanticRoleRefV2(role_id=role.role_id) for role in roles
        ),
    )
    return family, SemanticProgramSkeletonV2(
        roles=roles,
        steps=(step,),
        output_step_id=step.step_id,
    )


def admitted_evidence_from_state_v1(
    state: ControllerState,
) -> tuple[AdmittedEvidenceChunk, ...]:
    if not isinstance(state, ControllerState):
        raise TypeError("E18 requires a typed ControllerState")
    by_chunk_id: dict[str, AdmittedEvidenceChunk] = {}
    for hits in state.evidence_by_aspect.values():
        for evidence in hits:
            if not isinstance(evidence, AdmittedEvidenceChunk):
                raise TypeError("E18 state contains non-admitted evidence")
            existing = by_chunk_id.get(evidence.hit.chunk_id)
            if existing is not None and existing != evidence:
                raise ValueError("E18 chunk identity maps to conflicting evidence")
            by_chunk_id[evidence.hit.chunk_id] = evidence
    return tuple(by_chunk_id[key] for key in sorted(by_chunk_id))


def _not_applicable(
    reason: Literal[
        "NOT_FINANCIAL_NUMERIC",
        "MISSING_TYPED_SKELETON",
        "MISSING_SAFE_CATALOG",
        "POLICY_DENIED",
        "UNSUPPORTED_TYPED_CONTRACT",
    ],
    *,
    evidence_count: int,
    candidate_count: int = 0,
    family: OperationFamilyV1 | None = None,
) -> FinQAAdmittedContextBuildV1:
    return FinQAAdmittedContextBuildV1(
        resolution=FinQATypedServiceResolutionV1.not_applicable(reason),
        admitted_evidence_count=evidence_count,
        numeric_candidate_count=candidate_count,
        operation_family=family,
    )


def build_finqa_admitted_context_v1(
    *,
    question: str,
    evidence: tuple[AdmittedEvidenceChunk, ...],
    guard: RetrievedContentGuard | None = None,
) -> FinQAAdmittedContextBuildV1:
    if not isinstance(evidence, tuple) or any(
        not isinstance(item, AdmittedEvidenceChunk) for item in evidence
    ):
        raise TypeError("E18 accepts only a tuple of AdmittedEvidenceChunk")
    skeleton_build = build_online_rule_skeleton_v1(question)
    if skeleton_build is None:
        return _not_applicable(
            (
                "MISSING_TYPED_SKELETON"
                if isinstance(question, str)
                and _FINANCIAL_NUMERIC_SIGNAL.search(question)
                else "NOT_FINANCIAL_NUMERIC"
            ),
            evidence_count=min(len(evidence), MAX_EVIDENCE_UNITS),
        )
    family, skeleton = skeleton_build
    if not evidence:
        return _not_applicable(
            "MISSING_SAFE_CATALOG",
            evidence_count=0,
            family=family,
        )
    if len(evidence) > MAX_EVIDENCE_UNITS:
        return _not_applicable(
            "UNSUPPORTED_TYPED_CONTRACT",
            evidence_count=MAX_EVIDENCE_UNITS,
            family=family,
        )
    chunk_ids = tuple(item.hit.chunk_id for item in evidence)
    if len(chunk_ids) != len(set(chunk_ids)):
        return _not_applicable(
            "UNSUPPORTED_TYPED_CONTRACT",
            evidence_count=len(evidence),
            family=family,
        )
    total_chars = sum(len(item.hit.context_text) for item in evidence)
    if total_chars > MAX_TOTAL_EVIDENCE_CHARS:
        return _not_applicable(
            "UNSUPPORTED_TYPED_CONTRACT",
            evidence_count=len(evidence),
            family=family,
        )

    active_guard = guard or RetrievedContentGuard()
    ordered = tuple(sorted(evidence, key=lambda item: item.hit.chunk_id))
    context_by_id = {
        item.hit.chunk_id: item.hit.context_text for item in ordered
    }
    if any(
        active_guard.scan(text).disposition != "ADMIT"
        for text in context_by_id.values()
    ):
        return _not_applicable(
            "POLICY_DENIED",
            evidence_count=len(evidence),
            family=family,
        )

    candidates: list[NumericCandidateV2] = []
    try:
        for item in ordered:
            candidates.extend(
                candidate
                for candidate in extract_numeric_candidates_v2(
                    source_id=item.hit.doc_id,
                    evidence_id=item.hit.chunk_id,
                    text=item.hit.context_text,
                    kind="text",
                )
                if candidate.role == "operand"
            )
    except (TypeError, ValueError):
        return _not_applicable(
            "UNSUPPORTED_TYPED_CONTRACT",
            evidence_count=len(evidence),
            family=family,
        )
    if not candidates:
        return _not_applicable(
            "MISSING_SAFE_CATALOG",
            evidence_count=len(evidence),
            family=family,
        )
    if len(candidates) > MAX_NUMERIC_CANDIDATES:
        return _not_applicable(
            "UNSUPPORTED_TYPED_CONTRACT",
            evidence_count=len(evidence),
            candidate_count=MAX_NUMERIC_CANDIDATES,
            family=family,
        )
    try:
        catalog_build = build_retrievable_safe_descriptor_catalog_v3(
            candidates=tuple(candidates),
            admitted_evidence_ids=set(chunk_ids),
            evidence_context_by_id=context_by_id,
            guard=active_guard,
        )
        context = FinQATypedServiceContextV1.build(
            question=question.strip(),
            skeleton=skeleton,
            catalog=catalog_build.catalog,
            skeleton_origin="ONLINE_RULES",
            catalog_origin="RETRIEVED_ADMITTED_EVIDENCE",
        )
    except (TypeError, ValueError):
        return _not_applicable(
            "UNSUPPORTED_TYPED_CONTRACT",
            evidence_count=len(evidence),
            candidate_count=len(candidates),
            family=family,
        )
    return FinQAAdmittedContextBuildV1(
        resolution=FinQATypedServiceResolutionV1.eligible(context),
        admitted_evidence_count=len(evidence),
        numeric_candidate_count=len(candidates),
        operation_family=family,
    )


class FinQAAdmittedContextCoordinatorV1:
    """Owns E16/E17 admission and cleans every non-admitted context."""

    def __init__(
        self,
        *,
        resolver: FinQAEphemeralContextResolverV1,
        adapter: FinQATypedServiceAdapterV1,
        dark_observation: DarkObservationService,
        guard: RetrievedContentGuard | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.resolver = resolver
        self.adapter = adapter
        self.dark_observation = dark_observation
        self.guard = guard or RetrievedContentGuard()
        self._clock = clock
        self._lock = threading.Lock()
        self._counters: Counter[str] = Counter()
        self._eligibility: Counter[str] = Counter()
        self._preparation_latencies_ms: list[float] = []
        self._closed = False

    def start(self) -> None:
        self.dark_observation.start()

    def offer(
        self,
        *,
        request_id: str,
        question: str,
        primary_mode: str,
        primary_stop_reason: str | None,
        evidence: tuple[AdmittedEvidenceChunk, ...],
    ) -> TypedObservationOfferReceiptV1:
        with self._lock:
            closed = self._closed
        if closed:
            return self._receipt(
                outcome="CLOSED",
                reason="NOT_EVALUATED_DEFAULT_OFF",
            )
        if self.dark_observation.config.mode == "OFF":
            outcome = self.dark_observation.offer(
                request_id=request_id,
                question=question,
                primary_mode=primary_mode,
                primary_stop_reason=primary_stop_reason,
            )
            return self._receipt(
                outcome=outcome,
                reason="NOT_EVALUATED_DEFAULT_OFF",
            )

        started = self._clock()
        build = build_finqa_admitted_context_v1(
            question=question,
            evidence=evidence,
            guard=self.guard,
        )
        elapsed_ms = max(0.0, (self._clock() - started) * 1_000.0)
        with self._lock:
            self._preparation_latencies_ms.append(elapsed_ms)
            self._eligibility[build.resolution.reason] += 1
        try:
            self.resolver.register(
                request_id=request_id,
                resolution=build.resolution,
            )
        except Exception:
            with self._lock:
                self._counters["resolver_registration_error_total"] += 1
            return self._receipt(
                outcome="UNAVAILABLE",
                reason=build.resolution.reason,
                build=build,
            )

        try:
            outcome = self.dark_observation.offer(
                request_id=request_id,
                question=question,
                primary_mode=primary_mode,
                primary_stop_reason=primary_stop_reason,
            )
        except Exception:
            discarded = self.resolver.discard(request_id)
            with self._lock:
                self._counters["dark_offer_error_total"] += 1
            return self._receipt(
                outcome="UNAVAILABLE",
                reason=build.resolution.reason,
                build=build,
                registered=True,
                discarded=discarded,
            )

        discarded = False
        if outcome != "ADMITTED":
            discarded = self.resolver.discard(request_id)
        return self._receipt(
            outcome=outcome,
            reason=build.resolution.reason,
            build=build,
            registered=True,
            discarded=discarded,
        )

    def _receipt(
        self,
        *,
        outcome: DarkObservationOfferOutcome,
        reason: PreparationReasonV1,
        build: FinQAAdmittedContextBuildV1 | None = None,
        registered: bool = False,
        discarded: bool = False,
    ) -> TypedObservationOfferReceiptV1:
        with self._lock:
            self._counters[f"offer_{outcome.casefold()}_total"] += 1
        return TypedObservationOfferReceiptV1(
            offer_outcome=outcome,
            preparation_reason=reason,
            admitted_evidence_count=(
                build.admitted_evidence_count if build is not None else 0
            ),
            numeric_candidate_count=(
                build.numeric_candidate_count if build is not None else 0
            ),
            resolver_registered=registered,
            resolver_discarded=discarded,
        )

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            latencies = tuple(self._preparation_latencies_ms)
            counters = dict(sorted(self._counters.items()))
            eligibility = dict(sorted(self._eligibility.items()))
            closed = self._closed
        ordered = sorted(latencies)

        def percentile(fraction: float) -> float:
            if not ordered:
                return 0.0
            index = max(0, min(len(ordered) - 1, int(len(ordered) * fraction)))
            return round(ordered[index], 3)

        return {
            "schema_version": "finqa_admitted_context_metrics_v1",
            "component_version": ADMITTED_CONTEXT_VERSION,
            "counters": counters,
            "eligibility_reasons": eligibility,
            "preparation_latency_ms": {
                "count": len(ordered),
                "p50": percentile(0.50),
                "p95": percentile(0.95),
                "max": round(ordered[-1], 3) if ordered else 0.0,
            },
            "resolver": self.resolver.snapshot(),
            "adapter": self.adapter.snapshot(),
            "dark_observation": self.dark_observation.snapshot(),
            "secondary_retrieval_calls": 0,
            "model_calls": 0,
            "content_retained_in_snapshot": False,
            "closed": closed,
        }

    def close(self) -> dict[str, int]:
        with self._lock:
            if self._closed:
                return {"residual_workers": 0}
            self._closed = True
        dark_result = self.dark_observation.close()
        self.adapter.close()
        self.resolver.close()
        return dark_result


class FinQATypedObservationResponseBuilderV1:
    """Runs E18 only after the primary answer object has been constructed."""

    def __init__(
        self,
        *,
        delegate: _ResponseBuilder,
        coordinator: FinQAAdmittedContextCoordinatorV1,
        request_id_provider: Callable[[], str | None] = current_request_id,
    ) -> None:
        self.delegate = delegate
        self.coordinator = coordinator
        self.request_id_provider = request_id_provider

    def build(
        self,
        *,
        question: str,
        state: ControllerState,
        mode: str,
        stop_reason: str | None,
        trace: dict,
    ) -> AnswerResponse:
        answer = self.delegate.build(
            question=question,
            state=state,
            mode=mode,
            stop_reason=stop_reason,
            trace=trace,
        )
        try:
            request_id = self.request_id_provider()
            if request_id:
                self.coordinator.offer(
                    request_id=request_id,
                    question=question,
                    primary_mode=answer.mode,
                    primary_stop_reason=answer.stop_reason,
                    evidence=admitted_evidence_from_state_v1(state),
                )
        except Exception:
            pass
        return answer


__all__ = [
    "ADMITTED_CONTEXT_VERSION",
    "FinQAAdmittedContextBuildV1",
    "FinQAAdmittedContextCoordinatorV1",
    "FinQATypedObservationResponseBuilderV1",
    "TypedObservationOfferReceiptV1",
    "admitted_evidence_from_state_v1",
    "build_finqa_admitted_context_v1",
    "build_online_rule_skeleton_v1",
]
