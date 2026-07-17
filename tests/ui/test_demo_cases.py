from __future__ import annotations

from pathlib import Path

from app.evaluation.security import SECURITY_PROBES
from streamlit_app.demo_cases import load_demo_cases


ROOT = Path(__file__).resolve().parents[2]


def test_loads_seven_named_cases_from_canonical_sources() -> None:
    cases = load_demo_cases(ROOT)

    assert [case.category for case in cases] == [
        "single_document",
        "comparison",
        "version_conflict",
        "multi_condition",
        "not_found",
        "permission",
        "direct_injection",
    ]
    assert [case.provenance_id for case in cases[:6]] == [
        "fact_hr_remote_2026_notice",
        "compare_procurement_vendor_engineering_release",
        "conflict_customer_refund",
        "complete_security_incident",
        "missing_engineering_release",
        "permission_hr_compensation",
    ]
    assert all(case.provenance == "eval_case" for case in cases[:6])
    assert "expected_answer" not in type(cases[0]).model_fields


def test_direct_injection_uses_fixed_probe_and_is_never_mislabeled() -> None:
    case = load_demo_cases(ROOT)[-1]
    probe = next(
        item for item in SECURITY_PROBES if item.probe_id == "instruction_override"
    )

    assert case.provenance == "security_probe"
    assert case.provenance_id == "instruction_override"
    assert case.question == probe.prompt
    assert case.expected_mode == "unsafe"
    assert "document" not in case.label.casefold()
    assert "indirect" not in case.label.casefold()


def test_eval_user_context_maps_to_runtime_contract() -> None:
    permission = load_demo_cases(ROOT)[5]

    assert permission.user.tenant_id == "starbridge-cn"
    assert permission.user.groups == ["external_contractors"]
    assert permission.user.roles == []
