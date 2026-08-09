from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


EXPECTED_ARMS = ("bm25", "dense", "hybrid_rrf")
PUBLIC_ARM_NAMES = {
    "bm25": "bm25",
    "dense": "dense",
    "hybrid_rrf": "equal_rrf",
}
SUMMARY_FIELDS = (
    "article_hit_at_1",
    "article_recall_at_1",
    "article_recall_at_3",
    "article_recall_at_5",
    "mrr_at_5",
    "ndcg_at_5",
    "multi_article_completeness_at_5",
    "latency_ms_mean",
    "latency_ms_p50",
    "latency_ms_p95",
)
COHORT_KEYS = {
    "synthetic": "synthetic_development",
    "simulated": "simulated_validation_baseline",
    "expertwritten": "expertwritten_fixed_external",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish complete content-free WixQA retrieval aggregates."
    )
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--synthetic-summary", type=Path, required=True)
    parser.add_argument("--simulated-summary", type=Path, required=True)
    parser.add_argument("--expertwritten-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reproduction-metadata", type=Path)
    return parser


def build_public_evidence(
    *,
    protocol: dict[str, Any],
    runs: dict[str, dict[str, Any]],
    private_summary_hashes: dict[str, str],
    protocol_sha256: str | None = None,
    reproduction_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if tuple(protocol.get("arms", ())) != EXPECTED_ARMS:
        raise ValueError("WixQA protocol arms do not match the publisher contract")
    if set(runs) != set(COHORT_KEYS):
        raise ValueError("WixQA publication requires all three cohorts")

    identities: dict[str, Any] | None = None
    results: dict[str, Any] = {}
    private_bindings: dict[str, Any] = {}
    for cohort in COHORT_KEYS:
        run = runs[cohort]
        if run.get("schema_version") != "wixqa_retrieval_run_v1":
            raise ValueError(f"{cohort} has an unsupported run schema")
        if run.get("cohort") != cohort:
            raise ValueError(f"{cohort} summary has the wrong cohort")
        expected = protocol["cohorts"][cohort]
        if run.get("case_count") != expected["case_count"]:
            raise ValueError(f"{cohort} case count does not match the protocol")
        if run.get("question_ids_sha256") != expected["question_ids_sha256"]:
            raise ValueError(f"{cohort} question IDs do not match the protocol")
        if run.get("dataset_manifest_sha256") != protocol["dataset_manifest_sha256"]:
            raise ValueError(f"{cohort} dataset manifest does not match the protocol")
        summaries = run.get("summaries")
        if not isinstance(summaries, list):
            raise ValueError(f"{cohort} summaries are missing")
        by_arm = {item.get("arm"): item for item in summaries}
        if set(by_arm) != set(EXPECTED_ARMS) or len(summaries) != len(EXPECTED_ARMS):
            raise ValueError(f"{cohort} aggregate arms do not match the protocol")

        current_identity = {
            "dataset_manifest_sha256": run["dataset_manifest_sha256"],
            "index_manifest_sha256": run["index_manifest_sha256"],
            "embedding_model": run["embedding_model"],
            "embedding_model_sha256": run["embedding_model_sha256"],
            "execution_revision": run["code_revision"],
        }
        if identities is None:
            identities = current_identity
        elif identities != current_identity:
            raise ValueError("WixQA cohort identities are inconsistent")

        public_arms: dict[str, Any] = {}
        for arm in EXPECTED_ARMS:
            summary = by_arm[arm]
            missing = [field for field in SUMMARY_FIELDS if field not in summary]
            if missing:
                raise ValueError(f"{cohort}/{arm} is missing metrics: {missing}")
            public_arms[PUBLIC_ARM_NAMES[arm]] = {
                field: summary[field] for field in SUMMARY_FIELDS
            }
        results[COHORT_KEYS[cohort]] = {
            "case_count": run["case_count"],
            "consumption": run["consumption"],
            "question_ids_sha256": run["question_ids_sha256"],
            "multi_article_case_count": by_arm["bm25"][
                "multi_article_case_count"
            ],
            "arms": public_arms,
        }
        private_bindings[cohort] = {
            "summary_sha256": private_summary_hashes[cohort],
            "details_sha256": run["details_sha256"],
        }

    assert identities is not None
    payload = {
        "schema_version": "wixqa_retrieval_baseline_public_v2",
        "protocol_arms": list(EXPECTED_ARMS),
        "public_arm_names": PUBLIC_ARM_NAMES,
        "protocol_sha256": protocol_sha256 or _canonical_sha256(protocol),
        "dataset_revision": protocol["dataset_revision"],
        **identities,
        "claims": {
            "retrieval_champion": "dense",
            "blind_holdout": False,
            "answer_correctness": "NOT_RUN",
            "citation_quality": "NOT_RUN",
            "agent_quality": "MEASURED_SEPARATELY_REJECTED",
        },
        "latency_boundary": {
            "historical_machine_identity": "NOT_CAPTURED_IN_V1_PRIVATE_SUMMARIES",
            "accuracy_reproduction_requirement": "EXACT_WITH_FROZEN_IDENTITIES",
            "latency_reproduction_requirement": "REPORT_WITH_MACHINE_METADATA",
        },
        "private_run_bindings": private_bindings,
        "results": results,
    }
    if reproduction_metadata is not None:
        payload["reproduction_metadata"] = reproduction_metadata
    return payload


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protocol = _load_json(args.protocol)
    paths = {
        "synthetic": args.synthetic_summary,
        "simulated": args.simulated_summary,
        "expertwritten": args.expertwritten_summary,
    }
    runs = {cohort: _load_json(path) for cohort, path in paths.items()}
    hashes = {
        cohort: hashlib.sha256(path.read_bytes()).hexdigest()
        for cohort, path in paths.items()
    }
    reproduction = (
        _load_json(args.reproduction_metadata)
        if args.reproduction_metadata is not None
        else None
    )
    payload = build_public_evidence(
        protocol=protocol,
        runs=runs,
        private_summary_hashes=hashes,
        protocol_sha256=hashlib.sha256(args.protocol.read_bytes()).hexdigest(),
        reproduction_metadata=reproduction,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


def _canonical_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
