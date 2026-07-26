from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Mapping, Sequence

from pydantic import ValidationError

from app.config import get_settings
from app.lifecycle.operator import (
    LifecycleActivateRequest,
    LifecycleBuildRequest,
    LifecycleOperationError,
    LifecyclePreviewRequest,
    LifecycleRollbackRequest,
    OperatorSourceEventInput,
)
from app.runtime.resources import ServiceContainer, build_service_container
from app.security.identity import AuthenticationFailure


EXIT_CODES = {
    "schema": 2,
    "authorization": 3,
    "file_validation": 4,
    "quarantine": 5,
    "conflict": 6,
    "build": 7,
    "manifest": 8,
    "activation": 9,
    "rollback": 10,
}
_MAX_EVENTS_BYTES = 4 * 1024 * 1024


class CliSchemaError(ValueError):
    pass


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliSchemaError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        description="Operate the authenticated enterprise lifecycle pipeline."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def roots(command: argparse.ArgumentParser) -> None:
        command.add_argument("--input-root", type=Path)
        command.add_argument("--index-root", type=Path)

    preview = subparsers.add_parser("preview")
    preview.add_argument("--events", type=Path, required=True)
    preview.add_argument("--run-id", required=True)
    roots(preview)

    build = subparsers.add_parser("build")
    build.add_argument("--events", type=Path)
    build.add_argument("--run-id", required=True)
    build.add_argument("--activate", action="store_true")
    roots(build)

    activate = subparsers.add_parser("activate")
    activate.add_argument("--run-id", required=True)
    activate.add_argument("--expected-current-run-id")
    roots(activate)

    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--run-id", required=True)
    rollback.add_argument("--expected-current-run-id", required=True)
    roots(rollback)

    status = subparsers.add_parser("status")
    roots(status)
    return parser


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _read_events(path: Path) -> tuple[OperatorSourceEventInput, ...]:
    candidate = Path(os.path.abspath(path))
    descriptor: int | None = None
    try:
        expected = candidate.lstat()
        descriptor = os.open(
            candidate,
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        metadata = os.fstat(descriptor)
        current = candidate.lstat()
        if (
            candidate.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or not os.path.samestat(expected, metadata)
            or not os.path.samestat(metadata, current)
            or metadata.st_size > _MAX_EVENTS_BYTES
        ):
            raise LifecycleOperationError(
                "file_validation",
                "events_file_unsafe",
                "The events file is not a bounded regular file.",
            )
        chunks: list[bytes] = []
        remaining = _MAX_EVENTS_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(raw) > _MAX_EVENTS_BYTES
            or len(raw) != metadata.st_size
            or not os.path.samestat(metadata, after)
            or metadata.st_size != after.st_size
            or getattr(metadata, "st_mtime_ns", None)
            != getattr(after, "st_mtime_ns", None)
        ):
            raise LifecycleOperationError(
                "file_validation",
                "events_file_changed",
                "The events file changed during validation.",
            )
    except LifecycleOperationError:
        raise
    except OSError:
        raise LifecycleOperationError(
            "file_validation",
            "events_file_unavailable",
            "The events file is unavailable.",
        ) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    try:
        text = raw.decode("utf-8")
        lines = text.splitlines()
        if not lines or any(not line.strip() for line in lines):
            raise ValueError("events JSONL must contain non-blank lines")
        if len(lines) > 1000:
            raise ValueError("events JSONL exceeds the event limit")
        return tuple(
            OperatorSourceEventInput.model_validate(
                json.loads(line, object_pairs_hook=_unique_object)
            )
            for line in lines
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
        raise LifecycleOperationError(
            "schema",
            "events_schema_invalid",
            "The events file failed strict schema validation.",
        ) from None


def _emit(payload: object) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _failure(category: str, code: str) -> int:
    _emit(
        {
            "schema_version": "lifecycle_cli_result_v1",
            "status": "FAILED",
            "error": {
                "category": category,
                "code": code,
            },
        }
    )
    return EXIT_CODES[category]


def _unexpected_failure(command: str) -> tuple[str, str]:
    category = {
        "preview": "manifest",
        "build": "build",
        "activate": "activation",
        "rollback": "rollback",
        "status": "manifest",
    }[command]
    return category, f"lifecycle_{command}_failed"


def main(
    argv: Sequence[str] | None = None,
    *,
    container: ServiceContainer | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    try:
        args = build_parser().parse_args(argv)
    except (CliSchemaError, SystemExit):
        return _failure("schema", "cli_arguments_invalid")

    environment = os.environ if environ is None else environ
    token = environment.get("RAG_OPERATOR_TOKEN")
    if not token or token != token.strip() or any(char.isspace() for char in token):
        return _failure("authorization", "authentication_required")
    try:
        service_container = container or build_service_container(get_settings())
        principal = service_container.identity_verifier.verify_bearer(
            f"Bearer {token}"
        )
        if service_container.settings.identity_operator_role not in principal.roles:
            return _failure("authorization", "operator_role_required")
    except AuthenticationFailure as exc:
        return _failure("authorization", exc.code)
    except Exception:
        return _failure("authorization", "identity_unavailable")

    operator = service_container.lifecycle_operator
    if operator is None:
        return _failure("build", "lifecycle_service_unavailable")
    try:
        input_root = (
            None
            if args.input_root is None
            else Path(os.path.abspath(args.input_root))
        )
        index_root = (
            None
            if args.index_root is None
            else Path(os.path.abspath(args.index_root))
        )
        if input_root is not None or index_root is not None:
            operator = operator.with_operator_roots(
                input_root=input_root,
                index_root=index_root,
            )

        if args.command == "preview":
            result = operator.preview(
                LifecyclePreviewRequest(
                    target_run_id=args.run_id,
                    events=_read_events(args.events),
                ),
                principal,
            )
        elif args.command == "build":
            events = () if args.events is None else _read_events(args.events)
            result = operator.build(
                LifecycleBuildRequest(
                    target_run_id=args.run_id,
                    events=events,
                    activate=args.activate,
                ),
                principal,
            )
        elif args.command == "activate":
            result = operator.activate_existing(
                LifecycleActivateRequest(
                    target_run_id=args.run_id,
                    expected_current_run_id=args.expected_current_run_id,
                ),
                principal,
            )
        elif args.command == "rollback":
            result = operator.rollback(
                LifecycleRollbackRequest(
                    target_run_id=args.run_id,
                    expected_current_run_id=args.expected_current_run_id,
                ),
                principal,
            )
        else:
            result = operator.status(principal)
    except LifecycleOperationError as exc:
        return _failure(exc.category, exc.code)
    except ValidationError:
        return _failure("schema", "request_schema_invalid")
    except Exception:
        category, code = _unexpected_failure(args.command)
        return _failure(category, code)

    _emit(
        {
            "schema_version": "lifecycle_cli_result_v1",
            "status": "COMPLETED",
            "result": result.model_dump(mode="json"),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
