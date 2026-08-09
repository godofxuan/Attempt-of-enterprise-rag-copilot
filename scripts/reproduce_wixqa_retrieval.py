from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.external_datasets.wixqa import DEFAULT_WIXQA_MANIFEST


DEFAULT_PROTOCOL = Path(
    "docs/enterprise_eval/evidence/WIXQA_RETRIEVAL_PROTOCOL_V1.json"
)
DEFAULT_PUBLIC_OUTPUT = Path(
    "docs/enterprise_eval/evidence/wixqa_retrieval_baseline_public_v2.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reproduce the frozen WixQA retrieval baseline end to end."
    )
    parser.add_argument("--run-prefix", required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_WIXQA_MANIFEST)
    parser.add_argument(
        "--source-root", type=Path, default=Path(".private/external/wixqa/source")
    )
    parser.add_argument(
        "--index-root", type=Path, default=Path(".private/external/wixqa/indexes")
    )
    parser.add_argument(
        "--output-root", type=Path, default=Path(".private/external/wixqa/eval_runs")
    )
    parser.add_argument(
        "--embedding-cache",
        type=Path,
        default=Path(".private/external/wixqa/embedding_cache"),
    )
    parser.add_argument("--public-output", type=Path, default=DEFAULT_PUBLIC_OUTPUT)
    parser.add_argument("--reuse-verified-index", action="store_true")
    parser.add_argument("--publish-existing", action="store_true")
    parser.add_argument("--require-clean-roots", action="store_true")
    return parser


def command_plan(args: argparse.Namespace) -> list[list[str]]:
    python = sys.executable
    run_ids = {
        cohort: f"{args.run_prefix}-{cohort}" for cohort in _cohorts()
    }
    commands: list[list[str]] = []
    if not args.publish_existing:
        commands.append(
            [
                python,
                "-m",
                "scripts.download_wixqa",
                "--source-root",
                str(args.source_root),
                "--manifest",
                str(args.manifest),
            ]
        )
        if not args.reuse_verified_index:
            commands.append(
                [
                    python,
                    "-m",
                    "scripts.build_wixqa_index",
                    "--source-root",
                    str(args.source_root),
                    "--manifest",
                    str(args.manifest),
                    "--output-root",
                    str(args.index_root),
                    "--embedding-cache",
                    str(args.embedding_cache),
                    "--run-id",
                    f"{args.run_prefix}-index",
                ]
            )
        for cohort in _cohorts():
            command = [
                python,
                "-m",
                "scripts.eval_wixqa_retrieval",
                "--cohort",
                cohort,
                "--source-root",
                str(args.source_root),
                "--manifest",
                str(args.manifest),
                "--index-root",
                str(args.index_root),
                "--output-root",
                str(args.output_root),
                "--run-id",
                run_ids[cohort],
            ]
            if cohort == "expertwritten":
                command.append("--consume-fixed-external")
            commands.append(command)

    metadata = args.output_root / f"{args.run_prefix}-machine.json"
    commands.append(
        [
            python,
            "-m",
            "scripts.publish_wixqa_retrieval_eval",
            "--protocol",
            str(args.protocol),
            "--synthetic-summary",
            str(args.output_root / run_ids["synthetic"] / "summary.json"),
            "--simulated-summary",
            str(args.output_root / run_ids["simulated"] / "summary.json"),
            "--expertwritten-summary",
            str(args.output_root / run_ids["expertwritten"] / "summary.json"),
            "--reproduction-metadata",
            str(metadata),
            "--output",
            str(args.public_output),
        ]
    )
    return commands


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.require_clean_roots:
        _verify_clean_roots(args)
    args.output_root.mkdir(parents=True, exist_ok=True)
    metadata_path = args.output_root / f"{args.run_prefix}-machine.json"
    metadata = _machine_metadata()
    metadata["clean_reproduction"] = {
        "required": bool(args.require_clean_roots),
        "historical_private_artifacts_used_as_input": False,
        "dataset_manifest_path": str(args.manifest.resolve()),
        "dataset_manifest_sha256": hashlib.sha256(
            args.manifest.read_bytes()
        ).hexdigest(),
        "source_root": str(args.source_root.resolve()),
        "index_root": str(args.index_root.resolve()),
        "embedding_cache": str(args.embedding_cache.resolve()),
        "output_root": str(args.output_root.resolve()),
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for command in command_plan(args):
        subprocess.run(command, check=True)
    return 0


def _machine_metadata() -> dict[str, object]:
    from app.config import get_settings
    from app.runtime.ollama_embeddings import OllamaEmbeddingClient

    import faiss
    import numpy

    client = OllamaEmbeddingClient.from_settings(
        get_settings(),
        probe_text="WixQA clean reproduction metadata probe",
        endpoint_context="WixQA clean reproduction metadata",
    )
    requirements = Path("requirements.txt")
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, encoding="utf-8"
        ).strip(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor() or "UNKNOWN",
        "logical_cpu_count": os.cpu_count(),
        "requirements_sha256": hashlib.sha256(requirements.read_bytes()).hexdigest(),
        "numpy": numpy.__version__,
        "faiss": faiss.__version__,
        "torch": _package_version("torch"),
        "blas": numpy.__config__.CONFIG.get("Build Dependencies", {}).get("blas"),
        "embedding_model": client.model_identifier,
        "embedding_model_sha256": client.model_sha256,
        "embedding_dimension": client.dimension,
        "gpu": _gpu_identity(),
        "latency_comparability": "MACHINE_SPECIFIC",
        "fixed_labels": "REGRESSION_REPLAY_NOT_NEW_HOLDOUT",
    }


def _verify_clean_roots(args: argparse.Namespace) -> None:
    roots = {
        "source_root": args.source_root.resolve(),
        "index_root": args.index_root.resolve(),
        "embedding_cache": args.embedding_cache.resolve(),
        "output_root": args.output_root.resolve(),
    }
    if len(set(roots.values())) != len(roots):
        raise ValueError("WixQA clean reproduction roots must be distinct")
    dirty = [name for name, path in roots.items() if path.exists()]
    if dirty:
        raise FileExistsError(
            "WixQA clean reproduction roots already exist: " + ", ".join(dirty)
        )


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "NOT_INSTALLED"


def _gpu_identity() -> str:
    try:
        return subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader",
            ],
            text=True,
            timeout=10,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "UNAVAILABLE"


def _cohorts() -> tuple[str, ...]:
    return ("synthetic", "simulated", "expertwritten")


if __name__ == "__main__":
    raise SystemExit(main())
