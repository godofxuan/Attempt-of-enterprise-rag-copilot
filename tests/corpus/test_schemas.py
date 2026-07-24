from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.corpus.schemas import CompanyFacts, CorpusProfile


def valid_facts_payload() -> dict:
    return {
        "schema_version": "enterprise_facts_v1",
        "company": "星桥科技（虚构）",
        "tenants": ["starbridge-cn"],
        "regions": ["cn"],
        "departments": ["hr"],
        "acl_groups": ["all_employees", "hr_confidential"],
        "users": [
            {
                "user_id": "user_hr",
                "tenant": "starbridge-cn",
                "region": "cn",
                "groups": ["all_employees", "hr_confidential"],
            }
        ],
        "policies": [
            {
                "policy_id": "hr_remote",
                "title": "远程办公制度",
                "department": "hr",
                "tenant": "starbridge-cn",
                "region": "cn",
                "versions": [
                    {
                        "version_id": "hr_remote@2025",
                        "version": "2025.1",
                        "status": "retired",
                        "effective_from": "2025-01-01",
                        "effective_to": "2026-01-01",
                        "authority": 100,
                        "supersedes": None,
                        "acl_groups": ["all_employees"],
                        "facts": [
                            {
                                "fact_id": "hr_remote_2025_days",
                                "question": "2025 年每周可远程几天？",
                                "answer": "2 天",
                                "statement": "2025 年每周最多远程办公 2 天。",
                            }
                        ],
                    },
                    {
                        "version_id": "hr_remote@2026",
                        "version": "2026.1",
                        "status": "active",
                        "effective_from": "2026-01-01",
                        "effective_to": None,
                        "authority": 100,
                        "supersedes": "hr_remote@2025",
                        "acl_groups": ["all_employees"],
                        "facts": [
                            {
                                "fact_id": "hr_remote_2026_days",
                                "question": "当前每周可远程几天？",
                                "answer": "3 天",
                                "statement": "当前每周最多远程办公 3 天。",
                            }
                        ],
                    },
                ],
            }
        ],
    }


def test_company_facts_accepts_a_valid_versioned_policy() -> None:
    facts = CompanyFacts.model_validate(valid_facts_payload())

    assert facts.company == "星桥科技（虚构）"
    assert facts.policies[0].active_version.version_id == "hr_remote@2026"


def test_company_facts_rejects_unknown_acl_group() -> None:
    payload = valid_facts_payload()
    payload["policies"][0]["versions"][1]["acl_groups"] = ["missing_group"]

    with pytest.raises(ValidationError, match="unknown ACL group"):
        CompanyFacts.model_validate(payload)


def test_company_facts_rejects_duplicate_fact_ids() -> None:
    payload = valid_facts_payload()
    duplicate = deepcopy(payload["policies"][0]["versions"][1]["facts"][0])
    payload["policies"][0]["versions"][1]["facts"].append(duplicate)

    with pytest.raises(ValidationError, match="fact_id"):
        CompanyFacts.model_validate(payload)


def test_company_facts_rejects_invalid_effective_interval() -> None:
    payload = valid_facts_payload()
    payload["policies"][0]["versions"][0]["effective_to"] = "2024-12-31"

    with pytest.raises(ValidationError, match="effective_to"):
        CompanyFacts.model_validate(payload)


def test_company_facts_rejects_cyclic_supersedes_chain() -> None:
    payload = valid_facts_payload()
    payload["policies"][0]["versions"][0]["supersedes"] = "hr_remote@2026"

    with pytest.raises(ValidationError, match="cycle"):
        CompanyFacts.model_validate(payload)


def test_company_facts_rejects_overlapping_successive_versions() -> None:
    payload = valid_facts_payload()
    payload["policies"][0]["versions"][1]["effective_from"] = "2025-12-01"

    with pytest.raises(ValidationError, match="overlap"):
        CompanyFacts.model_validate(payload)


def test_company_facts_rejects_policy_without_a_retired_version() -> None:
    payload = valid_facts_payload()
    payload["policies"][0]["versions"] = [
        payload["policies"][0]["versions"][1]
    ]
    payload["policies"][0]["versions"][0]["supersedes"] = None

    with pytest.raises(ValidationError, match="retired version"):
        CompanyFacts.model_validate(payload)


def test_profile_rejects_ratios_that_consume_the_whole_corpus() -> None:
    payload = {
        "schema_version": "enterprise_corpus_profile_v1",
        "profile_id": "demo",
        "document_count": 72,
        "seed": 20260716,
        "format_weights": {"md": 4, "txt": 2, "html": 2, "csv": 1, "jsonl": 1},
        "source_type_weights": {
            "policy": 1,
            "wiki": 2,
            "email": 2,
            "ticket": 2,
            "meeting": 1,
            "table": 1,
        },
        "duplicate_ratio": 0.4,
        "near_duplicate_ratio": 0.3,
        "misfiled_ratio": 0.2,
        "stale_ratio": 0.1,
        "eval_dev_count": 24,
        "eval_test_count": 28,
    }

    with pytest.raises(ValidationError, match="variant ratios"):
        CorpusProfile.model_validate(payload)
