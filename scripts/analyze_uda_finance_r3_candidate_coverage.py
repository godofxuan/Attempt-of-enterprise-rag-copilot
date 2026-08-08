from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from app.config import get_settings
from app.domain.queries import QueryFilters, SearchRequest, UserContext
from app.evaluation.runtime import build_live_runtime
from app.external_datasets.uda_finance_r3 import (
    R3_PREPARED_ROOT,
    R3_PRIVATE_ROOT,
    R3_PROTOCOL_PATH,
    load_uda_finance_r3_cases,
    load_uda_finance_r3_protocol,
    verify_uda_finance_r3_preparation,
)
from app.external_datasets.uda_finance_r3_answer_eval import (
    R3_ANSWER_PROTOCOL_PATH,
    canonical_json_bytes,
    evidence_from_hits,
    extract_numeric_candidates,
    load_answer_protocol,
    uda_answer_match,
)
from scripts.eval_uda_finance_r3_answers import clean_git_revision


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure the frozen R3 numeric-candidate oracle ceiling."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--prepared-root", type=Path, default=R3_PREPARED_ROOT)
    parser.add_argument("--index-root", type=Path, default=R3_PRIVATE_ROOT / "indexes")
    parser.add_argument(
        "--out-root", type=Path, default=R3_PRIVATE_ROOT / "candidate_coverage_runs"
    )
    parser.add_argument("--dataset-protocol", type=Path, default=R3_PROTOCOL_PATH)
    parser.add_argument("--answer-protocol", type=Path, default=R3_ANSWER_PROTOCOL_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _, dataset_protocol_sha = load_uda_finance_r3_protocol(args.dataset_protocol)
    answer_protocol, answer_protocol_sha = load_answer_protocol(args.answer_protocol)
    if answer_protocol["dataset_protocol_sha256"] != dataset_protocol_sha:
        raise ValueError("R3 candidate analysis protocol binding is invalid")
    verify_uda_finance_r3_preparation(prepared_root=args.prepared_root)
    cases, cases_sha = load_uda_finance_r3_cases(args.prepared_root, split="dev")
    code_revision = clean_git_revision()
    settings = get_settings().model_copy(update={"v2_indexes_dir": args.index_root.resolve()})
    runtime = build_live_runtime(settings)
    if runtime.snapshot.version.manifest_sha256 != answer_protocol["index_manifest_sha256"]:
        raise ValueError("R3 candidate analysis loaded the wrong index")

    counts = {
        "case_count": len(cases),
        "page_hit_count": 0,
        "candidate_oracle_count": 0,
        "page_hit_and_candidate_oracle_count": 0,
        "page_hit_without_candidate_oracle_count": 0,
        "page_miss_with_candidate_oracle_count": 0,
        "candidate_limit_reached_count": 0,
    }
    candidate_counts: list[int] = []
    user = UserContext(
        user_id="uda-evaluator",
        tenant_id="uda-external",
        region="global",
        groups=["uda-evaluator"],
    )
    maximum = answer_protocol["typed_contract"]["max_candidates"]
    retrieval = answer_protocol["retrieval"]
    for case in cases:
        response = runtime.pipeline.search(
            SearchRequest(
                request_id=f"r3-oracle-{case.case_id}",
                query=case.question,
                purpose="R3 numeric candidate oracle coverage analysis",
                user=user,
                filters=QueryFilters(
                    policy_ids=[case.gold_doc_id],
                    temporal_scope="all",
                    authoritative_only=False,
                ),
                top_k=retrieval["top_k"],
                candidate_k=retrieval["candidate_k"],
                mode="dense",
                include_parent=retrieval["include_parent"],
                max_chunks_per_doc=retrieval["max_chunks_per_doc"],
                timeout_ms=120_000,
            )
        )
        units, _, pages = evidence_from_hits(response.hits)
        candidates = extract_numeric_candidates(units, max_candidates=maximum)
        candidate_counts.append(len(candidates))
        page_hit = case.page_number in pages
        oracle = any(uda_answer_match(item.value, case.answers) for item in candidates)
        counts["page_hit_count"] += int(page_hit)
        counts["candidate_oracle_count"] += int(oracle)
        counts["page_hit_and_candidate_oracle_count"] += int(page_hit and oracle)
        counts["page_hit_without_candidate_oracle_count"] += int(page_hit and not oracle)
        counts["page_miss_with_candidate_oracle_count"] += int(not page_hit and oracle)
        counts["candidate_limit_reached_count"] += int(len(candidates) == maximum)

    total = len(cases)
    payload = {
        "schema_version": "uda_finance_r3_candidate_coverage_v1",
        "run_id": args.run_id,
        "split": "dev",
        "code_revision": code_revision,
        "dataset_protocol_sha256": dataset_protocol_sha,
        "answer_protocol_sha256": answer_protocol_sha,
        "cases_sha256": cases_sha,
        "index_manifest_sha256": runtime.snapshot.version.manifest_sha256,
        "maximum_candidates": maximum,
        **counts,
        "page_hit_rate": counts["page_hit_count"] / total,
        "candidate_oracle_rate": counts["candidate_oracle_count"] / total,
        "page_hit_candidate_oracle_rate": (
            counts["page_hit_and_candidate_oracle_count"] / counts["page_hit_count"]
            if counts["page_hit_count"]
            else 0.0
        ),
        "candidate_limit_reached_rate": counts["candidate_limit_reached_count"] / total,
        "candidate_count_mean": sum(candidate_counts) / total,
        "candidate_count_min": min(candidate_counts),
        "candidate_count_max": max(candidate_counts),
        "embedding_calls": runtime.counters.embedding_calls,
    }
    run_dir = args.out_root.resolve() / args.run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    content = canonical_json_bytes(payload)
    (run_dir / "manifest.json").write_bytes(content)
    verified = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if verified != payload or hashlib.sha256(content).hexdigest() != hashlib.sha256(
        (run_dir / "manifest.json").read_bytes()
    ).hexdigest():
        raise ValueError("R3 candidate coverage artifact verification failed")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
