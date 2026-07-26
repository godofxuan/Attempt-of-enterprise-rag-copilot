from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Literal

from scripts import _bootstrap  # noqa: F401

from app.indexing.benchmark import (
    FullRebuildMeasurement,
    deterministic_embedding,
    measure_full_rebuild,
    summarize_full_rebuilds,
)
from app.ingestion.chunking import ChunkerConfig


BASE_DIR = Path(__file__).resolve().parents[1]
Backend = Literal["deterministic", "ollama"]
_SAFE_RUN_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,95}")
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
_PACKAGE_NAMES = (
    "faiss-cpu",
    "jieba",
    "numpy",
    "pydantic",
    "pydantic-settings",
    "pytest",
    "requests",
)


def minimum_repetitions(backend: Backend) -> int:
    return 10 if backend == "deterministic" else 5


def validate_repetitions(backend: Backend, repetitions: int) -> None:
    minimum = minimum_repetitions(backend)
    if repetitions < minimum:
        raise ValueError(
            f"{backend} full rebuild measurement requires at least "
            f"{minimum} repetitions"
        )


def validate_run_id(run_id: str) -> str:
    stem = run_id.split(".", 1)[0].upper()
    if (
        not _SAFE_RUN_ID.fullmatch(run_id)
        or stem in _WINDOWS_RESERVED
        or run_id.endswith((".", " "))
    ):
        raise ValueError("benchmark run ID is unsafe")
    return run_id


def resolve_run_directories(
    *,
    repository_root: Path,
    artifact_root: Path,
    work_root: Path,
    run_id: str,
) -> tuple[Path, Path]:
    repository = Path(repository_root).resolve()
    expected_artifact_root = (repository / "artifacts" / "lifecycle").resolve()
    expected_work_root = (repository / ".private" / "lifecycle").resolve()
    resolved_artifact_root = Path(artifact_root).resolve()
    resolved_work_root = Path(work_root).resolve()
    if resolved_artifact_root != expected_artifact_root:
        raise ValueError("artifact root must be artifacts/lifecycle")
    if resolved_work_root != expected_work_root:
        raise ValueError("work root must be .private/lifecycle")
    safe_run_id = validate_run_id(run_id)
    artifact_dir = (resolved_artifact_root / safe_run_id).resolve()
    work_dir = (resolved_work_root / safe_run_id).resolve()
    if not artifact_dir.is_relative_to(resolved_artifact_root):
        raise ValueError("artifact run directory escapes its root")
    if not work_dir.is_relative_to(resolved_work_root):
        raise ValueError("work run directory escapes its root")
    if artifact_dir.exists() or work_dir.exists():
        raise FileExistsError("benchmark run directory already exists")
    return artifact_dir, work_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure the current enterprise index full-rebuild path.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run")
    run.add_argument(
        "--profile",
        choices=("expanded", "expanded_benchmark"),
        required=True,
    )
    run.add_argument(
        "--embedding",
        choices=("deterministic", "ollama"),
        required=True,
    )
    run.add_argument("--embedding-model")
    run.add_argument("--repetitions", type=int, required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--chunk-size", type=int, default=500)
    run.add_argument("--overlap", type=int, default=80)
    run.add_argument(
        "--build-timestamp",
        default="2026-07-26T04:00:00+00:00",
    )

    worker = subparsers.add_parser("worker")
    worker.add_argument(
        "--profile",
        choices=("expanded", "expanded_benchmark"),
        required=True,
    )
    worker.add_argument(
        "--embedding",
        choices=("deterministic", "ollama"),
        required=True,
    )
    worker.add_argument("--embedding-model", required=True)
    worker.add_argument("--run-id", required=True)
    worker.add_argument("--repetition", type=int, required=True)
    worker.add_argument("--chunk-size", type=int, required=True)
    worker.add_argument("--overlap", type=int, required=True)
    worker.add_argument("--build-timestamp", required=True)
    worker.add_argument("--output-dir", type=Path, required=True)
    worker.add_argument("--result-file", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "worker":
            return _worker(args)
        return _coordinator(args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _coordinator(args: argparse.Namespace) -> int:
    validate_repetitions(args.embedding, args.repetitions)
    if args.embedding == "ollama" and not args.embedding_model:
        raise ValueError("--embedding-model is required for ollama")
    if args.embedding == "deterministic" and args.embedding_model:
        raise ValueError("--embedding-model is fixed for deterministic runs")
    build_timestamp = _parse_timestamp(args.build_timestamp)
    embedding_model = (
        "deterministic-shake256-128"
        if args.embedding == "deterministic"
        else args.embedding_model
    )
    artifact_dir, work_dir = resolve_run_directories(
        repository_root=BASE_DIR,
        artifact_root=BASE_DIR / "artifacts" / "lifecycle",
        work_root=BASE_DIR / ".private" / "lifecycle",
        run_id=args.run_id,
    )
    artifact_dir.mkdir(parents=True)
    work_dir.mkdir(parents=True)
    per_run_dir = artifact_dir / "per_run"
    logs_dir = artifact_dir / "logs"
    per_run_dir.mkdir()
    logs_dir.mkdir()

    commands: list[str] = []
    rows: list[FullRebuildMeasurement] = []
    status = {
        "schema_version": "full_rebuild_run_status_v1",
        "run_id": args.run_id,
        "status": "RUNNING",
        "completed_repetitions": 0,
        "requested_repetitions": args.repetitions,
    }
    _write_json(artifact_dir / "environment.json", _environment(args, embedding_model))
    _write_json(artifact_dir / "status.json", status)

    for repetition in range(1, args.repetitions + 1):
        result_file = per_run_dir / f"{repetition:03d}.json"
        output_dir = work_dir / f"{repetition:03d}" / "index"
        command = _worker_command(
            args=args,
            embedding_model=embedding_model,
            build_timestamp=build_timestamp,
            repetition=repetition,
            output_dir=output_dir,
            result_file=result_file,
        )
        commands.append(subprocess.list2cmdline(command))
        (artifact_dir / "commands.txt").write_text(
            "\n".join(commands) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        environment = os.environ.copy()
        environment["TEMP"] = str(work_dir)
        environment["TMP"] = str(work_dir)
        log_path = logs_dir / f"{repetition:03d}.log"
        with log_path.open("w", encoding="utf-8", newline="\n") as log:
            completed = subprocess.run(
                command,
                cwd=BASE_DIR,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        if completed.returncode != 0:
            status.update(
                {
                    "status": "FAILED",
                    "failed_repetition": repetition,
                    "worker_exit_code": completed.returncode,
                }
            )
            _write_json(artifact_dir / "status.json", status)
            _write_checksums(artifact_dir)
            return completed.returncode
        row = FullRebuildMeasurement.model_validate_json(
            result_file.read_text(encoding="utf-8")
        )
        rows.append(row)
        _remove_build_output(work_dir, output_dir.parent)
        status["completed_repetitions"] = repetition
        _write_json(artifact_dir / "status.json", status)

    process_ids = [row.process_id for row in rows]
    if len(set(process_ids)) != len(rows):
        raise RuntimeError("benchmark repetitions did not use distinct processes")
    summary = summarize_full_rebuilds(rows).model_dump(mode="json")
    summary.update(
        {
            "run_id": args.run_id,
            "build_timestamp": build_timestamp.isoformat(),
            "worker_process_ids": process_ids,
            "distinct_worker_processes": len(set(process_ids)),
        }
    )
    _write_json(artifact_dir / "summary.json", summary)
    _write_jsonl(artifact_dir / "per_run.jsonl", rows)
    status.update({"status": "COMPLETED", "worker_exit_code": 0})
    _write_json(artifact_dir / "status.json", status)
    _write_checksums(artifact_dir)
    if work_dir.exists() and next(work_dir.iterdir(), None) is None:
        work_dir.rmdir()
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    return 0


def _worker(args: argparse.Namespace) -> int:
    validate_run_id(args.run_id)
    if args.repetition < 1:
        raise ValueError("repetition must be positive")
    output_dir = Path(args.output_dir).resolve()
    result_file = Path(args.result_file).resolve()
    allowed_work_root = (BASE_DIR / ".private" / "lifecycle").resolve()
    allowed_artifact_root = (BASE_DIR / "artifacts" / "lifecycle").resolve()
    if not output_dir.is_relative_to(allowed_work_root):
        raise ValueError("worker output directory escapes private lifecycle root")
    if not result_file.is_relative_to(allowed_artifact_root):
        raise ValueError("worker result file escapes artifact lifecycle root")
    if output_dir.exists() or result_file.exists():
        raise FileExistsError("worker output already exists")

    if args.embedding == "deterministic":
        if args.embedding_model != "deterministic-shake256-128":
            raise ValueError("deterministic embedding model identity is invalid")
        embed_text = deterministic_embedding
    else:
        from app.retriever import _embed_text

        embed_text = lambda text: _embed_text(args.embedding_model, text)

    input_dir = BASE_DIR / "data" / "v2" / "generated" / args.profile
    measurement = measure_full_rebuild(
        input_dir=input_dir,
        output_dir=output_dir,
        run_id=f"{args.run_id}-{args.repetition:03d}",
        repetition=args.repetition,
        chunker_config=ChunkerConfig(
            mode="fixed",
            chunk_size=args.chunk_size,
            overlap=args.overlap,
        ),
        embedding_backend=args.embedding,
        embedding_model=args.embedding_model,
        embed_text=embed_text,
        started_at=_parse_timestamp(args.build_timestamp),
    )
    result_file.parent.mkdir(parents=True, exist_ok=True)
    _write_json(result_file, measurement.model_dump(mode="json"))
    return 0


def _worker_command(
    *,
    args: argparse.Namespace,
    embedding_model: str,
    build_timestamp: datetime,
    repetition: int,
    output_dir: Path,
    result_file: Path,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "scripts.benchmark_full_rebuild",
        "worker",
        "--profile",
        args.profile,
        "--embedding",
        args.embedding,
        "--embedding-model",
        embedding_model,
        "--run-id",
        args.run_id,
        "--repetition",
        str(repetition),
        "--chunk-size",
        str(args.chunk_size),
        "--overlap",
        str(args.overlap),
        "--build-timestamp",
        build_timestamp.isoformat(),
        "--output-dir",
        str(output_dir),
        "--result-file",
        str(result_file),
    ]


def _environment(args: argparse.Namespace, embedding_model: str) -> dict[str, object]:
    return {
        "schema_version": "full_rebuild_environment_v1",
        "git": {
            "head": _git_output("rev-parse", "HEAD"),
            "branch": _git_output("branch", "--show-current"),
            "dirty": bool(_git_output("status", "--porcelain")),
        },
        "python": sys.version,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "packages": {
            name: _package_version(name)
            for name in _PACKAGE_NAMES
        },
        "configuration": {
            "profile": args.profile,
            "embedding_backend": args.embedding,
            "embedding_model": embedding_model,
            "repetitions": args.repetitions,
            "chunk_size": args.chunk_size,
            "overlap": args.overlap,
            "build_timestamp": args.build_timestamp,
        },
    }


def _git_output(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=BASE_DIR,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip() if completed.returncode == 0 else "NOT_AVAILABLE"


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "NOT_INSTALLED"


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("build timestamp must include a UTC offset")
    return parsed


def _remove_build_output(work_root: Path, target: Path) -> None:
    resolved_root = Path(work_root).resolve()
    resolved_target = Path(target).resolve()
    if (
        resolved_target == resolved_root
        or not resolved_target.is_relative_to(resolved_root)
    ):
        raise ValueError("refusing to remove build output outside work root")
    if resolved_target.exists():
        shutil.rmtree(resolved_target)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_jsonl(path: Path, rows: list[FullRebuildMeasurement]) -> None:
    content = "".join(
        json.dumps(
            row.model_dump(mode="json"),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
        for row in rows
    )
    path.write_text(content, encoding="utf-8", newline="\n")


def _write_checksums(root: Path) -> None:
    checksum_path = root / "checksums.sha256"
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path == checksum_path:
            continue
        relative = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(f"{digest}  {relative}")
    checksum_path.write_text(
        "\n".join(rows) + "\n",
        encoding="ascii",
        newline="\n",
    )


if __name__ == "__main__":
    raise SystemExit(main())
