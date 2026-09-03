"""G2: compare deeper same-query retrieval with historical two-query fusion.

This is an offline, retrospective Oracle-triggered analysis.  It never calls a
model and never modifies serving behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.config import get_settings
from app.external_datasets.wixqa import load_wixqa_questions, verify_wixqa_source
from app.external_datasets.wixqa_retrieval import (
    canonical_json_bytes,
    load_wixqa_flat_index,
    reciprocal_rank_fusion,
    score_wixqa_ranking,
    summarize_wixqa_scores,
)
from app.runtime.ollama_embeddings import OllamaEmbeddingClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-root", type=Path, default=Path(".private/external/wixqa/source"))
    parser.add_argument("--index-root", type=Path, default=Path(".private/external/wixqa/indexes"))
    parser.add_argument("--manifest", type=Path, default=Path("data_manifests/WIXQA_MANIFEST.json"))
    parser.add_argument(
        "--s4-root", type=Path, default=Path(".private/external/wixqa/retrieval_strategy_bakeoff")
    )
    parser.add_argument(
        "--private-root", type=Path, default=Path(".private/adaptive_retrieval_v3/g2")
    )
    parser.add_argument(
        "--public-root", type=Path, default=Path("docs/adaptive_retrieval_v3/evidence")
    )
    args = parser.parse_args(argv)

    verify_wixqa_source(args.source_root, args.manifest)
    questions = load_wixqa_questions("expertwritten", args.source_root)
    index = load_wixqa_flat_index(args.index_root)
    embedding = OllamaEmbeddingClient.from_settings(
        get_settings(), probe_text="V3 G2 probe", endpoint_context="V3 G2"
    )
    s4_runs = [
        _load_s4(args.s4_root / f"wixqa-expertwritten-s4-b762b84-run{number}" / "details.json")
        for number in range(1, 4)
    ]
    by_run = [{case["question_id"]: case for case in run["cases"]} for run in s4_runs]
    oracle = [
        question
        for question in questions
        if float(by_run[0][question.question_id]["rrf_candidate_gold_recall"]) < 1.0
    ]
    if not oracle:
        raise ValueError("oracle subset is empty")
    private_rows, public_rows, summaries = [], [], []
    for run_number, cases in enumerate(by_run, start=1):
        r0, r1, r2 = [], [], []
        run_rows = []
        for question in oracle:
            vector = embedding.embed_batch([question.question])
            ranking = reciprocal_rank_fusion(
                index.bm25_article_ranking(question.question, candidate_k=200),
                index.dense_article_ranking(vector, candidate_k=200),
                rrf_k=index.manifest.rrf_k,
            )
            baseline = ranking[:5]
            deeper = ranking[:10]
            historical = cases[question.question_id]["score"]["ranked_article_ids"]
            r0.append(
                score_wixqa_ranking(
                    question,
                    arm="hybrid_rrf",
                    ranked_article_ids=baseline,
                    latency_ms=0,
                )
            )
            r1.append(
                score_wixqa_ranking(
                    question,
                    arm="hybrid_rrf",
                    ranked_article_ids=deeper[:5],
                    latency_ms=0,
                )
            )
            r2.append(
                score_wixqa_ranking(
                    question,
                    arm="hybrid_rrf",
                    ranked_article_ids=historical,
                    latency_ms=0,
                )
            )
            run_rows.append(
                {
                    "case_sha256": _sha(question.question_id),
                    "r0": baseline,
                    "r1": deeper[:5],
                    "r2": historical,
                }
            )
        summaries.append(
            {
                "run": run_number,
                "R0": _named_summary(r0, "R0"),
                "R1": _named_summary(r1, "R1"),
                "R2": _named_summary(r2, "R2"),
            }
        )
        private_rows.append(run_rows)
        public_rows.append(
            [
                {key: value for key, value in row.items() if key not in {"r0", "r1", "r2"}}
                for row in run_rows
            ]
        )
    payload = {
        "run_id": args.run_id,
        "mode": "RETROSPECTIVE_DEVELOPMENT_ONLY_CONSUMED",
        "oracle_definition": "first-pass hybrid Top-5 does not cover all gold documents",
        "oracle_case_count": len(oracle),
        "arms": {
            "R0": "first-pass original query Top-5",
            "R1": "same original query Top-10 candidate depth, fixed final Top-5",
            "R2": "historical validated two-query S4 fusion, fixed final Top-5",
        },
        "summaries": summaries,
        "claim_boundary": (
            "Oracle-triggered consumed-development retrieval analysis only; not "
            "answer correctness or a default policy claim."
        ),
    }
    public_bytes = canonical_json_bytes({**payload, "rows": public_rows})
    private_bytes = canonical_json_bytes({"rows": private_rows})
    payload["public_rows_sha256"] = _sha_bytes(public_bytes)
    payload["private_rows_sha256"] = _sha_bytes(private_bytes)
    args.private_root.mkdir(parents=True, exist_ok=True)
    target = args.private_root / args.run_id
    if target.exists():
        raise FileExistsError(target)
    target.mkdir()
    (target / "details.json").write_bytes(private_bytes)
    args.public_root.mkdir(parents=True, exist_ok=True)
    out = args.public_root / f"{args.run_id}.json"
    if out.exists():
        raise FileExistsError(out)
    out.write_bytes(canonical_json_bytes(payload))
    print(json.dumps(payload, indent=2))
    return 0


def _load_s4(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _named_summary(scores, arm_name: str) -> dict:
    summary = summarize_wixqa_scores(
        scores,
        cohort="expertwritten",
        arm="hybrid_rrf",
    ).model_dump(mode="json")
    summary["arm"] = arm_name
    return summary


def _sha(value: str) -> str:
    return _sha_bytes(value.encode())


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
