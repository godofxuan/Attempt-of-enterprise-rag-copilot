from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.external_datasets.finqa import DEFAULT_SOURCE_ROOT
from app.external_datasets.finqa_shadow_replay_v1 import (
    FinQAAggregateDistributionV1,
    FinQAShadowObservationSummaryV1,
    FinQAShadowOperationalReplaySummaryV1,
    FinQAShadowPreparationSummaryV1,
    evaluate_shadow_replay_gates_v1,
    load_finqa_shadow_replay_train_v1,
    prepare_finqa_shadow_replay_case_v1,
    select_shadow_replay_cases_v1,
)
from app.external_datasets.finqa_shadow_worker_protocol_v1 import (
    load_shadow_worker_replay_protocol_v1,
)
from app.security.retrieved_content import RetrievedContentGuard


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = (
    ROOT
    / "docs/external_datasets/evidence/finqa_shadow_worker_replay_protocol_v1.json"
)


@pytest.fixture(scope="module")
def protocol():
    protocol, _ = load_shadow_worker_replay_protocol_v1(PROTOCOL)
    return protocol


@pytest.fixture(scope="module")
def protocol_and_cases(protocol):
    train_path = DEFAULT_SOURCE_ROOT / "dataset/train.json"
    if not train_path.is_file():
        pytest.skip("private FinQA train split is unavailable")
    cases = load_finqa_shadow_replay_train_v1(
        train_path,
        expected_sha256=protocol.dataset.split_sha256,
    )
    return protocol, cases


def test_train_only_selection_matches_frozen_boundary(protocol_and_cases) -> None:
    protocol, cases = protocol_and_cases
    selected = select_shadow_replay_cases_v1(cases, protocol=protocol)

    assert len(selected) == 128
    assert len({case.id for case in selected}) == 128


def test_train_loader_redacts_invalid_quality_labels_before_validation(
    tmp_path: Path,
) -> None:
    source = {
        "pre_text": ["Revenue was 5."],
        "post_text": [],
        "filename": "example.pdf",
        "table_ori": [["Metric", "Value"], ["Revenue", "5"]],
        "table": [["Metric", "Value"], ["Revenue", "5"]],
        "qa": {
            "question": "What is revenue?",
            "answer": "sensitive-answer",
            "explanation": "sensitive-explanation",
            "ann_table_rows": [1],
            "ann_text_rows": [0],
            "steps": [],
            "program": "add(5, const_0)",
            "gold_inds": {"text_-1": "invalid official label"},
            "exe_ans": 5,
            "tfidftopn": {},
            "program_re": "add(5, const_0)",
            "model_input": [],
        },
        "id": "case-1",
        "table_retrieved": [],
        "text_retrieved": [],
        "table_retrieved_all": [],
        "text_retrieved_all": [],
    }
    content = json.dumps([source], ensure_ascii=True).encode("utf-8")
    path = tmp_path / "train.json"
    path.write_bytes(content)

    cases = load_finqa_shadow_replay_train_v1(
        path,
        expected_sha256=hashlib.sha256(content).hexdigest(),
    )

    assert cases[0].qa.answer == "REDACTED"
    assert cases[0].qa.exe_ans == 0
    assert cases[0].qa.gold_inds == {"text_0": "REDACTED"}
    assert cases[0].qa.ann_table_rows == []
    assert cases[0].qa.ann_text_rows == []


def test_replay_module_does_not_read_prohibited_quality_attributes() -> None:
    source = (
        ROOT / "app/external_datasets/finqa_shadow_replay_v1.py"
    ).read_text(encoding="utf-8")

    for expression in (
        "case.qa.answer",
        "case.qa.exe_ans",
        "case.qa.gold_inds",
        "case.qa.ann_table_rows",
        "case.qa.ann_text_rows",
    ):
        assert expression not in source


def test_replay_preparation_builds_runtime_input_without_labels(
    protocol_and_cases,
) -> None:
    protocol, cases = protocol_and_cases
    selected = select_shadow_replay_cases_v1(cases, protocol=protocol)
    prepared = None
    for case in selected:
        try:
            prepared = prepare_finqa_shadow_replay_case_v1(
                case,
                guard=RetrievedContentGuard(),
                selected_unit_limit=protocol.dataset.max_selected_units_per_case,
            )
            break
        except Exception:
            continue

    assert prepared is not None
    assert prepared.question
    assert prepared.skeleton.roles
    assert prepared.catalog.descriptors
    assert not hasattr(prepared, "answer")
    assert not hasattr(prepared, "gold_inds")


def _passing_summary() -> FinQAShadowOperationalReplaySummaryV1:
    return FinQAShadowOperationalReplaySummaryV1(
        preparation=FinQAShadowPreparationSummaryV1(
            selected_case_count=128,
            prepared_case_count=120,
            preparation_failure_count=8,
            primary_failure_count=0,
        ),
        observations=FinQAShadowObservationSummaryV1(
            attempted_count=120,
            completed_count=120,
            outcome_counts={"MATCH": 100, "DIVERGED": 20},
            role_count=180,
            changed_role_count=24,
            common_descriptor_count_at_4=680,
            worker_restart_count=0,
            model_call_count=0,
        ),
        latency_ms=FinQAAggregateDistributionV1(
            count=120,
            p50=2.0,
            p95=4.0,
            maximum=8.0,
        ),
        worker_peak_rss_bytes=FinQAAggregateDistributionV1(
            count=120,
            p50=100_000_000,
            p95=110_000_000,
            maximum=120_000_000,
        ),
        all_primary_results_e8=True,
        per_request_rows_persisted=0,
        quality_labels_consumed=0,
    )


def test_replay_gate_evaluation_is_exact_and_aggregate_only(
    protocol,
) -> None:
    summary = _passing_summary()

    assert all(evaluate_shadow_replay_gates_v1(summary, protocol=protocol).values())
    payload = summary.model_dump(mode="json")
    assert set(payload) == {
        "schema_version",
        "preparation",
        "observations",
        "latency_ms",
        "worker_peak_rss_bytes",
        "all_primary_results_e8",
        "per_request_rows_persisted",
        "quality_labels_consumed",
    }
    serialized = summary.model_dump_json()
    assert "case_id" not in serialized
    assert "descriptor_id" not in serialized


def test_replay_summary_rejects_per_request_extension() -> None:
    payload = _passing_summary().model_dump(mode="json")
    payload["per_request"] = [{"question": "secret"}]

    with pytest.raises(ValueError):
        FinQAShadowOperationalReplaySummaryV1.model_validate(payload)


def test_replay_summary_rejects_cross_group_count_drift() -> None:
    payload = _passing_summary().model_dump(mode="json")
    payload["observations"]["attempted_count"] = 119
    payload["observations"]["outcome_counts"] = {"MATCH": 99, "DIVERGED": 20}
    payload["observations"]["completed_count"] = 119
    payload["latency_ms"]["count"] = 119
    payload["worker_peak_rss_bytes"]["count"] = 119

    with pytest.raises(ValueError, match="preparation and observation"):
        FinQAShadowOperationalReplaySummaryV1.model_validate(payload)
