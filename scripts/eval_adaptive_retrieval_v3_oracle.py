"""F1/F2: corrected Oracle comparison from frozen G1 first-pass evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from app.evaluation.adaptive_retrieval_v3 import select_oracle_case_ids
from app.external_datasets.wixqa import load_wixqa_questions, verify_wixqa_source
from app.external_datasets.wixqa_retrieval import (
    canonical_json_bytes,
    score_wixqa_ranking,
    summarize_wixqa_scores,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-root", type=Path, default=Path(".private/external/wixqa/source"))
    parser.add_argument("--manifest", type=Path, default=Path("data_manifests/WIXQA_MANIFEST.json"))
    parser.add_argument(
        "--g1-private",
        type=Path,
        default=Path(
            ".private/adaptive_retrieval_v3/g1/g1-assessor-run1-e304212/private_details.json"
        ),
    )
    parser.add_argument(
        "--s4-root", type=Path, default=Path(".private/external/wixqa/retrieval_strategy_bakeoff")
    )
    parser.add_argument(
        "--private-root", type=Path, default=Path(".private/adaptive_retrieval_v3/g2")
    )
    parser.add_argument(
        "--public-root", type=Path, default=Path("docs/adaptive_retrieval_v3/evidence")
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    verify_wixqa_source(args.source_root, args.manifest)
    first_pass = _load(args.g1_private)["rows"]
    oracle_ids = select_oracle_case_ids(first_pass)
    questions = {
        item.question_id: item for item in load_wixqa_questions("expertwritten", args.source_root)
    }
    first_by_id = {item["question_id"]: item for item in first_pass}
    if set(first_by_id) != set(questions):
        raise ValueError("G1 first-pass evidence does not cover the fixed cohort")
    if not oracle_ids:
        raise ValueError("corrected Oracle subset is empty")

    summaries, private_runs = [], []
    for run_number in range(1, 4):
        s4 = _load(
            args.s4_root / f"wixqa-expertwritten-s4-b762b84-run{run_number}" / "details.json"
        )
        s4_by_id = {item["question_id"]: item for item in s4["cases"]}
        baseline_scores, corrective_scores, rows = [], [], []
        recovery = {"full_recovery": 0, "partial_improvement": 0, "no_change": 0, "harm": 0}
        accepted = 0
        for question_id in oracle_ids:
            question = questions[question_id]
            baseline = first_by_id[question_id]["post_guard_document_ids"]
            corrective = s4_by_id[question_id]["score"]["ranked_article_ids"]
            baseline_scores.append(_score(question, baseline))
            corrective_scores.append(_score(question, corrective))
            before, after = (
                _coverage(question.article_ids, baseline),
                _coverage(question.article_ids, corrective),
            )
            _record_recovery(recovery, before, after)
            accepted += int(s4_by_id[question_id]["query_expansion"]["status"] == "accepted")
            rows.append(
                {
                    "case_sha256": _sha(question_id),
                    "baseline_ids": baseline,
                    "corrective_ids": corrective,
                    "before_coverage": before,
                    "after_coverage": after,
                }
            )
        summaries.append(
            {
                "historical_s4_run": run_number,
                "R0_BASELINE": _summary(baseline_scores, "R0_BASELINE"),
                "R2_MULTI_QUERY_CORRECTIVE": _summary(
                    corrective_scores, "R2_MULTI_QUERY_CORRECTIVE"
                ),
                "recovery": recovery,
                "accepted_expansions": accepted,
                "fallback_expansions": len(oracle_ids) - accepted,
                "rewrite_calls": len(oracle_ids),
                "search_queries": len(oracle_ids) + accepted * 2,
            }
        )
        private_runs.append(rows)

    cohort = {
        "schema_version": "adaptive_retrieval_v3_corrected_oracle_v1",
        "git_sha": _git_sha(),
        "dataset_manifest_sha256": _sha_file(args.manifest),
        "g1_first_pass_private_sha256": _sha_file(args.g1_private),
        "question_set_sha256": _sha_bytes(canonical_json_bytes(list(oracle_ids))),
        "baseline_complete_case_count": len(first_pass) - len(oracle_ids),
        "baseline_incomplete_case_count": len(oracle_ids),
        "selection_rule": "not set(gold_document_ids).issubset(set(post_guard_document_ids))",
        "selection_independent_of": ["S4 fused Top-5", "rewrite output", "corrective outcome"],
    }
    result = {
        "schema_version": "adaptive_retrieval_v3_corrected_g2_v1",
        "run_id": args.run_id,
        "mode": "RETROSPECTIVE_DEVELOPMENT_ONLY_CONSUMED",
        "oracle_cohort": cohort,
        "arms": {
            "R0_BASELINE": "frozen G1 first-pass post-Guard Top-5 evidence",
            "R2_MULTI_QUERY_CORRECTIVE": (
                "historical frozen S4 original plus up to two validated alternatives, "
                "deterministic fusion, fixed Top-5"
            ),
        },
        "summaries": summaries,
        "claim_boundary": (
            "Corrected Oracle retrieval analysis on consumed development data only; "
            "not answer correctness or a production default claim."
        ),
    }
    private_bytes = canonical_json_bytes({"runs": private_runs})
    result["private_rows_sha256"] = _sha_bytes(private_bytes)
    _write_outputs(args, cohort, result, private_bytes)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


def _score(question, ranking):
    return score_wixqa_ranking(question, arm="hybrid_rrf", ranked_article_ids=ranking, latency_ms=0)


def _summary(scores, arm_name: str) -> dict:
    summary = summarize_wixqa_scores(scores, cohort="expertwritten", arm="hybrid_rrf").model_dump(
        mode="json"
    )
    summary["arm"] = arm_name
    return summary


def _record_recovery(recovery: dict[str, int], before: float, after: float) -> None:
    if after == 1.0 and before < 1.0:
        recovery["full_recovery"] += 1
    elif after > before:
        recovery["partial_improvement"] += 1
    elif after < before:
        recovery["harm"] += 1
    else:
        recovery["no_change"] += 1


def _coverage(gold, observed) -> float:
    return len(set(gold) & set(observed)) / len(set(gold))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(value: str) -> str:
    return _sha_bytes(value.encode())


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def _write_outputs(args, cohort: dict, result: dict, private_bytes: bytes) -> None:
    private_target = args.private_root / args.run_id
    if private_target.exists():
        raise FileExistsError(private_target)
    private_target.mkdir(parents=True)
    (private_target / "details.json").write_bytes(private_bytes)
    args.public_root.mkdir(parents=True, exist_ok=True)
    for name, payload in (
        ("g2-corrected-oracle-cohort-v1.json", cohort),
        (f"{args.run_id}.json", result),
    ):
        target = args.public_root / name
        if target.exists():
            raise FileExistsError(target)
        target.write_bytes(canonical_json_bytes(payload))


if __name__ == "__main__":
    raise SystemExit(main())
