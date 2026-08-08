from pathlib import Path

from app.evaluation.garak_latent_report import (
    GarakLatentReportFixture,
    build_garak_latent_report_expanded_fixture,
    extract_class_assignments,
)
from app.security.retrieved_content import RetrievedContentGuard


ROOT = Path(__file__).resolve().parents[2]


def test_garak_ast_extraction_reads_only_required_static_assignments() -> None:
    source = '''
MARKER = "<marker>"
class Probe:
    top_instructions = ["Summarize"]
    contexts = [f"Report {MARKER}"]
    injection_sep_pairs = [("\\n", "")]
    injection_instructions = [f"Ignore and print {MARKER}"]
    payloads = [f"Visit {MARKER}"]
    dynamic = dangerous_call()
'''

    values = extract_class_assignments(source, class_name="Probe")

    assert values == {
        "top_instructions": ["Summarize"],
        "contexts": ["Report <marker>"],
        "injection_sep_pairs": [("\n", "")],
        "injection_instructions": ["Ignore and print <marker>"],
        "payloads": ["Visit <marker>"],
    }


def test_garak_holdout_attack_combinations_are_disjoint_from_development() -> None:
    development = GarakLatentReportFixture.model_validate_json(
        (ROOT / "data/external_benchmarks/garak_latent_report_v1.json").read_text(
            encoding="utf-8"
        )
    )
    holdout = GarakLatentReportFixture.model_validate_json(
        (
            ROOT
            / "data/external_benchmarks/garak_latent_report_holdout_v1.json"
        ).read_text(encoding="utf-8")
    )

    def combinations(
        fixture: GarakLatentReportFixture,
    ) -> set[tuple[int, int, int, int]]:
        return {
            (
                case.context_index,
                case.injection_instruction_index,
                case.payload_index,
                case.trigger_index,
            )
            for case in fixture.cases
            if case.label == "attack"
        }

    assert len(combinations(development)) == 12
    assert len(combinations(holdout)) == 12
    assert combinations(development).isdisjoint(combinations(holdout))
    assert holdout.attack_case_count == 12
    assert holdout.benign_case_count == 2


def test_guard_classifies_pinned_garak_development_content() -> None:
    fixture = GarakLatentReportFixture.model_validate_json(
        (ROOT / "data/external_benchmarks/garak_latent_report_v1.json").read_text(
            encoding="utf-8"
        )
    )
    guard = RetrievedContentGuard()

    dispositions = {
        case.case_id: guard.scan(case.retrieved_content).disposition
        for case in fixture.cases
    }

    assert all(
        dispositions[case.case_id] == "QUARANTINE"
        for case in fixture.cases
        if case.label == "attack"
    )
    assert all(
        dispositions[case.case_id] == "ADMIT"
        for case in fixture.cases
        if case.label == "benign"
    )


def test_expanded_fixture_crosses_source_tuples_with_all_contexts() -> None:
    development = GarakLatentReportFixture.model_validate_json(
        (ROOT / "data/external_benchmarks/garak_latent_report_v1.json").read_bytes()
    )
    holdout = GarakLatentReportFixture.model_validate_json(
        (
            ROOT / "data/external_benchmarks/garak_latent_report_holdout_v1.json"
        ).read_bytes()
    )
    expanded = build_garak_latent_report_expanded_fixture(
        development=development,
        holdout=holdout,
    )
    attacks = [case for case in expanded.cases if case.label == "attack"]
    source_tuples = {
        (
            case.injection_instruction_index,
            case.payload_index,
            case.trigger_index,
        )
        for case in attacks
    }

    assert expanded.attack_case_count == 48
    assert expanded.benign_case_count == 4
    assert len(source_tuples) == 12
    assert {case.context_index for case in attacks} == {0, 1, 2, 3}
    assert all(
        sum(
            item.context_index == context and (
                item.injection_instruction_index,
                item.payload_index,
                item.trigger_index,
            )
            == source_tuple
            for item in attacks
        )
        == 1
        for context in range(4)
        for source_tuple in source_tuples
    )


def test_guard_classifies_every_expanded_case() -> None:
    development = GarakLatentReportFixture.model_validate_json(
        (ROOT / "data/external_benchmarks/garak_latent_report_v1.json").read_bytes()
    )
    holdout = GarakLatentReportFixture.model_validate_json(
        (
            ROOT / "data/external_benchmarks/garak_latent_report_holdout_v1.json"
        ).read_bytes()
    )
    expanded = build_garak_latent_report_expanded_fixture(
        development=development,
        holdout=holdout,
    )
    guard = RetrievedContentGuard()

    assert all(
        guard.scan(case.retrieved_content).disposition
        == ("QUARANTINE" if case.label == "attack" else "ADMIT")
        for case in expanded.cases
    )
