from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


QUALITY_FIELDS = (
    "article_hit_at_1",
    "article_recall_at_1",
    "article_recall_at_3",
    "article_recall_at_5",
    "mrr_at_5",
    "ndcg_at_5",
    "multi_article_completeness_at_5",
)
LATENCY_FIELDS = (
    "latency_ms_mean",
    "latency_ms_p50",
    "latency_ms_p95",
)
PUBLIC_METADATA_FIELDS = (
    "captured_at",
    "embedding_dimension",
    "embedding_model",
    "embedding_model_sha256",
    "faiss",
    "fixed_labels",
    "git_sha",
    "gpu",
    "latency_comparability",
    "logical_cpu_count",
    "numpy",
    "platform",
    "processor",
    "python",
    "requirements_sha256",
    "torch",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify a clean WixQA replay against frozen public evidence."
    )
    parser.add_argument("--historical", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def compare_reproduction(
    historical: dict[str, Any],
    candidate: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    tolerance = float(contract["quality_absolute_tolerance"])
    identity_fields = (
        "dataset_manifest_sha256",
        "dataset_revision",
        "embedding_model",
        "embedding_model_sha256",
        "protocol_sha256",
    )
    expected_candidate = {
        field: historical.get(field) for field in identity_fields
    }
    expected_candidate.update(contract.get("expected_candidate_identity", {}))
    identity_matches = {
        field: candidate.get(field) == expected_candidate.get(field)
        for field in identity_fields
    }
    differences: list[dict[str, Any]] = []
    quality: dict[str, Any] = {}
    latency: dict[str, Any] = {}
    for cohort, expected_cohort in historical["results"].items():
        actual_cohort = candidate["results"].get(cohort, {})
        cohort_quality: dict[str, Any] = {}
        cohort_latency: dict[str, Any] = {}
        for arm, expected_arm in expected_cohort["arms"].items():
            actual_arm = actual_cohort.get("arms", {}).get(arm, {})
            arm_quality: dict[str, Any] = {}
            for metric in QUALITY_FIELDS:
                expected = expected_arm.get(metric)
                actual = actual_arm.get(metric)
                if expected is None or actual is None:
                    matches = expected is actual
                    delta = None
                else:
                    delta = float(actual) - float(expected)
                    matches = abs(delta) <= tolerance
                arm_quality[metric] = {
                    "historical": expected,
                    "candidate": actual,
                    "delta": delta,
                }
                if not matches:
                    differences.append(
                        {
                            "cohort": cohort,
                            "arm": arm,
                            "metric": metric,
                            "historical": expected,
                            "candidate": actual,
                            "delta": delta,
                        }
                    )
            cohort_quality[arm] = arm_quality
            cohort_latency[arm] = {
                field: actual_arm.get(field) for field in LATENCY_FIELDS
            }
        quality[cohort] = cohort_quality
        latency[cohort] = cohort_latency

    metadata = candidate.get("reproduction_metadata", {})
    clean = metadata.get("clean_reproduction", {})
    clean_contract = (
        clean.get("required") is True
        and clean.get("historical_private_artifacts_used_as_input") is False
    )
    verified = (
        all(identity_matches.values())
        and clean_contract
        and not differences
    )
    return {
        "schema_version": "wixqa_clean_reproduction_public_v1",
        "status": "VERIFIED" if verified else "REPRODUCTION_GAP",
        "claim_boundary": {
            "independent_third_party_reproduction": False,
            "wording": "fresh clean-environment reproduction",
            "fixed_public_labels_replayed": True,
            "answer_quality": "NOT_RUN",
        },
        "quality_absolute_tolerance": tolerance,
        "identity_matches": identity_matches,
        "clean_root_contract_satisfied": clean_contract,
        "source_transport_boundary": contract.get("source_transport_boundary"),
        "quality_difference_count": len(differences),
        "quality_differences": differences,
        "quality_observation": quality,
        "candidate_execution_revision": candidate.get("execution_revision"),
        "candidate_index_manifest_sha256": candidate.get("index_manifest_sha256"),
        "candidate_reproduction_metadata": _public_reproduction_metadata(
            metadata
        ),
        "candidate_latency_observation": latency,
    }


def _public_reproduction_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    public = {
        field: metadata.get(field)
        for field in PUBLIC_METADATA_FIELDS
        if field in metadata
    }
    blas = metadata.get("blas", {})
    if isinstance(blas, dict):
        public["blas"] = {
            field: blas.get(field)
            for field in ("name", "version", "openblas configuration")
            if field in blas
        }
    clean = metadata.get("clean_reproduction", {})
    if isinstance(clean, dict):
        public["clean_reproduction"] = {
            "required": clean.get("required"),
            "historical_private_artifacts_used_as_input": clean.get(
                "historical_private_artifacts_used_as_input"
            ),
            "dataset_manifest_sha256": clean.get("dataset_manifest_sha256"),
            "source_root_class": "FRESH_REPOSITORY_LOCAL_IGNORED",
            "index_root_class": "FRESH_REPOSITORY_LOCAL_IGNORED",
            "embedding_cache_class": "FRESH_REPOSITORY_LOCAL_IGNORED",
            "output_root_class": "FRESH_REPOSITORY_LOCAL_IGNORED",
        }
    return public


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    historical = _load(args.historical)
    candidate = _load(args.candidate)
    contract = _load(args.contract)
    payload = compare_reproduction(historical, candidate, contract)
    payload["historical_public_sha256"] = _sha256(args.historical)
    payload["candidate_public_sha256"] = _sha256(args.candidate)
    payload["contract_sha256"] = _sha256(args.contract)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if payload["status"] == "VERIFIED" else 1


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
