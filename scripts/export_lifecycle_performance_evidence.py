from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import sys
from typing import Sequence

from scripts import _bootstrap  # noqa: F401

from app.filesystem import atomic_directory_move
from app.ingestion.path_security import absolute_path_has_redirect
from app.lifecycle.evidence import (
    EvidenceArtifactHash,
    ExperimentRecord,
    load_jsonl_records,
    resolve_bounded_file,
    validate_experiment_history,
    validate_repository_relative_path,
)
from app.lifecycle.performance_evidence import (
    LifecyclePerformanceEvidencePackageManifest,
    PackagedRawArtifact,
    build_public_performance_summary,
    canonical_performance_package_checksums,
    canonical_performance_package_manifest_bytes,
    canonical_public_performance_summary_bytes,
    experiment_identity_from_record,
    package_path_for_dataset_metadata,
    package_path_for_raw_artifact,
    verify_public_performance_evidence_package,
)


BASE_DIR = Path(__file__).resolve().parents[1]
PUBLIC_ROOT = (BASE_DIR / "data" / "v2" / "public").resolve()
EXPERIMENTS_PATH = BASE_DIR / "docs" / "lifecycle" / "EXPERIMENTS.jsonl"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _binding(path: str, content: bytes) -> EvidenceArtifactHash:
    return EvidenceArtifactHash(
        path=path,
        byte_count=len(content),
        sha256=_sha256(content),
    )


def _exclusive_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        path,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
        0o600,
    )
    try:
        written = os.write(descriptor, content)
        if written != len(content):
            raise OSError("short public evidence write")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _output_directory(path: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = BASE_DIR / candidate
    candidate = candidate.absolute()
    if absolute_path_has_redirect(candidate):
        raise ValueError("public evidence output ancestry contains a redirect")
    resolved = candidate.resolve()
    public_root = PUBLIC_ROOT.resolve(strict=True)
    if (
        resolved == public_root
        or not resolved.is_relative_to(public_root)
        or resolved.exists()
        or resolved.parent != public_root
    ):
        raise ValueError(
            "public evidence output must be a new direct child of "
            "data/v2/public"
        )
    return resolved


def _dataset_metadata(
    relative_paths: Sequence[str],
) -> tuple[tuple[EvidenceArtifactHash, bytes], ...]:
    normalized = [
        validate_repository_relative_path(value) for value in relative_paths
    ]
    if len(normalized) != len(set(normalized)):
        raise ValueError("dataset metadata paths must be unique")
    packaged: list[tuple[EvidenceArtifactHash, bytes]] = []
    for source_path in sorted(normalized):
        content = resolve_bounded_file(BASE_DIR, source_path).read_bytes()
        package_path = package_path_for_dataset_metadata(source_path)
        packaged.append((_binding(package_path, content), content))
    return tuple(packaged)


def export_completed_experiment(
    *,
    completed_experiment_id: str,
    output_directory: Path,
    dataset_metadata_paths: Sequence[str] = (),
) -> Path:
    records = load_jsonl_records(EXPERIMENTS_PATH, ExperimentRecord)
    validate_experiment_history(records)
    record = next(
        (
            item
            for item in records
            if item.experiment_id == completed_experiment_id
        ),
        None,
    )
    if record is None:
        raise ValueError("completed experiment ID was not found")

    summary = build_public_performance_summary(
        BASE_DIR,
        record,
        history=records,
    )
    summary_bytes = canonical_public_performance_summary_bytes(summary)
    summary_binding = _binding("summary.json", summary_bytes)

    raw_payloads: list[tuple[PackagedRawArtifact, bytes]] = []
    for source_binding in summary.raw_artifacts:
        source_content = resolve_bounded_file(
            BASE_DIR,
            source_binding.path,
        ).read_bytes()
        if (
            len(source_content) != source_binding.byte_count
            or _sha256(source_content) != source_binding.sha256
        ):
            raise ValueError(
                f"raw artifact changed during export: {source_binding.path}"
            )
        package_path = package_path_for_raw_artifact(source_binding.path)
        package_binding = _binding(package_path, source_content)
        raw_payloads.append(
            (
                PackagedRawArtifact(
                    source_path=source_binding.path,
                    package_file=package_binding,
                ),
                source_content,
            )
        )

    metadata_payloads = _dataset_metadata(dataset_metadata_paths)
    manifest = LifecyclePerformanceEvidencePackageManifest(
        experiment=experiment_identity_from_record(
            record,
            history=records,
        ),
        summary=summary_binding,
        raw_artifacts=tuple(item for item, _ in raw_payloads),
        dataset_metadata=tuple(
            binding for binding, _ in metadata_payloads
        ),
    )
    manifest_bytes = canonical_performance_package_manifest_bytes(manifest)
    manifest_binding = _binding("manifest.json", manifest_bytes)
    checksum_bytes = canonical_performance_package_checksums(
        [
            manifest_binding,
            summary_binding,
            *(item.package_file for item, _ in raw_payloads),
            *(binding for binding, _ in metadata_payloads),
        ]
    )

    output = _output_directory(output_directory)
    temporary = output.with_name(
        f".{output.name}.tmp-{secrets.token_hex(8)}"
    )
    temporary.mkdir(parents=False)
    try:
        _exclusive_write(temporary / "summary.json", summary_bytes)
        for packaged, content in raw_payloads:
            _exclusive_write(
                temporary / Path(packaged.package_file.path),
                content,
            )
        for binding, content in metadata_payloads:
            _exclusive_write(temporary / Path(binding.path), content)
        _exclusive_write(temporary / "manifest.json", manifest_bytes)
        _exclusive_write(
            temporary / "checksums.sha256",
            checksum_bytes,
        )
        verify_public_performance_evidence_package(temporary)
        atomic_directory_move(temporary, output)
        verify_public_performance_evidence_package(output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export a self-contained, independently verifiable lifecycle "
            "performance evidence package."
        )
    )
    parser.add_argument("--completed-experiment-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--dataset-metadata-file",
        action="append",
        default=[],
        help=(
            "Optional repository-relative dataset metadata file. The file is "
            "copied below dataset/ and bound by the package manifest."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output = export_completed_experiment(
            completed_experiment_id=args.completed_experiment_id,
            output_directory=args.output_dir,
            dataset_metadata_paths=args.dataset_metadata_file,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(output.relative_to(BASE_DIR).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
