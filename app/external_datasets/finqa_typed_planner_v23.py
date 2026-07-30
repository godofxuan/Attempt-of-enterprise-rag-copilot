from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.external_datasets import finqa_typed_planner as v1_planner
from app.external_datasets import finqa_typed_planner_v2 as v22_planner
from app.external_datasets.finqa_numeric_evidence_v2 import NumericCandidateV2
from app.external_datasets.finqa_typed_contract_v2 import (
    FinancialQuestionIntentV2,
)
from app.external_datasets.finqa_typed_contract_v23 import (
    TypedProgramResultV23,
    compile_and_execute_typed_program_v23,
)
from app.external_datasets.finqa_typed_program import (
    TypedProgram,
    TypedProgramValidationError,
)
from app.ollama_chat import chat_with_ollama


PLANNER_VERSION = "finqa_typed_planner_v2_3"


@dataclass(frozen=True)
class TypedPlannerResultV23:
    planner_version: str
    intent: FinancialQuestionIntentV2
    program: TypedProgram
    execution: TypedProgramResultV23
    attempt_count: int
    latency_ms: float
    generation_calls: int
    compiler_calls: int


class LocalFinQATypedProgramPlannerV23:
    def __init__(
        self,
        *,
        model: str,
        chat_fn: v1_planner.TypedPlannerChatFn = chat_with_ollama,
        max_attempts: int = 2,
    ) -> None:
        if not model.strip() or len(model.strip()) > 200:
            raise ValueError("v2.3 planner model must contain 1-200 characters")
        if not 1 <= max_attempts <= 3:
            raise ValueError("v2.3 planner attempts must be between 1 and 3")
        self.model = model.strip()
        self.chat_fn = chat_fn
        self.max_attempts = max_attempts

    def plan_and_execute(
        self,
        *,
        question: str,
        candidates: Sequence[NumericCandidateV2],
        admitted_evidence_ids: set[str],
        intent: FinancialQuestionIntentV2 | None = None,
        evidence_context_by_id: Mapping[str, str] | None = None,
    ) -> TypedPlannerResultV23:
        resolved_intent = intent or v22_planner.extract_financial_question_intent_v2(
            question
        )
        usable = v22_planner.question_conditioned_candidate_shortlist_v2(
            question=question,
            candidates=candidates,
            admitted_evidence_ids=admitted_evidence_ids,
            intent=resolved_intent,
            evidence_context_by_id=evidence_context_by_id,
        )
        candidate_ids = [candidate.candidate_id for candidate in usable]
        messages = v22_planner.build_typed_planner_messages_v2(
            question=question,
            candidates=usable,
            admitted_evidence_ids=admitted_evidence_ids,
            intent=resolved_intent,
            evidence_context_by_id=evidence_context_by_id,
        )
        response_format = v22_planner.typed_program_sketch_response_format_v2(
            candidate_ids=candidate_ids,
            intent=resolved_intent,
        )
        started = time.perf_counter()
        last_error: Exception | None = None
        last_reason = "invalid_program_schema"
        compiler_calls = 0
        attempt_count = 0
        for attempt_count in range(1, self.max_attempts + 1):
            raw = self.chat_fn(
                self.model,
                messages,
                response_format=response_format,
                think=False,
            )
            try:
                sketch = v22_planner.parse_typed_program_sketch_v2(
                    raw,
                    candidate_ids=candidate_ids,
                    intent=resolved_intent,
                )
                payload = v22_planner.compile_typed_program_sketch_v2(sketch)
                compiler_calls += 1
                execution = compile_and_execute_typed_program_v23(
                    planner_payload=payload,
                    candidates=usable,
                    admitted_evidence_ids=admitted_evidence_ids,
                    intent=resolved_intent,
                )
                return TypedPlannerResultV23(
                    planner_version=PLANNER_VERSION,
                    intent=resolved_intent,
                    program=TypedProgram.model_validate(payload),
                    execution=execution,
                    attempt_count=attempt_count,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    generation_calls=attempt_count,
                    compiler_calls=compiler_calls,
                )
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                last_reason = (
                    exc.reason
                    if isinstance(exc, TypedProgramValidationError)
                    else "invalid_program_schema"
                )
                if attempt_count < self.max_attempts:
                    messages = [
                        *messages,
                        {"role": "assistant", "content": raw[:4_096]},
                        {
                            "role": "user",
                            "content": v22_planner._repair_prompt_v2(
                                reason=last_reason,
                                candidate_ids=candidate_ids,
                                intent=resolved_intent,
                            ),
                        },
                    ]
        assert last_error is not None
        raise v1_planner.TypedPlannerProtocolError(
            attempt_count=attempt_count,
            latency_ms=(time.perf_counter() - started) * 1000,
            last_reason=last_reason,
            compiler_calls=compiler_calls,
        ) from last_error


__all__ = [
    "PLANNER_VERSION",
    "LocalFinQATypedProgramPlannerV23",
    "TypedPlannerResultV23",
]
