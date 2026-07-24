from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


CONTENT_FILES = (
    "README.md",
    "manifest.json",
    "index_manifest.json",
    "quality.json",
    "retrieval_dev_summary.json",
    "retrieval_test_summary.json",
    "verify.py",
)
PACKAGE_FILES = frozenset((*CONTENT_FILES, "checksums.sha256"))
CHECKSUM_PATTERN = re.compile(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
GIT_OBJECT_PATTERN = re.compile(r"[0-9a-f]{40}")

EXPECTED_EVIDENCE_MANIFEST: dict[str, Any] = {
    "corpus": {
        "document_count": 240,
        "generator_version": "2.0.0",
        "manifest_sha256": (
            "5d96338e4d637c207c381323fc6919f575983992e553a06f548a7e7e0fc24e57"
        ),
    },
    "evaluation": {
        "dev": {
            "artifact": "retrieval_dev_summary.json",
            "case_count": 48,
            "dataset_path": "data/v2/generated/expanded/eval/dev.json",
            "dataset_sha256": (
                "aabcd796f76001b2b3b8a3e37d5f8f388a7aaf069a1330c0ac0779da35db5cab"
            ),
            "run_id": "corpus_expanded_fullfact_dev_live_20260724",
            "summary_sha256": (
                "fa089ee94e85e0dbb986718d2c9809b6f1920f72ac1c7d818d40ebd26710f846"
            ),
        },
        "test": {
            "artifact": "retrieval_test_summary.json",
            "case_count": 56,
            "dataset_path": "data/v2/generated/expanded/eval/test.json",
            "dataset_sha256": (
                "d4c516fcaa9e8dac6474bde69d13f2e95bf9ae4562e91b3fd8d5e90f8ef18c76"
            ),
            "run_id": "corpus_expanded_fullfact_test_live_20260724",
            "summary_sha256": (
                "db817c18d8a8d12b60698b38acaffcb215b392989db3958066b7def590b439aa"
            ),
        },
    },
    "facts": {
        "canonical_sha256": (
            "761fd6d2400721bcd669bc3417b4c1d3322d4f179cd584737044805e914c34b1"
        ),
        "file_sha256": (
            "5d72a8310f19be2b94f2d55b065c4ae4f68394e8091839f80ed95834eadec474"
        ),
        "path": "data/v2/facts/company_facts_v2.json",
        "schema_version": "enterprise_facts_v2",
    },
    "index": {
        "artifact": "index_manifest.json",
        "canonical_document_count": 216,
        "chunker_mode": "fixed",
        "corpus_manifest_sha256": (
            "5d96338e4d637c207c381323fc6919f575983992e553a06f548a7e7e0fc24e57"
        ),
        "embedding_dimension": 1024,
        "embedding_model": "bge-m3",
        "manifest_sha256": (
            "69b9fb7d3008467f65fb2920a621e9812cdb59c4919834819333e0e33b866507"
        ),
        "run_id": "20260724T024653Z_expanded_bge_m3_fixed",
        "source_document_count": 240,
    },
    "producer": "enterprise_agentic_rag_v2",
    "profile": {
        "canonical_sha256": (
            "8bfe9da8f5dd063f971ef55ddcc9fbc8fb669c958f113df6fe91fc7311ad2787"
        ),
        "document_count": 240,
        "file_sha256": (
            "a5a1842245dd3ef234a0b63caf34ecbb17624ecc5783680fc8d74de76af01d3d"
        ),
        "id": "expanded",
        "path": "data/v2/config/expanded.json",
        "seed": 20260724,
    },
    "profile_id": "expanded",
    "quality": {
        "artifact": "quality.json",
        "corpus_artifact_validated": True,
        "corpus_manifest_sha256": (
            "5d96338e4d637c207c381323fc6919f575983992e553a06f548a7e7e0fc24e57"
        ),
        "sha256": (
            "01ab592adb534b5f958017bf50e8ea9dcc5bd54cdec08ba182f1ff6caa4f75f9"
        ),
    },
    "run_provenance": {
        "captured_git_dirty": True,
        "captured_git_head": "e657beaf7d184409b2d7574c974733cbd7233f4e",
        "implementation_snapshot_relation": "post_run_reviewed_snapshot",
    },
    "schema_version": "enterprise_corpus_expansion_public_evidence_v1",
    "source_git_commit": "184913e5e504b150d3959ae541cc808544ac379e",
}

EXPECTED_QUALITY_CHECKS = frozenset(
    {
        "active_fact_count_at_least_50",
        "all_document_formats_are_present",
        "all_document_source_types_are_present",
        "all_operational_acl_groups_are_used",
        "atomic_fact_count_at_least_100",
        "department_count_at_least_12",
        "document_count_matches_profile",
        "eval_case_ids_are_unique",
        "eval_counts_match_profile",
        "eval_covers_all_departments",
        "eval_covers_all_task_types",
        "eval_splits_are_disjoint",
        "every_active_fact_has_supporting_content",
        "every_active_fact_is_evaluated",
        "every_policy_has_three_source_types",
        "fact_questions_are_unique",
        "fact_statements_are_unique",
        "facts_schema_is_v2",
        "policy_count_at_least_20",
        "policy_version_count_at_least_40",
    }
)

EXPECTED_QUALITY_METRICS: dict[str, int | float] = {
    "acl_group_count": 15,
    "active_fact_count": 52,
    "active_fact_eval_coverage": 1.0,
    "active_fact_support_coverage": 1.0,
    "atomic_fact_count": 104,
    "authoritative_document_count": 40,
    "department_count": 12,
    "document_count": 240,
    "document_format_count": 5,
    "document_source_type_count": 6,
    "eval_case_count": 104,
    "eval_department_count": 12,
    "eval_dev_count": 48,
    "eval_task_type_count": 6,
    "eval_test_count": 56,
    "fixture_user_count": 15,
    "minimum_policy_source_type_count": 3,
    "policy_count": 20,
    "policy_version_count": 40,
    "supporting_document_count": 133,
    "unused_operational_acl_group_count": 0,
}

INDEX_KEYS = frozenset(
    {
        "artifacts",
        "bm25",
        "canonical_document_count",
        "chunk_count",
        "chunker_config",
        "corpus_manifest_hash",
        "duplicate_count",
        "duration_ms",
        "embedding",
        "faiss",
        "finished_at",
        "index_version",
        "indexed_chunk_count",
        "parent_chunk_count",
        "parser_versions",
        "producer",
        "profile_id",
        "run_id",
        "schema_version",
        "source_document_count",
        "started_at",
        "table_chunk_count",
    }
)

RETRIEVAL_SUMMARY_KEYS = frozenset(
    {
        "case_count",
        "config",
        "mode",
        "producer",
        "run_id",
        "schema_version",
        "security_probes",
        "split",
        "suite",
        "summary",
    }
)


def _require_exact_keys(
    payload: dict[str, Any],
    expected: frozenset[str] | set[str],
    label: str,
) -> None:
    actual = set(payload)
    if actual != set(expected):
        missing = sorted(set(expected) - actual)
        unexpected = sorted(actual - set(expected))
        raise ValueError(
            f"{label} fields differ: missing={missing}, unexpected={unexpected}"
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(package: Path, name: str) -> dict[str, Any]:
    payload = json.loads((package / name).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{name} must contain a JSON object")
    return payload


def _verify_checksums(package: Path) -> None:
    actual_files = {
        item.name
        for item in package.iterdir()
        if item.is_file()
    }
    if actual_files != PACKAGE_FILES:
        raise ValueError(
            "unexpected package files: "
            f"expected {sorted(PACKAGE_FILES)}, got {sorted(actual_files)}"
        )

    rows = (package / "checksums.sha256").read_text(
        encoding="utf-8"
    ).splitlines()
    declared: dict[str, str] = {}
    for row in rows:
        match = CHECKSUM_PATTERN.fullmatch(row)
        if match is None:
            raise ValueError(f"invalid checksum row: {row!r}")
        digest, name = match.groups()
        if name in declared:
            raise ValueError(f"duplicate checksum entry: {name}")
        declared[name] = digest
    if set(declared) != set(CONTENT_FILES):
        raise ValueError("checksum file set does not match package contract")

    for name in CONTENT_FILES:
        actual = _sha256(package / name)
        if actual != declared[name]:
            raise ValueError(
                f"checksum mismatch for {name}: "
                f"expected {declared[name]}, got {actual}"
            )


def _retrieval_metric(summary: dict[str, Any], name: str) -> float:
    return float(
        summary["summary"]["layers"]["retrieval"]["metrics"][name]["mean"]
    )


def _verify_evidence_manifest(manifest: dict[str, Any]) -> None:
    if manifest != EXPECTED_EVIDENCE_MANIFEST:
        raise ValueError(
            "evidence manifest does not match the frozen release contract"
        )
    for section in ("facts", "profile", "corpus", "index", "quality"):
        for name, value in manifest[section].items():
            if name.endswith("sha256") and SHA256_PATTERN.fullmatch(value) is None:
                raise ValueError(f"invalid SHA-256 in {section}.{name}")
    for split in ("dev", "test"):
        for name, value in manifest["evaluation"][split].items():
            if name.endswith("sha256") and SHA256_PATTERN.fullmatch(value) is None:
                raise ValueError(
                    f"invalid SHA-256 in evaluation.{split}.{name}"
                )
    if GIT_OBJECT_PATTERN.fullmatch(manifest["source_git_commit"]) is None:
        raise ValueError("source_git_commit is not a full Git object id")


def _verify_file_bindings(
    package: Path,
    manifest: dict[str, Any],
) -> None:
    bindings = (
        (manifest["quality"]["artifact"], manifest["quality"]["sha256"]),
        (manifest["index"]["artifact"], manifest["index"]["manifest_sha256"]),
        (
            manifest["evaluation"]["dev"]["artifact"],
            manifest["evaluation"]["dev"]["summary_sha256"],
        ),
        (
            manifest["evaluation"]["test"]["artifact"],
            manifest["evaluation"]["test"]["summary_sha256"],
        ),
    )
    for name, expected in bindings:
        actual = _sha256(package / name)
        if actual != expected:
            raise ValueError(
                f"evidence binding mismatch for {name}: "
                f"expected {expected}, got {actual}"
            )


def _verify_quality(quality: dict[str, Any]) -> None:
    _require_exact_keys(
        quality,
        {
            "checks",
            "corpus_artifact_validated",
            "corpus_manifest_sha256",
            "facts_schema_version",
            "failures",
            "metrics",
            "profile_id",
            "release_pass",
            "schema_version",
        },
        "quality",
    )
    if quality.get("schema_version") != "enterprise_corpus_quality_v1":
        raise ValueError("unexpected quality schema")
    if quality.get("profile_id") != "expanded":
        raise ValueError("quality profile is not expanded")
    if quality.get("facts_schema_version") != "enterprise_facts_v2":
        raise ValueError("quality report is bound to the wrong facts schema")
    if quality.get("release_pass") is not True:
        raise ValueError("corpus quality gate did not pass")
    if quality.get("failures") != []:
        raise ValueError("corpus quality report contains failures")
    if quality.get("corpus_artifact_validated") is not True:
        raise ValueError("materialized corpus was not validated")
    if quality.get("corpus_manifest_sha256") != (
        EXPECTED_EVIDENCE_MANIFEST["corpus"]["manifest_sha256"]
    ):
        raise ValueError("quality report is bound to the wrong corpus")
    checks = quality.get("checks", {})
    _require_exact_keys(checks, EXPECTED_QUALITY_CHECKS, "quality.checks")
    if not all(value is True for value in checks.values()):
        raise ValueError("one or more corpus quality checks failed")
    metrics = quality.get("metrics", {})
    _require_exact_keys(
        metrics,
        set(EXPECTED_QUALITY_METRICS),
        "quality.metrics",
    )
    for name, expected in EXPECTED_QUALITY_METRICS.items():
        if metrics.get(name) != expected:
            raise ValueError(
                f"unexpected quality metric {name}: {metrics.get(name)!r}"
            )
def _verify_index(manifest: dict[str, Any]) -> None:
    _require_exact_keys(manifest, INDEX_KEYS, "index manifest")
    expected = {
        "schema_version": "enterprise_index_manifest_v1",
        "profile_id": "expanded",
        "source_document_count": 240,
        "canonical_document_count": 216,
        "duplicate_count": 24,
        "chunk_count": 216,
        "indexed_chunk_count": 216,
    }
    for name, value in expected.items():
        if manifest.get(name) != value:
            raise ValueError(
                f"unexpected index manifest field {name}: "
                f"{manifest.get(name)!r}"
            )
    embedding = manifest.get("embedding", {})
    if embedding.get("model") != "bge-m3":
        raise ValueError("index evidence was not built with bge-m3")
    if embedding.get("dimension") != 1024:
        raise ValueError("unexpected embedding dimension")
    if manifest.get("chunker_config", {}).get("mode") != "fixed":
        raise ValueError("unexpected chunker mode")
    if manifest.get("corpus_manifest_hash") != (
        EXPECTED_EVIDENCE_MANIFEST["corpus"]["manifest_sha256"]
    ):
        raise ValueError("index manifest is bound to the wrong corpus")
    if manifest.get("run_id") != EXPECTED_EVIDENCE_MANIFEST["index"]["run_id"]:
        raise ValueError("index manifest declares the wrong run")


def _verify_retrieval(
    summary: dict[str, Any],
    *,
    split: str,
    case_count: int,
) -> None:
    _require_exact_keys(
        summary,
        RETRIEVAL_SUMMARY_KEYS,
        f"{split} retrieval summary",
    )
    if summary.get("schema_version") != "enterprise_evaluation_result_v1":
        raise ValueError(f"{split} evidence has the wrong schema")
    if summary.get("producer") != "enterprise_agentic_rag_v2":
        raise ValueError(f"{split} evidence has the wrong producer")
    expected_run = EXPECTED_EVIDENCE_MANIFEST["evaluation"][split]["run_id"]
    if summary.get("run_id") != expected_run:
        raise ValueError(f"{split} evidence declares the wrong run")
    if summary.get("mode") != "live":
        raise ValueError(f"{split} evidence is not a live run")
    if summary.get("split") != split:
        raise ValueError(f"{split} evidence declares the wrong split")
    if summary.get("suite") != "retrieval":
        raise ValueError(f"{split} evidence is not a retrieval suite")
    if summary.get("case_count") != case_count:
        raise ValueError(f"{split} evidence has the wrong case count")
    aggregate = summary.get("summary", {})
    if aggregate.get("failed_case_count") != 0:
        raise ValueError(f"{split} retrieval contains failed cases")
    if aggregate.get("overall_case_pass", {}).get("rate") != 1.0:
        raise ValueError(f"{split} overall pass rate is not 1.0")
    if _retrieval_metric(summary, "acl_leakage_count") != 0.0:
        raise ValueError(f"{split} retrieval contains ACL leakage")
    if _retrieval_metric(summary, "hit@1") != 1.0:
        raise ValueError(f"{split} hit@1 is below the release threshold")
    if _retrieval_metric(summary, "document_recall@3") != 1.0:
        raise ValueError(
            f"{split} document_recall@3 is below the release threshold"
        )


def verify(package: Path) -> dict[str, object]:
    package = package.resolve()
    if not package.is_dir():
        raise ValueError(f"package directory not found: {package}")
    _verify_checksums(package)
    manifest = _load_json(package, "manifest.json")
    _verify_evidence_manifest(manifest)
    _verify_file_bindings(package, manifest)
    quality = _load_json(package, "quality.json")
    index = _load_json(package, "index_manifest.json")
    _verify_quality(quality)
    _verify_index(index)
    _verify_retrieval(
        _load_json(package, "retrieval_dev_summary.json"),
        split="dev",
        case_count=48,
    )
    _verify_retrieval(
        _load_json(package, "retrieval_test_summary.json"),
        split="test",
        case_count=56,
    )
    return {"profile_id": "expanded", "verified": True}


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Verify the public expanded-corpus evidence package.",
    )
    parser.add_argument(
        "--package",
        type=Path,
        default=Path(__file__).resolve().parent,
    )
    args = parser.parse_args(argv)
    try:
        report = verify(args.package)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
