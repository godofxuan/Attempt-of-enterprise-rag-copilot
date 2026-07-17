import json
from pathlib import Path

from app.corpus.schemas import CompanyFacts, CorpusProfile


ROOT = Path(__file__).resolve().parents[2]
FACTS_PATH = ROOT / "data" / "v2" / "facts" / "company_facts_v1.json"
CONFIG_DIR = ROOT / "data" / "v2" / "config"
LEGACY_METADATA_PATH = ROOT / "data" / "eval" / "metadata.json"
DATA_CARD_PATH = ROOT / "docs" / "data_card.md"
TEST_MANIFEST_PATH = ROOT / "data" / "v2" / "eval" / "test_manifest.sha256"


def load_model(path: Path, model_type):
    return model_type.model_validate(json.loads(path.read_text(encoding="utf-8")))


def test_checked_in_fact_skeleton_is_complete_and_valid() -> None:
    facts = load_model(FACTS_PATH, CompanyFacts)

    assert facts.company.endswith("（虚构）")
    assert len(facts.policies) == 8
    assert sum(len(policy.versions) for policy in facts.policies) == 16
    assert sum(
        len(version.facts)
        for policy in facts.policies
        for version in policy.versions
    ) == 32
    assert {policy.active_version.status for policy in facts.policies} == {"active"}


def test_demo_and_benchmark_profiles_have_explicit_measured_scale() -> None:
    demo = load_model(CONFIG_DIR / "demo.json", CorpusProfile)
    benchmark = load_model(CONFIG_DIR / "benchmark.json", CorpusProfile)

    assert demo.profile_id == "demo"
    assert demo.document_count == 72
    assert benchmark.profile_id == "benchmark"
    assert benchmark.document_count == 600
    assert demo.eval_dev_count == benchmark.eval_dev_count == 24
    assert demo.eval_test_count == benchmark.eval_test_count == 28
    assert demo.seed == benchmark.seed == 20260716


def test_facts_include_public_and_restricted_policy_examples() -> None:
    facts = load_model(FACTS_PATH, CompanyFacts)
    active_acl_sets = {
        tuple(policy.active_version.acl_groups) for policy in facts.policies
    }

    assert ("all_employees",) in active_acl_sets
    assert any(groups != ("all_employees",) for groups in active_acl_sets)
    assert any(user.user_id == "user_contractor" for user in facts.users)
    assert any(user.user_id == "user_auditor" for user in facts.users)


def test_legacy_metadata_points_to_v2_without_rewriting_history() -> None:
    metadata = json.loads(LEGACY_METADATA_PATH.read_text(encoding="utf-8"))

    assert metadata["name"] == "enterprise_rag_golden_set_v1"
    assert metadata["lifecycle"]["status"] == "legacy_regression_only"
    assert metadata["lifecycle"]["successor"] == "data/v2/eval"
    assert "do not overwrite" in metadata["lifecycle"]["rule"]


def test_data_card_declares_synthetic_scope_profiles_and_frozen_test_hash() -> None:
    data_card = DATA_CARD_PATH.read_text(encoding="utf-8")
    test_hash = TEST_MANIFEST_PATH.read_text(encoding="utf-8").split()[0]

    assert "全部为虚构合成" in data_card
    assert "不包含真实企业" in data_card
    assert "72" in data_card
    assert "600" in data_card
    assert "20260716" in data_card
    assert test_hash in data_card
    assert "不得根据 test 失败调参" in data_card
