from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.retrieval.canary_config import RetrievalCanarySettings


def test_retrieval_canary_defaults_off() -> None:
    settings = RetrievalCanarySettings(_env_file=None)

    assert settings.profile == "default"
    assert settings.canary_policy_ids == []
    assert settings.finance_known_report_page_fusion_enabled is True
    assert settings.finance_known_report_policy_ids == []
    assert settings.page_fusion_policy_ids == []


def test_retrieval_canary_requires_the_registered_profile_and_allowlist() -> None:
    settings = RetrievalCanarySettings(
        _env_file=None,
        profile="finance_known_report_page_fusion_v1",
        canary_policy_ids=["finance-report-policy-1"],
    )

    assert settings.profile == "finance_known_report_page_fusion_v1"
    assert settings.page_fusion_policy_ids == ["finance-report-policy-1"]
    with pytest.raises(ValidationError):
        RetrievalCanarySettings(_env_file=None, profile="finance_page_fusion_latest")
    with pytest.raises(ValidationError, match="explicit policy allowlist"):
        RetrievalCanarySettings(
            _env_file=None,
            profile="finance_known_report_page_fusion_v1",
        )
    with pytest.raises(ValidationError, match="stale canary allowlist"):
        RetrievalCanarySettings(
            _env_file=None,
            canary_policy_ids=["finance-report-policy-1"],
        )


def test_promoted_finance_profile_uses_server_classification_without_legacy_opt_in() -> None:
    settings = RetrievalCanarySettings(
        _env_file=None,
        finance_known_report_policy_ids=["finance-report-policy-1"],
    )

    assert settings.profile == "default"
    assert settings.page_fusion_policy_ids == ["finance-report-policy-1"]


def test_promoted_finance_profile_has_fail_closed_rollback_and_legacy_boundaries() -> None:
    disabled = RetrievalCanarySettings(
        _env_file=None,
        finance_known_report_page_fusion_enabled=False,
        finance_known_report_policy_ids=["finance-report-policy-1"],
    )
    assert disabled.page_fusion_policy_ids == []
    with pytest.raises(ValidationError, match="cannot both be set"):
        RetrievalCanarySettings(
            _env_file=None,
            profile="finance_known_report_page_fusion_v1",
            canary_policy_ids=["legacy-policy"],
            finance_known_report_policy_ids=["promoted-policy"],
        )
