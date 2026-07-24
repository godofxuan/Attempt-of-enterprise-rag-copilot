import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pytest

from app.corpus.artifacts import write_corpus
from app.corpus.generator import (
    generate_document_specs,
    load_facts,
    load_profile,
)
from app.corpus.eval_cases import build_eval_splits
from app.corpus.quality import evaluate_corpus_quality
from app.corpus.schemas import CompanyFacts


ROOT = Path(__file__).resolve().parents[2]
FACTS_V2 = ROOT / "data" / "v2" / "facts" / "company_facts_v2.json"
EXPANDED_PROFILE = ROOT / "data" / "v2" / "config" / "expanded.json"


def run_generator(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.generate_enterprise_corpus",
            *args,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_expanded_profile_reports_real_knowledge_breadth() -> None:
    result = run_generator("--profile", "expanded", "--dry-run")

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["profile_id"] == "expanded"
    assert summary["facts_schema_version"] == "enterprise_facts_v2"
    assert summary["document_count"] == 240
    assert summary["policy_count"] == 20
    assert summary["policy_version_count"] == 40
    assert summary["atomic_fact_count"] == 104
    assert summary["active_fact_count"] == 52
    assert summary["department_count"] == 12
    assert summary["eval_dev_count"] == 48
    assert summary["eval_test_count"] == 56


def test_generator_defaults_to_the_current_expanded_profile() -> None:
    result = run_generator("--dry-run")

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["profile_id"] == "expanded"
    assert summary["document_count"] == 240


def test_expanded_full_artifacts_are_byte_deterministic(
    tmp_path: Path,
) -> None:
    facts = load_facts(FACTS_V2)
    profile = load_profile(EXPANDED_PROFILE)
    first = tmp_path / "first"
    second = tmp_path / "second"

    write_corpus(first, facts, profile)
    write_corpus(second, facts, profile)

    first_files = {
        path.relative_to(first).as_posix(): path.read_bytes()
        for path in first.rglob("*")
        if path.is_file()
    }
    second_files = {
        path.relative_to(second).as_posix(): path.read_bytes()
        for path in second.rglob("*")
        if path.is_file()
    }
    assert first_files == second_files


def test_expanded_profile_makes_every_active_fact_retrievable_from_supporting_content() -> None:
    facts = load_facts(FACTS_V2)
    profile = load_profile(EXPANDED_PROFILE)
    documents = generate_document_specs(facts, profile)
    active_fact_ids = {
        fact.fact_id
        for policy in facts.policies
        for fact in policy.active_version.facts
    }
    supporting_fact_ids: set[str] = set()
    source_types_by_policy: dict[str, set[str]] = defaultdict(set)
    for document in documents:
        if document.metadata.variant != "supporting":
            continue
        supporting_fact_ids.update(document.fact_ids)
        source_types_by_policy[document.metadata.policy_id].add(
            document.source_type
        )

    assert supporting_fact_ids.issuperset(active_fact_ids)
    assert all(
        len(source_types_by_policy[policy.policy_id]) >= 3
        for policy in facts.policies
    )


def test_quality_gate_requires_operational_acl_groups_on_active_versions() -> None:
    facts = load_facts(FACTS_V2)
    payload = facts.model_dump(mode="json")
    visitor_policy = next(
        policy
        for policy in payload["policies"]
        if policy["policy_id"] == "facilities_visitor"
    )
    active_version = next(
        version
        for version in visitor_policy["versions"]
        if version["status"] == "active"
    )
    active_version["acl_groups"] = ["all_employees"]
    drifted_facts = CompanyFacts.model_validate(payload)
    profile = load_profile(EXPANDED_PROFILE)

    report = evaluate_corpus_quality(drifted_facts, profile)

    assert report.checks["all_operational_acl_groups_are_used"] is False
    assert report.metrics["unused_operational_acl_group_count"] == 1


@pytest.mark.parametrize(
    ("profile_id", "document_count"),
    [
        ("expanded", 240),
        ("expanded_benchmark", 2000),
    ],
)
def test_expanded_quality_gate_passes_from_the_public_cli(
    profile_id: str,
    document_count: int,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.eval_corpus_quality",
            "--profile",
            profile_id,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["schema_version"] == "enterprise_corpus_quality_v1"
    assert report["profile_id"] == profile_id
    assert report["release_pass"] is True
    assert report["failures"] == []
    assert report["metrics"]["document_count"] == document_count
    assert report["metrics"]["active_fact_support_coverage"] == 1.0
    assert report["metrics"]["active_fact_eval_coverage"] == 1.0
    assert report["metrics"]["minimum_policy_source_type_count"] >= 3
    assert report["metrics"]["unused_operational_acl_group_count"] == 0
    assert report["metrics"]["eval_task_type_count"] == 6
    assert report["metrics"]["eval_department_count"] == 12
    assert all(report["checks"].values())


def test_expanded_completeness_questions_match_the_required_fact_count() -> None:
    facts = load_facts(FACTS_V2)
    profile = load_profile(EXPANDED_PROFILE)
    documents = generate_document_specs(facts, profile)
    dev_cases, test_cases = build_eval_splits(facts, documents, profile)
    count_words = {1: "一项", 2: "两项", 3: "三项"}

    completeness_cases = [
        case
        for case in [*dev_cases, *test_cases]
        if case.task_type == "completeness"
    ]

    assert completeness_cases
    for case in completeness_cases:
        assert count_words[len(case.required_fact_ids)] in case.question


def test_quality_cli_can_publish_a_machine_readable_report(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "corpus-quality.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.eval_corpus_quality",
            "--profile",
            "expanded",
            "--output",
            str(output_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    stdout_report = json.loads(result.stdout)
    file_report = json.loads(output_path.read_text(encoding="utf-8"))
    assert file_report == stdout_report
    assert output_path.read_bytes().endswith(b"\n")

    refused = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.eval_corpus_quality",
            "--profile",
            "expanded",
            "--output",
            str(output_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    replaced = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.eval_corpus_quality",
            "--profile",
            "expanded",
            "--output",
            str(output_path),
            "--force",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert refused.returncode == 2
    assert "already exists" in refused.stderr
    assert replaced.returncode == 0, replaced.stderr


def test_quality_cli_validates_the_materialized_corpus(
    tmp_path: Path,
) -> None:
    facts = load_facts(FACTS_V2)
    profile = load_profile(EXPANDED_PROFILE)
    corpus_dir = tmp_path / "expanded"
    write_corpus(corpus_dir, facts, profile)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.eval_corpus_quality",
            "--profile",
            "expanded",
            "--corpus-dir",
            str(corpus_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    manifest_bytes = (corpus_dir / "manifest.json").read_bytes()
    assert report["corpus_artifact_validated"] is True
    assert report["corpus_manifest_sha256"] == hashlib.sha256(
        manifest_bytes
    ).hexdigest()
