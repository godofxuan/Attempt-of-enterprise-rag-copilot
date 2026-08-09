from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


DEFAULT_OUTPUT = Path(
    "docs/rapid_upgrade/evidence/MULTIDOC_FAST_TRACK_PUBLIC.json"
)


def build_public_evidence(run: dict, *, private_summary_sha256: str) -> dict:
    if run.get("mode") != "RETROSPECTIVE_DEVELOPMENT_ONLY_ALREADY_OBSERVED":
        raise ValueError("only the retrospective development run may be published")
    if run.get("promotion_status") != "HOLD_NO_UNCONSUMED_VALIDATION":
        raise ValueError("public evidence must preserve the promotion hold")
    boundary = run.get("claim_boundary", {})
    if boundary.get("resume_quality_claim_allowed") is not False:
        raise ValueError("retrospective evidence cannot authorize a resume claim")
    return {
        "schema_version": "wixqa_multidoc_fast_track_public_v1",
        "mode": run["mode"],
        "execution_git_sha": run["code_revision"],
        "private_summary_sha256": private_summary_sha256,
        "dataset_manifest_sha256": run["dataset_manifest_sha256"],
        "cohort_sha256": run["cohort_sha256"],
        "index_run_id": run["index_run_id"],
        "index_manifest_sha256": run["index_manifest_sha256"],
        "embedding_model": run["embedding_model"],
        "embedding_model_sha256": run["embedding_model_sha256"],
        "agent_budget": run["agent_budget"],
        "same_retriever_across_arms": run["same_retriever_across_arms"],
        "same_guard_acl_across_agent_arms": run[
            "same_guard_acl_across_agent_arms"
        ],
        "retrieval_baseline": run["retrieval_baseline"],
        "arm_summaries": run["arm_summaries"],
        "candidate_vs_current": run["candidate_vs_current"],
        "registered_gates": run["registered_gates"],
        "registered_gate_status": run["registered_gate_status"],
        "promotion_status": run["promotion_status"],
        "precision_tradeoff_status": run["precision_tradeoff_status"],
        "claim_boundary": run["claim_boundary"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish aggregate-only WixQA multi-document fast-track evidence."
    )
    parser.add_argument("--run-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary_bytes = args.run_summary.read_bytes()
    run = json.loads(summary_bytes)
    payload = build_public_evidence(
        run,
        private_summary_sha256=hashlib.sha256(summary_bytes).hexdigest(),
    )
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
