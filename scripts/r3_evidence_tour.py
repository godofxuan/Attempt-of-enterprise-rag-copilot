from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_FILES = {
    "page_validation": ROOT
    / "docs/r3/evidence/uda_finance_r3_page_validation_v1.json",
    "answer_development": ROOT
    / "docs/r3/evidence/uda_finance_r3_answer_dev_v1.json",
    "security_stress": ROOT
    / "docs/r3/evidence/garak_latent_report_expanded_v1.json",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Show the offline R3 evidence tour.")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return parser


def load_evidence_tour() -> dict:
    payloads = {}
    hashes = {}
    for name, path in EVIDENCE_FILES.items():
        content = path.read_bytes()
        payloads[name] = json.loads(content.decode("utf-8"))
        hashes[name] = hashlib.sha256(content).hexdigest()
    page = payloads["page_validation"]
    answer = payloads["answer_development"]
    security = payloads["security_stress"]
    if page["decision"] != "VALIDATION_REJECTED_FIXED_TEST_UNTOUCHED":
        raise ValueError("R3 page decision is not the frozen rejection")
    if answer["decision"] != (
        "TYPED_CANDIDATE_REJECTED_ON_DEVELOPMENT_NO_VALIDATION_OR_TEST"
    ):
        raise ValueError("R3 answer decision is not the frozen rejection")
    if security["guard_on"]["attack_success_count"] != 0:
        raise ValueError("R3 security evidence does not match the published result")
    arms = {item["strategy"]: item for item in answer["arms"]}
    return {
        "schema_version": "r3_offline_evidence_tour_v1",
        "evidence_sha256": hashes,
        "page_retrieval": {
            "validation_baseline_hit_at_5": page["baseline"]["page_hit_at_5"],
            "validation_candidate_hit_at_5": page["candidate"]["page_hit_at_5"],
            "validation_baseline_ndcg_at_5": page["baseline"]["page_ndcg_at_5"],
            "validation_candidate_ndcg_at_5": page["candidate"]["page_ndcg_at_5"],
            "decision": page["decision"],
        },
        "answer": {
            "direct_numeric_accuracy": arms["direct"]["numeric_accuracy"],
            "typed_numeric_accuracy": arms["typed_candidate"]["numeric_accuracy"],
            "typed_candidate_oracle_count": answer["candidate_oracle_analysis"][
                "candidate_oracle_count"
            ],
            "case_count": answer["case_count"],
            "decision": answer["decision"],
        },
        "security_stress": {
            "attack_case_count": security["fixture"]["attack_case_count"],
            "guard_off_attack_success_count": security["guard_off"][
                "attack_success_count"
            ],
            "guard_on_attack_success_count": security["guard_on"][
                "attack_success_count"
            ],
            "guard_off_context_exposure_count": security["guard_off"][
                "context_exposure_count"
            ],
            "guard_on_context_exposure_count": security["guard_on"][
                "context_exposure_count"
            ],
            "benign_case_count": security["fixture"]["benign_case_count"],
            "guard_on_benign_false_positive_count": security["guard_on"][
                "benign_false_positive_count"
            ],
            "guard_latency_ms_mean": security["guard_on"][
                "guard_latency_ms_mean"
            ],
            "claim_tier": "CURRENT_IMPLEMENTATION_STRESS_NOT_BLIND_HOLDOUT",
        },
        "human_review": {
            "status": "NOT_RUN",
            "reason": "requires two independent human reviewers",
        },
    }


def render_markdown(tour: dict) -> str:
    page = tour["page_retrieval"]
    answer = tour["answer"]
    security = tour["security_stress"]
    return "\n".join(
        [
            "# R3 Offline Evidence Tour",
            "",
            "## Page retrieval",
            (
                f"Validation Hit@5 {page['validation_baseline_hit_at_5']:.2%} -> "
                f"{page['validation_candidate_hit_at_5']:.2%}; nDCG@5 "
                f"{page['validation_baseline_ndcg_at_5']:.2%} -> "
                f"{page['validation_candidate_ndcg_at_5']:.2%}."
            ),
            f"Decision: `{page['decision']}`.",
            "",
            "## Answer and citation",
            (
                f"Direct numeric accuracy {answer['direct_numeric_accuracy']:.2%}; "
                f"typed candidate {answer['typed_numeric_accuracy']:.2%}. "
                f"Candidate oracle coverage {answer['typed_candidate_oracle_count']}/"
                f"{answer['case_count']}."
            ),
            f"Decision: `{answer['decision']}`.",
            "",
            "## Retrieved-content security stress",
            (
                f"ASR {security['guard_off_attack_success_count']}/"
                f"{security['attack_case_count']} -> "
                f"{security['guard_on_attack_success_count']}/"
                f"{security['attack_case_count']}; context exposure "
                f"{security['guard_off_context_exposure_count']}/"
                f"{security['attack_case_count']} -> "
                f"{security['guard_on_context_exposure_count']}/"
                f"{security['attack_case_count']}."
            ),
            (
                f"Benign false positives {security['guard_on_benign_false_positive_count']}/"
                f"{security['benign_case_count']}; mean Guard scan "
                f"{security['guard_latency_ms_mean']:.2f} ms."
            ),
            "Claim tier: current implementation stress, not a blind holdout.",
            "",
            "## Human review",
            "Not run: two independent reviewers are still required.",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    tour = load_evidence_tour()
    if args.format == "json":
        print(json.dumps(tour, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(tour))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
