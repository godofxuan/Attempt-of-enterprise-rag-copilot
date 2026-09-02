from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.retrieval.canary_config import RetrievalCanarySettings


def test_retrieval_canary_defaults_off() -> None:
    settings = RetrievalCanarySettings(_env_file=None)

    assert settings.profile == "default"
    assert settings.canary_policy_ids == []


def test_retrieval_canary_requires_the_registered_profile_and_allowlist() -> None:
    settings = RetrievalCanarySettings(
        _env_file=None,
        profile="finance_known_report_page_fusion_v1",
        canary_policy_ids=["finance-report-policy-1"],
    )

    assert settings.profile == "finance_known_report_page_fusion_v1"
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
