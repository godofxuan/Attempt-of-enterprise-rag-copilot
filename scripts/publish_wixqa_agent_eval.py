from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish aggregate WixQA bounded-Agent missing-arm evidence."
    )
    parser.add_argument("--simulated-run-id", required=True)
    parser.add_argument("--expertwritten-run-id", required=True)
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path(".private/external/wixqa/agent_eval_runs"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/enterprise_eval/evidence/wixqa_agent_public_v1.json"),
    )
    return parser


def build_public_evidence(
    simulated: dict[str, Any],
    expertwritten: dict[str, Any],
    *,
    simulated_private_sha256: str,
    expertwritten_private_sha256: str,
) -> dict[str, Any]:
    runs = {"simulated": simulated, "expertwritten": expertwritten}
    for cohort, run in runs.items():
        if run.get("mode") != "FIXED_MISSING_ARM":
            raise ValueError(f"{cohort} run is not a fixed missing-arm run")
        if run.get("cohort") != cohort or run.get("case_count") != 200:
            raise ValueError(f"{cohort} cohort identity/count mismatch")
        if run.get("claim_boundary", {}).get("answer_correctness") != "NOT_MEASURED":
            raise ValueError("Agent evidence must not claim answer correctness")
        if not re.fullmatch(r"[0-9a-f]{40}", run.get("code_revision", "")):
            raise ValueError("Agent run requires a full Git SHA")
    invariant_fields = (
        "code_revision",
        "dataset_manifest_sha256",
        "index_manifest_sha256",
        "embedding_model",
        "embedding_model_sha256",
        "protocol_sha256",
        "fixed_chunk_candidate_k",
        "agent_budget",
    )
    for field in invariant_fields:
        if simulated[field] != expertwritten[field]:
            raise ValueError(f"Agent paired-run invariant differs: {field}")
    return {
        "schema_version": "wixqa_agent_public_v1",
        "execution_git_sha": simulated["code_revision"],
        "dataset_manifest_sha256": simulated["dataset_manifest_sha256"],
        "index_manifest_sha256": simulated["index_manifest_sha256"],
        "embedding_model": simulated["embedding_model"],
        "embedding_model_sha256": simulated["embedding_model_sha256"],
        "protocol_sha256": simulated["protocol_sha256"],
        "fixed_chunk_candidate_k": simulated["fixed_chunk_candidate_k"],
        "agent_budget": simulated["agent_budget"],
        "cohorts": {
            "simulated": {
                "private_summary_sha256": simulated_private_sha256,
                "question_ids_sha256": simulated["question_ids_sha256"],
                "query_embedding_calls": simulated["query_embedding_calls"],
                "summary": simulated["summary"],
            },
            "expertwritten": {
                "private_summary_sha256": expertwritten_private_sha256,
                "question_ids_sha256": expertwritten["question_ids_sha256"],
                "query_embedding_calls": expertwritten["query_embedding_calls"],
                "summary": expertwritten["summary"],
            },
        },
        "claim_boundary": {
            "answer_correctness": "NOT_MEASURED",
            "citation_precision_recall_gold": "official article IDs",
            "agent_search_evidence": "union of top-5 results per actual search call",
            "agent_promotion_rule": (
                "reject when quality does not improve or latency is at least 3x"
            ),
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    simulated_bytes = (
        args.run_root / args.simulated_run_id / "summary.json"
    ).read_bytes()
    expertwritten_bytes = (
        args.run_root / args.expertwritten_run_id / "summary.json"
    ).read_bytes()
    evidence = build_public_evidence(
        json.loads(simulated_bytes),
        json.loads(expertwritten_bytes),
        simulated_private_sha256=hashlib.sha256(simulated_bytes).hexdigest(),
        expertwritten_private_sha256=hashlib.sha256(expertwritten_bytes).hexdigest(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
