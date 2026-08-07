try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.domain.documents import ChunkRecord
from app.external_datasets.financebench import DEFAULT_PREPARED_ROOT
from app.external_datasets.financebench_failure_analysis import (
    analyze_financebench_page_failures,
)
from app.external_datasets.financebench_page_eval import (
    FinanceBenchPageCaseResult,
    load_financebench_bundle,
    verify_financebench_page_run,
)
from app.filesystem import atomic_directory_move


DEFAULT_INDEX_ROOT = (
    Path(__file__).resolve().parent.parent
    / ".private"
    / "external_datasets"
    / "financebench"
    / "indexes"
    / "versions"
)
DEFAULT_OUT_ROOT = (
    Path(__file__).resolve().parent.parent
    / ".private"
    / "external_datasets"
    / "financebench"
    / "failure_analysis"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Classify FinanceBench page-retrieval failures without generation."
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--prepared-root", type=Path, default=DEFAULT_PREPARED_ROOT)
    parser.add_argument("--index-root", type=Path, default=DEFAULT_INDEX_ROOT)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--analysis-id", required=True)
    parser.add_argument("--parser-risk-threshold", type=float, default=0.20)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    code_revision = _clean_git_revision()
    source_manifest = verify_financebench_page_run(args.run_dir)
    _, evidence_cases, source_hashes = load_financebench_bundle(
        args.prepared_root,
        split=source_manifest.split,
    )
    details_path = Path(args.run_dir).resolve() / "details.jsonl"
    details = [
        FinanceBenchPageCaseResult.model_validate_json(line)
        for line in details_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    index_dir = (
        Path(args.index_root).resolve() / source_manifest.index_run_id
    ).resolve()
    chunks_path = index_dir / "chunks.json"
    chunks = [
        ChunkRecord.model_validate(item)
        for item in _read_json_array(chunks_path)
    ]
    summary, per_case = analyze_financebench_page_failures(
        details=details,
        evidence_cases=evidence_cases,
        chunks=chunks,
        parser_risk_threshold=args.parser_risk_threshold,
    )

    summary_bytes = _json_bytes(summary.model_dump(mode="json"))
    per_case_bytes = b"".join(
        _json_bytes(item.model_dump(mode="json")) for item in per_case
    )
    manifest = {
        "schema_version": "financebench_failure_analysis_v1",
        "analysis_id": args.analysis_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_revision": code_revision,
        "source_run_id": source_manifest.run_id,
        "source_run_code_revision": source_manifest.code_revision,
        "source_details_sha256": _sha256(details_path),
        "source_index_run_id": source_manifest.index_run_id,
        "source_chunks_sha256": _sha256(chunks_path),
        "source_dataset_hashes": source_hashes,
        "parser_risk_threshold": args.parser_risk_threshold,
        "command": [sys.executable, *sys.argv[1:]],
        "hardware": {
            "platform": platform.platform(),
            "processor": platform.processor() or "not_reported",
        },
        "artifacts": {
            "summary.json": {
                "sha256": hashlib.sha256(summary_bytes).hexdigest(),
                "byte_count": len(summary_bytes),
            },
            "per_case.private.jsonl": {
                "sha256": hashlib.sha256(per_case_bytes).hexdigest(),
                "byte_count": len(per_case_bytes),
            },
        },
    }
    manifest_bytes = _json_bytes(manifest)
    output = _publish(
        root=args.out_root,
        analysis_id=args.analysis_id,
        artifacts={
            "manifest.json": manifest_bytes,
            "summary.json": summary_bytes,
            "per_case.private.jsonl": per_case_bytes,
        },
    )
    print(
        json.dumps(
            {
                "analysis_id": args.analysis_id,
                "output_dir": str(output),
                **summary.model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _publish(
    *,
    root: Path,
    analysis_id: str,
    artifacts: dict[str, bytes],
) -> Path:
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / analysis_id).resolve()
    if target.parent != root or analysis_id in {".", ".."}:
        raise ValueError("failure analysis ID is unsafe")
    if target.exists():
        raise FileExistsError(f"failure analysis already exists: {target}")
    stage = Path(tempfile.mkdtemp(prefix=f".{analysis_id}.staging-", dir=root))
    try:
        for name, content in artifacts.items():
            (stage / name).write_bytes(content)
        atomic_directory_move(stage, target)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return target


def _clean_git_revision() -> str:
    root = Path(__file__).resolve().parent.parent
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if dirty:
        raise ValueError("failure analysis requires a clean tracked worktree")
    return revision


def _read_json_array(path: Path) -> list[object]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"expected JSON array: {path}")
    return value


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
