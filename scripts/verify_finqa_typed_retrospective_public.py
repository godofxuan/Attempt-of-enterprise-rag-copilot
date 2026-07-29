try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from app.external_datasets.finqa_typed_retrospective import (
    load_protocol,
    load_public_evidence,
    verify_public_evidence_contract,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify aggregate FinQA typed retrospective evidence and its "
            "historical Git source snapshot."
        )
    )
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=REPOSITORY_ROOT,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protocol = load_protocol(args.protocol)
    evidence = load_public_evidence(args.evidence)
    verify_public_evidence_contract(
        evidence=evidence,
        protocol=protocol,
    )
    _verify_git_source_snapshot(
        repository_root=args.repository_root,
        revision=evidence.execution_code_revision,
        expected_file_sha256=protocol.source_file_sha256,
    )
    print(
        json.dumps(
            {
                "status": "VERIFIED",
                "claim_label": evidence.claim_label,
                "run_id": evidence.run_id,
                "execution_code_revision": evidence.execution_code_revision,
                "source_file_count": len(protocol.source_file_sha256),
                "selected_case_count": evidence.selected_case_count,
                "private_manifest_sha256": (
                    evidence.private_manifest_sha256
                ),
                "private_details_sha256": evidence.private_details_sha256,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _verify_git_source_snapshot(
    *,
    repository_root: Path,
    revision: str,
    expected_file_sha256: dict[str, str],
) -> None:
    root = Path(repository_root).resolve()
    resolved_revision = subprocess.run(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    if resolved_revision != revision:
        raise ValueError("public evidence Git revision is not exact")
    for relative_path, expected_sha256 in expected_file_sha256.items():
        completed = subprocess.run(
            ["git", "show", f"{revision}:{relative_path}"],
            cwd=root,
            check=True,
            capture_output=True,
        )
        actual_sha256 = hashlib.sha256(completed.stdout).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(
                f"historical source hash mismatch: {relative_path}"
            )


if __name__ == "__main__":
    raise SystemExit(main())
