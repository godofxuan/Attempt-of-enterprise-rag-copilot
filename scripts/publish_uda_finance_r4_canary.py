from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.external_datasets.uda_finance_page_eval import UdaFinancePageCaseResult
from app.external_datasets.uda_finance_r4_canary import (
    build_r4_canary_evidence,
    canonical_json_bytes,
)
from app.external_datasets.uda_finance_r4_public import R4PublicEvidence


def _load_rows(path: Path) -> list[UdaFinancePageCaseResult]:
    return [
        UdaFinancePageCaseResult.model_validate_json(line)
        for line in path.read_bytes().splitlines()
        if line
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish the aggregate R4 limited-canary review")
    parser.add_argument(
        "--source-public-evidence",
        type=Path,
        default=Path("docs/r4/evidence/uda_finance_r4_public_v1.json"),
    )
    parser.add_argument(
        "--validation-run",
        type=Path,
        default=Path(".private/external/uda_finance/r4/page_eval_runs/r4-validation-v3-c128c7a"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/r4/evidence/uda_finance_r4_canary_review_v1.json"),
    )
    parser.add_argument("--bootstrap-seed", type=int, default=20260902)
    parser.add_argument("--bootstrap-iterations", type=int, default=100_000)
    args = parser.parse_args()

    source_bytes = args.source_public_evidence.read_bytes()
    source = R4PublicEvidence.model_validate_json(source_bytes)
    manifest_bytes = (args.validation_run / "manifest.json").read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != source.validation.source_manifest_sha256:
        raise ValueError("R4 validation manifest does not match the public evidence")
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    arm_hashes = {arm["arm"]: arm["details_sha256"] for arm in manifest["arms"]}
    baseline_path = args.validation_run / "dense_chunk.jsonl"
    candidate_path = args.validation_run / "focused_page_fusion.jsonl"
    observed_hashes = {
        "dense_chunk": hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
        "focused_page_fusion": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
    }
    if observed_hashes != arm_hashes:
        raise ValueError("R4 private detail hashes do not match the validation manifest")

    evidence = build_r4_canary_evidence(
        source_public_evidence=source,
        source_public_evidence_sha256=hashlib.sha256(source_bytes).hexdigest(),
        baseline=_load_rows(baseline_path),
        candidate=_load_rows(candidate_path),
        baseline_details_sha256=observed_hashes["dense_chunk"],
        candidate_details_sha256=observed_hashes["focused_page_fusion"],
        bootstrap_seed=args.bootstrap_seed,
        bootstrap_iterations=args.bootstrap_iterations,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json_bytes(evidence))
    print(args.output)


if __name__ == "__main__":
    main()
