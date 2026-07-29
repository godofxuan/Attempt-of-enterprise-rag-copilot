from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.external_datasets.finqa import FinQACase, build_finqa_evidence_units
from app.external_datasets.finqa_eval import LocalFinQAProgramAnswerer
from app.external_datasets.finqa_multi_program import (
    LocalFinQAMultiProgramPlanner,
)
from app.external_datasets.finqa_typed_planner import (
    LocalFinQATypedProgramPlanner,
)
from app.external_datasets.finqa_typed_retrospective import (
    FinQATypedArmEvaluation,
    FinQATypedRetrospectiveCase,
    FinQATypedRetrospectiveProtocol,
    FinQATypedRetrospectiveRunManifest,
    FrozenModelIdentity,
    build_public_evidence,
    canonical_json_bytes,
    implementation_snapshot_sha256,
    publish_typed_retrospective_run,
    summarize_typed_retrospective,
    verify_typed_retrospective_run,
)
from scripts.eval_finqa_typed_retrospective import (
    _evaluate_b0,
    _evaluate_b1,
    _evaluate_b2,
    _prepare_typed_context,
)


_SHA = "a" * 64
_REVISION = "b" * 40


def _case() -> FinQACase:
    return FinQACase.model_validate(
        {
            "pre_text": [],
            "post_text": [],
            "filename": "report.pdf",
            "table_ori": [
                ["", "2020", "2019"],
                ["Revenue", "$120 million", "$100 million"],
            ],
            "table": [
                ["", "2020", "2019"],
                ["Revenue", "$120 million", "$100 million"],
            ],
            "qa": {
                "question": "What was the total revenue in 2019 and 2020?",
                "answer": "220",
                "explanation": "",
                "ann_table_rows": [1],
                "ann_text_rows": [],
                "steps": [],
                "program": "add(120, 100)",
                "gold_inds": {"table_1": "Revenue values"},
                "exe_ans": 220000000,
                "tfidftopn": {},
                "program_re": "add(120, 100)",
                "model_input": [],
            },
            "id": "private-case-id",
            "table_retrieved": [],
            "text_retrieved": [],
            "table_retrieved_all": [],
            "text_retrieved_all": [],
        }
    )


class _ContractAwareFakeChat:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(
        self,
        _model,
        messages,
        *,
        response_format=None,
        think=None,
    ) -> str:
        assert think is False
        self.calls += 1
        properties = response_format["properties"]
        if "expression" in properties:
            return json.dumps(
                {
                    "expression": "120000000 + 100000000",
                    "cited_candidate_ids": ["evidence-01"],
                }
            )
        user_payload = json.loads(messages[1]["content"])
        candidate_ids = [
            item["candidate_id"] for item in user_payload["candidates"]
        ]
        forward = _add_program(candidate_ids[0], candidate_ids[1])
        if "programs" in properties:
            reverse = _add_program(candidate_ids[1], candidate_ids[0])
            return json.dumps({"programs": [forward, reverse]})
        return json.dumps(forward)


def _add_program(first: str, second: str) -> dict:
    return {
        "dsl_version": "finqa_typed_financial_dsl_v1",
        "steps": [
            {
                "step_id": "step-01",
                "operation": "ADD",
                "arguments": [
                    {"candidate_id": first},
                    {"candidate_id": second},
                ],
            }
        ],
        "output_step_id": "step-01",
    }


def _arm(
    arm_id: str,
    *,
    correct: bool,
    status: str = "ANSWERED",
    calls: int = 1,
    latency: float = 10,
) -> FinQATypedArmEvaluation:
    answered = status == "ANSWERED"
    return FinQATypedArmEvaluation(
        arm_id=arm_id,
        status=status,
        failure_reason=None if answered else "ambiguous_intent",
        final_answer="1" if answered else "",
        calculation="program" if answered else "",
        cited_unit_ids=["table_1"] if answered else [],
        answer_parseable=answered,
        strict_execution_match=correct if answered else False,
        presentation_tolerance_match=correct if answered else False,
        citation_precision=1 if answered else 0,
        citation_recall=1 if answered else 0,
        grounded_execution_match=correct if answered else False,
        grounded_presentation_match=correct if answered else False,
        generation_calls=calls,
        compiler_calls=calls,
        generated_program_count=calls,
        latency_ms=latency,
        candidate_count=2 if arm_id != "B0_FREE_LITERAL" else 0,
        selected_support_count=1 if answered else 0,
        valid_program_count=1 if answered else 0,
        invalid_program_count=0,
        duplicate_program_count=0,
    )


def _row(
    case_id: str,
    *,
    b0_correct: bool,
    b1_correct: bool,
    b2_correct: bool,
    b1_status: str = "ANSWERED",
) -> FinQATypedRetrospectiveCase:
    return FinQATypedRetrospectiveCase(
        case_id=case_id,
        diagnostic_category="operand_selection_signal",
        execution_order=(
            "B0_FREE_LITERAL",
            "B1_TYPED_SINGLE",
            "B2_TYPED_MULTI",
        ),
        selected_unit_ids=["table_1"],
        gold_unit_ids=["table_1"],
        selected_evidence_recall=1,
        admitted_unit_count=1,
        quarantined_unit_count=0,
        guard_rule_ids=[],
        historical_b0_strict_execution_match=b0_correct,
        historical_b0_grounded_execution_match=b0_correct,
        b0=_arm("B0_FREE_LITERAL", correct=b0_correct),
        b1=_arm(
            "B1_TYPED_SINGLE",
            correct=b1_correct,
            status=b1_status,
            calls=0 if b1_status != "ANSWERED" else 1,
        ),
        b2=_arm("B2_TYPED_MULTI", correct=b2_correct, calls=1),
    )


def _protocol() -> FinQATypedRetrospectiveProtocol:
    source_run = {
        "run_id": "source-run",
        "manifest_sha256": _SHA,
        "details_sha256": _SHA,
    }
    return FinQATypedRetrospectiveProtocol.model_validate(
        {
            "status": "FROZEN_BEFORE_EXECUTION",
            "protocol_id": "gate-e-v1",
            "implementation_base_revision": _REVISION,
            "dataset_revision": _REVISION,
            "split": "dev",
            "split_sha256": _SHA,
            "sample_seed": "disclosed-dev",
            "selected_case_count": 2,
            "selected_case_ids_sha256": _SHA,
            "retrieval_mode": "hybrid",
            "top_k": 10,
            "source_eval_run": source_run,
            "source_diagnostic_run": source_run,
            "arms": [
                "B0_FREE_LITERAL",
                "B1_TYPED_SINGLE",
                "B2_TYPED_MULTI",
            ],
            "arm_order_policy": "cyclic_latin_square_v1",
            "answer_model": {"name": "qwen3:8b", "sha256": _SHA},
            "timeout_seconds": 120,
            "max_attempts": 2,
            "multi_program_count": 3,
            "candidate_extraction_version": "extract-v1",
            "candidate_extraction_config_sha256": _SHA,
            "intent_version": "intent-v1",
            "dsl_version": "dsl-v1",
            "validator_version": "validator-v1",
            "compiler_version": "compiler-v1",
            "typed_planner_version": "planner-v1",
            "multi_program_planner_version": "multi-v1",
            "selector_version": "selector-v1",
            "source_file_sha256": {"app/example.py": _SHA},
            "primary_metrics": ["execution_accuracy"],
            "operational_metrics": ["generation_calls"],
            "stop_conditions": ["abort_on_model_digest_mismatch"],
            "non_claims": ["not a held-out result"],
        }
    )


def test_fake_model_executes_all_three_frozen_arms() -> None:
    case = _case()
    evidence = tuple(
        unit
        for unit in build_finqa_evidence_units(case)
        if unit.unit_id == "table_1"
    )
    context = _prepare_typed_context(case, evidence)
    fake = _ContractAwareFakeChat()

    b0 = _evaluate_b0(
        case=case,
        evidence=evidence,
        answerer=LocalFinQAProgramAnswerer(
            model="fake",
            chat_fn=fake,
            max_attempts=1,
        ),
    )
    b1 = _evaluate_b1(
        case=case,
        evidence=evidence,
        typed_context=context,
        planner=LocalFinQATypedProgramPlanner(
            model="fake",
            chat_fn=fake,
            max_attempts=1,
        ),
    )
    b2 = _evaluate_b2(
        case=case,
        evidence=evidence,
        typed_context=context,
        planner=LocalFinQAMultiProgramPlanner(
            model="fake",
            chat_fn=fake,
            program_count=2,
            max_attempts=1,
        ),
    )

    assert fake.calls == 3
    assert b0.strict_execution_match
    assert b1.strict_execution_match
    assert b2.strict_execution_match
    assert b1.selected_program_sha256
    assert b2.valid_program_count == 2
    assert b2.selected_support_count == 1


def test_summary_reports_fixes_regressions_refusals_and_cost() -> None:
    rows = [
        _row("case-1", b0_correct=False, b1_correct=True, b2_correct=True),
        _row(
            "case-2",
            b0_correct=True,
            b1_correct=False,
            b2_correct=True,
            b1_status="REFUSED",
        ),
    ]

    summary = summarize_typed_retrospective(rows)
    b1 = summary.arm_summaries["B1_TYPED_SINGLE"]
    comparison = summary.paired_comparisons[0]

    assert summary.claim_label == "RETROSPECTIVE_DEVELOPMENT_ONLY"
    assert b1.coverage == 0.5
    assert b1.execution_accuracy == 0.5
    assert b1.execution_accuracy_on_answered == 1
    assert comparison.transition_counts == {
        "correct_to_correct": 0,
        "correct_to_wrong": 1,
        "wrong_to_correct": 1,
        "wrong_to_wrong": 0,
    }
    assert comparison.prevented_operand_failure_count == 1
    assert comparison.new_refusal_count == 1
    assert comparison.mcnemar_exact_p_value == 1


def test_private_public_publication_is_reproducible_and_aggregate_only(
    tmp_path: Path,
) -> None:
    rows = [
        _row("private-case-1", b0_correct=False, b1_correct=True, b2_correct=True),
        _row("private-case-2", b0_correct=True, b1_correct=True, b2_correct=True),
    ]
    protocol = _protocol()
    summary = summarize_typed_retrospective(rows)
    manifest = FinQATypedRetrospectiveRunManifest(
        run_id="gate-e-run",
        protocol_id=protocol.protocol_id,
        protocol_sha256=hashlib.sha256(
            canonical_json_bytes(protocol.model_dump(mode="json"))
        ).hexdigest(),
        dataset_revision=protocol.dataset_revision,
        split="dev",
        split_sha256=protocol.split_sha256,
        selected_case_count=2,
        selected_case_ids_sha256=protocol.selected_case_ids_sha256,
        retrieval_mode="hybrid",
        top_k=10,
        answer_model=FrozenModelIdentity(name="qwen3:8b", sha256=_SHA),
        execution_code_revision=_REVISION,
        implementation_snapshot_sha256=implementation_snapshot_sha256(
            protocol.source_file_sha256
        ),
        timeout_seconds=120,
        max_attempts=2,
        multi_program_count=3,
        summary=summary,
    )
    run_dir = publish_typed_retrospective_run(
        root=tmp_path,
        manifest=manifest,
        details=rows,
    )

    verified = verify_typed_retrospective_run(run_dir)
    public = build_public_evidence(run_dir=run_dir, protocol=protocol)
    public_text = canonical_json_bytes(public.model_dump(mode="json")).decode()

    assert verified.summary == summary
    assert "private-case-1" not in public_text
    assert "table_1" not in public_text
    assert '"final_answer"' not in public_text
    assert public.private_details_sha256 == verified.artifacts["details.jsonl"]


def test_publication_detects_tampered_private_details(tmp_path: Path) -> None:
    rows = [
        _row("case-1", b0_correct=False, b1_correct=True, b2_correct=True),
        _row("case-2", b0_correct=True, b1_correct=True, b2_correct=True),
    ]
    protocol = _protocol()
    manifest = FinQATypedRetrospectiveRunManifest(
        run_id="tamper-run",
        protocol_id=protocol.protocol_id,
        protocol_sha256=hashlib.sha256(
            canonical_json_bytes(protocol.model_dump(mode="json"))
        ).hexdigest(),
        dataset_revision=protocol.dataset_revision,
        split="dev",
        split_sha256=protocol.split_sha256,
        selected_case_count=2,
        selected_case_ids_sha256=protocol.selected_case_ids_sha256,
        retrieval_mode="hybrid",
        top_k=10,
        answer_model=FrozenModelIdentity(name="qwen3:8b", sha256=_SHA),
        execution_code_revision=_REVISION,
        implementation_snapshot_sha256=implementation_snapshot_sha256(
            protocol.source_file_sha256
        ),
        timeout_seconds=120,
        max_attempts=2,
        multi_program_count=3,
        summary=summarize_typed_retrospective(rows),
    )
    run_dir = publish_typed_retrospective_run(
        root=tmp_path,
        manifest=manifest,
        details=rows,
    )
    with (run_dir / "details.jsonl").open("ab") as output:
        output.write(b" ")

    with pytest.raises(ValueError, match="artifact mismatch"):
        verify_typed_retrospective_run(run_dir)


def test_protocol_rejects_arm_drift() -> None:
    payload = _protocol().model_dump(mode="json")
    payload["arms"] = [
        "B1_TYPED_SINGLE",
        "B0_FREE_LITERAL",
        "B2_TYPED_MULTI",
    ]

    with pytest.raises(ValueError, match="frozen B0/B1/B2 order"):
        FinQATypedRetrospectiveProtocol.model_validate(payload)
