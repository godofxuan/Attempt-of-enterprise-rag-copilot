from __future__ import annotations

from app.evaluation.attribution import attribute_failures
from app.evaluation.contracts import FailureSignal


def signal(stage: str, code: str) -> FailureSignal:
    return FailureSignal(stage=stage, code=code, message=f"failure: {code}")


def test_attribution_uses_earliest_observable_stage_not_input_order() -> None:
    primary, secondary = attribute_failures(
        [
            signal("generation", "missing_fact"),
            signal("retrieval", "gold_missing"),
            signal("citation_verification", "unsupported_claim"),
        ]
    )

    assert primary == "retrieval"
    assert secondary == ["generation", "citation_verification"]


def test_attribution_prioritizes_runtime_and_acl_fail_closed() -> None:
    primary, secondary = attribute_failures(
        [
            signal("retrieval", "gold_missing"),
            signal("acl", "unauthorized_exposure"),
            signal("system_runtime", "timeout"),
        ]
    )

    assert primary == "system_runtime"
    assert secondary == ["acl", "retrieval"]


def test_attribution_collapses_duplicate_stages_but_not_source_signals() -> None:
    signals = [
        signal("ranking", "gold_below_cutoff"),
        signal("ranking", "invalid_extra"),
        signal("generation", "fact_omission"),
    ]

    primary, secondary = attribute_failures(signals)

    assert len(signals) == 3
    assert primary == "ranking"
    assert secondary == ["generation"]


def test_attribution_returns_empty_for_passing_case() -> None:
    assert attribute_failures([]) == (None, [])
