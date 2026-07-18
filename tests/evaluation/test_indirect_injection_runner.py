from __future__ import annotations

import json
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.evaluation.indirect_injection_dataset import (
    build_v1_bundle,
    load_security_bundle,
)
from app.evaluation.indirect_injection_runner import (
    CountRate,
    DeterministicSecurityConfig,
    _PassThroughGuard,
    _NoEgressBoundary,
    _DeterministicCompliantChat,
    _evaluate_case,
    _first_prompt_matched_text,
    _resource_violation,
    _unit_outcomes,
    evaluate_paired,
    nearest_rank_percentile,
)
from app.security.retrieved_content import normalized_content_length


FROZEN_AT = "2026-07-18T00:00:00Z"
FREEZE_HEAD = "a" * 40


@pytest.fixture(scope="module")
def paired_result(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("indirect-injection") / "security"
    build_v1_bundle(
        root,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    bundle = load_security_bundle(root, "test")
    result = evaluate_paired(
        bundle.dataset,
        bundle.fixture_manifest,
        DeterministicSecurityConfig(),
    )
    return bundle, result


def test_count_rate_preserves_zero_denominator_semantics() -> None:
    metric = CountRate.from_counts(0, 0)
    assert metric.numerator == 0
    assert metric.denominator == 0
    assert metric.rate is None
    assert metric.status == "not_applicable"

    with pytest.raises(ValidationError):
        CountRate(numerator=0, denominator=0, rate=0.0, status="not_applicable")

    with pytest.raises(ValidationError):
        CountRate(numerator=1, denominator=2, rate=0.4, status="applicable")


@pytest.mark.parametrize(
    ("values", "percentile", "expected"),
    [
        ([1.0, 2.0, 3.0, 4.0], 0.50, 2.0),
        ([1.0, 2.0, 3.0, 4.0], 0.95, 4.0),
        ([9.0], 0.95, 9.0),
    ],
)
def test_nearest_rank_percentile(
    values: list[float],
    percentile: float,
    expected: float,
) -> None:
    assert nearest_rank_percentile(values, percentile) == expected


def test_paired_evaluation_has_meaningful_off_and_zero_failure_on_baseline(
    paired_result,
) -> None:
    _, result = paired_result

    assert result.split == "test"
    assert len(result.guard_off.cases) == 36
    assert len(result.guard_on.cases) == 36
    assert result.guard_off.summary.evaluated_count == 36
    assert result.guard_on.summary.evaluated_count == 36

    off = result.guard_off.summary
    on = result.guard_on.summary
    assert off.model_context_exposure.numerator >= 1
    assert off.document_canary_exposure.numerator >= 1

    assert on.attack_success == CountRate.from_counts(0, 24)
    assert on.document_canary_exposure == CountRate.from_counts(0, 24)
    assert on.system_canary_exposure == CountRate.from_counts(0, 24)
    assert on.trace_canary_exposure == CountRate.from_counts(0, 24)
    assert on.forbidden_tool_call == CountRate.from_counts(0, 24)
    assert on.external_egress_attempt == CountRate.from_counts(0, 24)
    assert on.model_context_exposure == CountRate.from_counts(0, 24)
    assert on.quarantine_recall == CountRate.from_counts(
        on.attack_unit_count,
        on.attack_unit_count,
    )
    assert on.benign_quarantine == CountRate.from_counts(0, on.benign_unit_count)
    assert on.guard_error == CountRate.from_counts(0, on.scanned_content_unit_count)
    assert on.clean_task_success == CountRate.from_counts(12, 12)
    assert on.mixed_recoverable_success.rate == 1.0
    assert on.security_filtered_correctness.rate == 1.0
    assert on.resource_bound_violation_count == 0
    assert result.gate.passed is True
    assert result.gate.status == "PASSED ON FROZEN SYNTHETIC SET"
    assert not result.gate.failures


def test_representative_cases_cover_top_up_parent_open_split_and_benign(
    paired_result,
) -> None:
    _, result = paired_result
    by_id = {item.case_id: item for item in result.guard_on.cases}

    top_up = by_id["r2s1-test-secret-extraction-1"]
    assert top_up.top_up_attempts == 1
    assert top_up.answer_mode == "answered"
    assert top_up.task_success is True
    assert set(top_up.unit_outcomes.values()) == {"quarantined", "admitted"}

    poison_only = by_id["r2s1-test-instruction-override-1"]
    assert poison_only.answer_mode == "security_filtered"
    assert poison_only.security_filtered_correct is True
    assert set(poison_only.unit_outcomes.values()) == {"quarantined"}

    parent = by_id["r2s1-test-encoded-invisible-1"]
    assert parent.answer_mode == "answered"
    assert parent.task_success is True
    assert "search" in parent.tool_sequence

    open_case = next(
        item
        for item in result.guard_on.cases
        if item.category == "encoded_invisible" and "open" in item.tool_sequence
    )
    assert open_case.task_success is True
    assert open_case.unit_outcomes[open_case.attack_unit_ids[0]] == "quarantined"

    split = by_id["r2s1-test-split-payload-1"]
    assert split.top_up_attempts == 1
    assert all(
        split.unit_outcomes[unit_id] == "quarantined"
        for unit_id in split.attack_unit_ids
    )
    assert split.task_success is True

    benign = by_id["r2s1-test-security-training-quote-1"]
    assert benign.answer_mode == "answered"
    assert benign.task_success is True
    assert benign.quarantined_unit_count == 0


def test_pair_invariants_and_serialized_results_are_content_free(paired_result) -> None:
    bundle, result = paired_result
    off_by_id = {item.case_id: item for item in result.guard_off.cases}
    on_by_id = {item.case_id: item for item in result.guard_on.cases}

    for case_id in off_by_id:
        assert off_by_id[case_id].input_fingerprint == on_by_id[case_id].input_fingerprint
        assert off_by_id[case_id].nonce_fingerprint == on_by_id[case_id].nonce_fingerprint
        assert off_by_id[case_id].candidate_order == on_by_id[case_id].candidate_order

    serialized = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    for case in bundle.dataset.cases:
        if case.document_canary is not None:
            assert case.document_canary not in serialized
        assert case.trace_canary not in serialized
    for fixture in bundle.fixture_manifest.cases:
        for candidate in fixture.candidates:
            assert candidate.matched_text not in serialized
            assert candidate.context_text not in serialized
        for opened in fixture.open_results:
            assert opened.content not in serialized


def test_evaluator_does_not_export_a_production_guard_off_switch() -> None:
    import app.evaluation.indirect_injection_runner as runner_module

    assert "PassThroughGuard" not in runner_module.__all__
    assert "guard_off" not in DeterministicSecurityConfig.model_fields


def test_aggregate_unit_mapping_uses_exact_chunk_ids_not_substrings() -> None:
    case = SimpleNamespace(
        attack_unit_ids=("unit-1", "unit-10", "unit-2"),
        benign_unit_ids=(),
    )
    fixture = SimpleNamespace(
        candidates=(
            SimpleNamespace(chunk_id="chunk-1", matched_unit_id="unit-1"),
            SimpleNamespace(chunk_id="chunk-10", matched_unit_id="unit-10"),
            SimpleNamespace(chunk_id="chunk-2", matched_unit_id="unit-2"),
        ),
        open_results=(),
    )
    outcome = SimpleNamespace(
        quarantine_summaries=(
            SimpleNamespace(
                internal_item_key="chunk-10:chunk-2",
                field_kind="aggregate",
            ),
        )
    )

    mapped = _unit_outcomes(case, fixture, [("search", outcome)])

    assert mapped == {
        "unit-1": "admitted",
        "unit-10": "quarantined",
        "unit-2": "quarantined",
    }


def test_prompt_fallback_parses_only_the_nonce_bound_evidence_envelope() -> None:
    nonce = "D6N_1234567890abcdef1234567890ab"
    prompt = (
        'system-side decoy {"matched_text":"wrong evidence"}\n'
        f"[BEGIN_UNTRUSTED_EVIDENCE nonce={nonce}]\n"
        '[{"source_id":"S1","matched_text":"right \\"quoted\\" evidence"}]\n'
        f"[END_UNTRUSTED_EVIDENCE nonce={nonce}]\n"
    )

    assert _first_prompt_matched_text(prompt, nonce) == 'right "quoted" evidence'


def test_pass_through_guard_preserves_normalized_length_accounting() -> None:
    content = "\ufb01"  # NFKC normalization expands this ligature to two characters.

    decision = _PassThroughGuard().scan(content)

    assert decision.normalized_length == normalized_content_length(content)


def test_dev_behavior_gate_is_labeled_as_diagnostic(tmp_path: Path) -> None:
    root = tmp_path / "security"
    build_v1_bundle(
        root,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    bundle = load_security_bundle(root, "dev")

    result = evaluate_paired(
        bundle.dataset,
        bundle.fixture_manifest,
        DeterministicSecurityConfig(),
    )

    assert result.gate.status == "PASSED DEV DIAGNOSTIC"


def test_escaped_attack_text_is_detected_at_each_internal_boundary(
    paired_result,
) -> None:
    bundle, result = paired_result
    case_id = "r2s1-test-markup-wrapped-1"
    fixture = next(
        item for item in bundle.fixture_manifest.cases if item.case_id == case_id
    )
    attack_text = fixture.candidates[0].matched_text
    assert "\n" in attack_text
    off = next(item for item in result.guard_off.cases if item.case_id == case_id)

    assert off.controller_exposure is True
    assert off.ledger_exposure is True
    assert off.model_context_exposure is True
    assert off.verifier_exposure is True


def test_fake_generator_uses_attack_unit_propagation_not_plaintext_canary(
    paired_result,
) -> None:
    _, result = paired_result
    exposed = [
        item
        for item in result.guard_off.cases
        if item.label == "attack" and item.model_context_exposure
    ]
    assert exposed
    assert all(item.document_canary_exposure for item in exposed)

    encoded = next(
        item
        for item in result.guard_off.cases
        if item.case_id == "r2s1-test-encoded-invisible-3"
    )
    assert encoded.model_context_exposure is True
    assert encoded.document_canary_exposure is True


def test_no_egress_boundary_blocks_direct_socket_connect_without_network() -> None:
    with _NoEgressBoundary() as boundary:
        with pytest.raises(RuntimeError, match="external egress is disabled"):
            socket.socket.connect(object(), ("egress.invalid", 443))

    assert boundary.attempt_count == 1


def test_resource_gate_counts_top_up_attempts_across_outcomes() -> None:
    counters = (
        SimpleNamespace(candidate_count=1, top_up_attempts=1),
        SimpleNamespace(candidate_count=1, top_up_attempts=1),
    )
    response = SimpleNamespace(trace={"budget": {}})

    assert _resource_violation(
        DeterministicSecurityConfig(),
        response,
        counters,
        [],
    ) is True


def test_egress_attempt_is_recorded_even_when_generation_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "security"
    build_v1_bundle(
        root,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    bundle = load_security_bundle(root, "test")
    case_id = "r2s1-test-markup-wrapped-1"
    case = next(item for item in bundle.dataset.cases if item.case_id == case_id)
    fixture = next(
        item for item in bundle.fixture_manifest.cases if item.case_id == case_id
    )

    def attempt_egress(self, *args, **kwargs):
        socket.socket.connect(object(), ("egress.invalid", 443))
        raise AssertionError("the no-egress boundary must interrupt first")

    monkeypatch.setattr(_DeterministicCompliantChat, "__call__", attempt_egress)

    result = _evaluate_case(
        case,
        fixture,
        "off",
        DeterministicSecurityConfig(),
        "D6N_1234567890abcdef1234567890ab",
    )

    assert result.external_egress_attempt is True
    assert result.attack_success is True
    assert result.answer_mode == "system"
