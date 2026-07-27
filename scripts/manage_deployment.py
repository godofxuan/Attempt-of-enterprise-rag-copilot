from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.config import BASE_DIR, get_settings
from app.deployment.releases import (
    DeploymentRelease,
    activate_deployment,
    calculate_runtime_contract_sha256,
    load_active_deployment,
    load_release,
    recover_deployment,
    register_release,
    render_compose_environment,
    rollback_deployment,
    verify_active_deployment,
)
from app.indexing.store import load_index_version


def build_parser() -> argparse.ArgumentParser:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Manage immutable single-host deployment releases."
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        default=BASE_DIR / ".private" / "deployment",
    )
    parser.add_argument(
        "--index-root",
        type=Path,
        default=settings.v2_indexes_dir,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    register = subparsers.add_parser("register")
    register.add_argument("--release-id", required=True)
    register.add_argument("--image-reference", required=True)
    register.add_argument("--index-run-id", required=True)
    register.add_argument("--source-commit", default=None)
    register.add_argument("--previous-release-id", default=None)

    activate = subparsers.add_parser("activate")
    activate.add_argument("--release-id", required=True)

    subparsers.add_parser("rollback")

    recover = subparsers.add_parser("recover")
    recover.add_argument(
        "--strategy",
        required=True,
        choices=("restore_previous", "complete_target"),
    )

    render = subparsers.add_parser("render-env")
    render.add_argument("--output", type=Path, required=True)
    render.add_argument("--force", action="store_true")

    subparsers.add_parser("verify")
    subparsers.add_parser("status")
    return parser


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=BASE_DIR,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return completed.stdout.strip()


def _write_environment(path: Path, payload: str, *, force: bool) -> None:
    target = Path(os.path.abspath(path))
    if target.exists() and not force:
        raise FileExistsError(f"deployment environment already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | (os.O_TRUNC if force else os.O_EXCL)
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(target, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _pointer_payload(pointer) -> dict[str, object]:
    return pointer.model_dump(mode="json") if pointer is not None else {}


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    state_root = Path(args.state_root)
    index_root = Path(args.index_root)
    try:
        if args.command == "register":
            index = load_index_version(index_root, args.index_run_id)
            release = DeploymentRelease(
                schema_version="enterprise_deployment_release_v1",
                producer="enterprise_agentic_rag_v2",
                release_id=args.release_id,
                image_reference=args.image_reference,
                source_commit=args.source_commit or _git_head(),
                runtime_contract_sha256=(
                    calculate_runtime_contract_sha256(BASE_DIR)
                ),
                index_run_id=args.index_run_id,
                index_manifest_sha256=index.manifest_sha256,
                previous_release_id=args.previous_release_id,
                created_at=datetime.now(timezone.utc),
            )
            manifest_sha256 = register_release(
                state_root,
                index_root,
                release,
            )
            payload = {
                "release": release.model_dump(mode="json"),
                "release_manifest_sha256": manifest_sha256,
                "status": "registered",
            }
        elif args.command == "activate":
            payload = {
                "active": _pointer_payload(
                    activate_deployment(
                        state_root,
                        index_root,
                        args.release_id,
                    )
                ),
                "status": "active",
            }
        elif args.command == "rollback":
            payload = {
                "active": _pointer_payload(
                    rollback_deployment(state_root, index_root)
                ),
                "status": "rolled_back",
            }
        elif args.command == "recover":
            pointer = recover_deployment(
                state_root,
                index_root,
                strategy=args.strategy,
            )
            payload = {
                "active": _pointer_payload(pointer),
                "status": args.strategy,
            }
        elif args.command == "render-env":
            environment = render_compose_environment(state_root, index_root)
            _write_environment(args.output, environment, force=args.force)
            payload = {
                "output": str(Path(os.path.abspath(args.output))),
                "status": "rendered",
            }
        elif args.command == "verify":
            payload = {
                "active": _pointer_payload(
                    verify_active_deployment(state_root, index_root)
                ),
                "status": "verified",
            }
        else:
            try:
                pointer = load_active_deployment(state_root)
                release, release_sha256 = load_release(
                    state_root,
                    pointer.release_id,
                )
                payload = {
                    "active": pointer.model_dump(mode="json"),
                    "image_reference": release.image_reference,
                    "release_manifest_sha256": release_sha256,
                    "status": "active",
                }
            except FileNotFoundError:
                payload = {"active": None, "status": "not_initialized"}
    except (
        FileExistsError,
        FileNotFoundError,
        PermissionError,
        RuntimeError,
        subprocess.SubprocessError,
        ValueError,
    ) as exc:
        parser.error(str(exc))
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()


__all__ = ["build_parser", "main"]
