from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from app.evaluation.external_aggregate_export import load_and_verify_aggregate_reference

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify an aggregate-only RAG evidence reference for external EvalOps."
    )
    parser.add_argument("reference", type=Path)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    reference = load_and_verify_aggregate_reference(
        args.reference,
        repository_root=args.repository_root,
    )
    print(
        json.dumps(
            {
                "artifact_path": reference.artifact_path,
                "case_count": reference.case_count,
                "decision": reference.decision,
                "evidence_id": reference.evidence_id,
                "formal_case_results": reference.formal_case_results,
                "status": "VERIFIED",
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
