from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.controller_v2 import ControllerDecision, ControllerState, V2AgentController
from app.agent.query_analysis import RuleFirstQueryAnalyzer
from app.agent.runner_v2 import ExtractiveResponseBuilder, V2AgentRunner
from app.agent.tools_v2 import V2ToolRegistry
from app.domain.agent import AgentBudget
from app.domain.evidence import AnswerResponse
from app.domain.queries import QueryAnalysis, UserContext
from app.domain.retrieved_security import GuardedV2ToolExecution
from app.external_datasets.wixqa import WixQAQuestion
from app.external_datasets.wixqa_agent_eval import WixQARankedNavigator
from app.retrieval.pipeline import RankedSearchPool


SHA256_PATTERN = r"^[0-9a-f]{64}$"
STAGE_SEQUENCE = (
    "retrieval_top20",
    "retrieval_top5",
    "controller_search",
    "post_acl",
    "post_guard",
    "ledger",
    "response_selection",
    "post_grounding",
    "final",
)


class FirstLossStage(StrEnum):
    NO_FAILURE = "NO_FAILURE"
    RETRIEVAL_TOP20_MISS = "RETRIEVAL_TOP20_MISS"
    RETRIEVAL_TOP5_MISS = "RETRIEVAL_TOP5_MISS"
    ACL_FILTERED = "ACL_FILTERED"
    GUARD_FILTERED = "GUARD_FILTERED"
    QUERY_ANALYSIS_UNDERSPECIFIED = "QUERY_ANALYSIS_UNDERSPECIFIED"
    CONTROLLER_SEARCH_INSUFFICIENT = "CONTROLLER_SEARCH_INSUFFICIENT"
    LEDGER_ASSEMBLY_LOSS = "LEDGER_ASSEMBLY_LOSS"
    PROMPT_BUDGET_LOSS = "PROMPT_BUDGET_LOSS"
    RESPONSE_BUILDER_CITATION_OMISSION = (
        "RESPONSE_BUILDER_CITATION_OMISSION"
    )
    GENERATOR_CITATION_OMISSION = "GENERATOR_CITATION_OMISSION"
    GROUNDING_GATE_REMOVAL = "GROUNDING_GATE_REMOVAL"
    EVALUATOR_MISMATCH = "EVALUATOR_MISMATCH"
    UNKNOWN = "UNKNOWN"


class FrozenMultiDocCase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question_id: str = Field(min_length=1)
    question_sha256: str = Field(pattern=SHA256_PATTERN)
    answer_sha256: str = Field(pattern=SHA256_PATTERN)
    gold_support_article_ids: list[str] = Field(min_length=2)

    @classmethod
    def from_protocol_record(
        cls, record: Mapping[str, object]
    ) -> "FrozenMultiDocCase":
        if record.get("case_type") != "multi_document":
            raise ValueError("protocol record is not a multi-document case")
        return cls.model_validate(
            {
                "question_id": record.get("question_id"),
                "question_sha256": record.get("question_sha256"),
                "answer_sha256": record.get("answer_sha256"),
                "gold_support_article_ids": record.get(
                    "gold_support_article_ids"
                ),
            }
        )

    @model_validator(mode="after")
    def validate_gold_documents(self) -> "FrozenMultiDocCase":
        if len(self.gold_support_article_ids) != len(
            set(self.gold_support_article_ids)
        ):
            raise ValueError("gold document IDs must be distinct")
        return self


class MultiDocAttributionCase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    case_id: str = Field(min_length=1)
    question_id_sha256: str = Field(pattern=SHA256_PATTERN)
    gold_document_ids: list[str] = Field(min_length=2)
    gold_document_count: int = Field(ge=2)
    retrieval_top5_document_ids: list[str]
    retrieval_top10_document_ids: list[str]
    retrieval_top20_document_ids: list[str]
    controller_retrieved_document_ids: list[str]
    post_acl_document_ids: list[str]
    pre_guard_document_ids: list[str]
    post_guard_document_ids: list[str]
    intent: str = Field(min_length=1)
    required_aspects: list[str] = Field(min_length=1)
    controller_search_query_sha256: list[str]
    controller_search_call_count: int = Field(ge=0)
    controller_find_call_count: int = Field(ge=0)
    controller_open_call_count: int = Field(ge=0)
    controller_stop_reason: str = Field(min_length=1)
    ledger_supported_aspects: list[str]
    ledger_document_ids: list[str]
    ledger_coverage: float = Field(ge=0, le=1)
    ledger_recommended_action: str = Field(min_length=1)
    prompt_stage_status: Literal[
        "NOT_APPLICABLE_SOURCE_RUN_EXTRACTIVE",
        "OBSERVED",
    ]
    prompt_document_ids: list[str]
    generation_stage_status: Literal[
        "NOT_APPLICABLE_SOURCE_RUN_EXTRACTIVE",
        "OBSERVED",
    ]
    model_proposed_citation_document_ids: list[str]
    response_selected_document_ids: list[str]
    pre_grounding_citation_document_ids: list[str]
    post_grounding_citation_document_ids: list[str]
    final_source_document_ids: list[str]
    source_observed_citation_complete: bool
    gold_retrieval_oracle_post_guard_document_ids: list[str]
    gold_retrieval_oracle_final_source_document_ids: list[str]
    guard_quarantined_count: int = Field(ge=0)
    guard_risk_categories: list[str]
    coverage_by_stage: dict[str, float]
    first_loss_stage: FirstLossStage
    query_analysis_underspecified: bool
    ledger_false_completeness: bool
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_attribution(self) -> "MultiDocAttributionCase":
        if self.gold_document_count != len(set(self.gold_document_ids)):
            raise ValueError("gold document count does not match distinct IDs")
        sequences = {
            "retrieval_top20": self.retrieval_top20_document_ids,
            "retrieval_top5": self.retrieval_top5_document_ids,
            "controller_search": self.controller_retrieved_document_ids,
            "post_acl": self.post_acl_document_ids,
            "post_guard": self.post_guard_document_ids,
            "ledger": self.ledger_document_ids,
            "response_selection": self.response_selected_document_ids,
            "post_grounding": self.post_grounding_citation_document_ids,
            "final": self.final_source_document_ids,
        }
        expected_coverages = {
            name: gold_coverage(self.gold_document_ids, values)
            for name, values in sequences.items()
        }
        if set(self.coverage_by_stage) != set(STAGE_SEQUENCE):
            raise ValueError("coverage map must contain every attribution stage")
        for name, expected in expected_coverages.items():
            if abs(self.coverage_by_stage[name] - expected) > 1e-12:
                raise ValueError(f"coverage mismatch at {name}")
        expected_loss = classify_first_loss(
            gold_document_ids=self.gold_document_ids,
            retrieval_top20_document_ids=self.retrieval_top20_document_ids,
            retrieval_top5_document_ids=self.retrieval_top5_document_ids,
            controller_retrieved_document_ids=(
                self.controller_retrieved_document_ids
            ),
            post_acl_document_ids=self.post_acl_document_ids,
            post_guard_document_ids=self.post_guard_document_ids,
            ledger_document_ids=self.ledger_document_ids,
            response_selected_document_ids=self.response_selected_document_ids,
            post_grounding_document_ids=self.post_grounding_citation_document_ids,
            final_document_ids=self.final_source_document_ids,
        )
        if self.first_loss_stage != expected_loss:
            raise ValueError("first-loss stage does not match stage evidence")
        expected_false_completeness = (
            self.ledger_coverage == 1.0
            and gold_coverage(self.gold_document_ids, self.ledger_document_ids) < 1.0
        )
        if self.ledger_false_completeness != expected_false_completeness:
            raise ValueError("ledger false-completeness flag is inconsistent")
        return self


def gold_coverage(gold_ids: Sequence[str], observed_ids: Sequence[str]) -> float:
    gold = set(gold_ids)
    if not gold:
        raise ValueError("gold evidence must not be empty")
    return len(gold.intersection(observed_ids)) / len(gold)


def all_gold_recalled(
    gold_ids: Sequence[str], observed_ids: Sequence[str]
) -> bool:
    return set(gold_ids).issubset(observed_ids)


def classify_first_loss(
    *,
    gold_document_ids: Sequence[str],
    retrieval_top20_document_ids: Sequence[str],
    retrieval_top5_document_ids: Sequence[str],
    controller_retrieved_document_ids: Sequence[str],
    post_acl_document_ids: Sequence[str],
    post_guard_document_ids: Sequence[str],
    ledger_document_ids: Sequence[str],
    response_selected_document_ids: Sequence[str],
    post_grounding_document_ids: Sequence[str],
    final_document_ids: Sequence[str],
) -> FirstLossStage:
    checks = (
        (FirstLossStage.RETRIEVAL_TOP20_MISS, retrieval_top20_document_ids),
        (FirstLossStage.RETRIEVAL_TOP5_MISS, retrieval_top5_document_ids),
        (
            FirstLossStage.CONTROLLER_SEARCH_INSUFFICIENT,
            controller_retrieved_document_ids,
        ),
        (FirstLossStage.ACL_FILTERED, post_acl_document_ids),
        (FirstLossStage.GUARD_FILTERED, post_guard_document_ids),
        (FirstLossStage.LEDGER_ASSEMBLY_LOSS, ledger_document_ids),
        (
            FirstLossStage.RESPONSE_BUILDER_CITATION_OMISSION,
            response_selected_document_ids,
        ),
        (FirstLossStage.GROUNDING_GATE_REMOVAL, post_grounding_document_ids),
        (FirstLossStage.EVALUATOR_MISMATCH, final_document_ids),
    )
    for stage, observed in checks:
        if not all_gold_recalled(gold_document_ids, observed):
            return stage
    return FirstLossStage.NO_FAILURE


def validate_frozen_case(
    frozen: FrozenMultiDocCase,
    question: WixQAQuestion,
    known_article_ids: set[str],
) -> None:
    if frozen.question_id != question.question_id:
        raise ValueError("frozen case does not match question ID")
    if frozen.question_sha256 != _sha256_text(question.question):
        raise ValueError("frozen question hash mismatch")
    if frozen.answer_sha256 != _sha256_text(question.answer):
        raise ValueError("frozen answer hash mismatch")
    if frozen.gold_support_article_ids != question.article_ids:
        raise ValueError("frozen gold mapping differs from source question")
    if not set(frozen.gold_support_article_ids).issubset(known_article_ids):
        raise ValueError("frozen gold document ID does not resolve")


def citation_complete(
    gold_document_ids: Sequence[str], cited_document_ids: Sequence[str]
) -> bool:
    return all_gold_recalled(gold_document_ids, cited_document_ids)


@dataclass
class DiagnosticCapture:
    analysis: QueryAnalysis | None = None
    decisions: list[ControllerDecision] = field(default_factory=list)
    executions: list[GuardedV2ToolExecution] = field(default_factory=list)
    observed_states: list[ControllerState] = field(default_factory=list)
    final_state: ControllerState | None = None
    response_selected_document_ids: list[str] = field(default_factory=list)


class RecordingQueryAnalyzer:
    def __init__(
        self,
        capture: DiagnosticCapture,
        delegate: RuleFirstQueryAnalyzer | None = None,
    ) -> None:
        self.capture = capture
        self.delegate = delegate or RuleFirstQueryAnalyzer()

    def analyze(self, question: str, user: UserContext) -> QueryAnalysis:
        analysis = self.delegate.analyze(question, user)
        self.capture.analysis = analysis
        return analysis


class RecordingController:
    def __init__(
        self,
        capture: DiagnosticCapture,
        delegate: V2AgentController | None = None,
    ) -> None:
        self.capture = capture
        self.delegate = delegate or V2AgentController()

    def initialize(self, *args, **kwargs) -> ControllerState:
        state = self.delegate.initialize(*args, **kwargs)
        self.capture.observed_states.append(state)
        return state

    def next_decision(self, state: ControllerState) -> ControllerDecision:
        decision = self.delegate.next_decision(state)
        self.capture.decisions.append(decision)
        return decision

    def observe(
        self,
        state: ControllerState,
        execution: GuardedV2ToolExecution,
    ) -> ControllerState:
        next_state = self.delegate.observe(state, execution)
        self.capture.executions.append(execution)
        self.capture.observed_states.append(next_state)
        return next_state


class RecordingExtractiveResponseBuilder:
    def __init__(
        self,
        capture: DiagnosticCapture,
        *,
        max_evidence_per_aspect: int = 1,
    ) -> None:
        self.capture = capture
        self.max_evidence_per_aspect = max_evidence_per_aspect
        self.delegate = ExtractiveResponseBuilder(
            max_evidence_per_aspect=max_evidence_per_aspect
        )

    def build(self, **kwargs) -> AnswerResponse:
        state: ControllerState = kwargs["state"]
        self.capture.final_state = state
        selected: list[str] = []
        supported = state.ledger.supported_aspects if state.ledger else []
        for aspect in supported:
            evidence_items = state.evidence_by_aspect.get(aspect, [])
            for evidence in evidence_items[: self.max_evidence_per_aspect]:
                doc_id = evidence.hit.doc_id
                if doc_id not in selected:
                    selected.append(doc_id)
        self.capture.response_selected_document_ids = selected
        return self.delegate.build(**kwargs)


class RecordingWixQANavigator(WixQARankedNavigator):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.raw_search_pools: list[RankedSearchPool] = []

    def search_ranked(self, request) -> RankedSearchPool:
        pool = super().search_ranked(request)
        self.raw_search_pools.append(pool)
        return pool


def run_recorded_agent(
    *,
    question: str,
    user: UserContext,
    navigator: RecordingWixQANavigator,
    budget: AgentBudget,
    top_k: int = 5,
) -> tuple[AnswerResponse, DiagnosticCapture]:
    capture = DiagnosticCapture()
    runner = V2AgentRunner(
        registry=V2ToolRegistry(navigator),
        analyzer=RecordingQueryAnalyzer(capture),
        controller=RecordingController(capture),
        response_builder=RecordingExtractiveResponseBuilder(capture),
        budget=budget,
    )
    return runner.run(question, user, top_k=top_k), capture


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "DiagnosticCapture",
    "FirstLossStage",
    "FrozenMultiDocCase",
    "MultiDocAttributionCase",
    "RecordingWixQANavigator",
    "STAGE_SEQUENCE",
    "all_gold_recalled",
    "citation_complete",
    "classify_first_loss",
    "gold_coverage",
    "run_recorded_agent",
    "validate_frozen_case",
]
