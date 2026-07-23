from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.evaluation.trusted_identity import evaluate_trusted_identity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the frozen offline R2-S5 trusted identity API matrix."
    )
    parser.add_argument(
        "--matrix",
        type=Path,
        default=Path("data/v2/security/r2_s5_identity_matrix_v1.json"),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("security_runs/r2_s5/identity_matrix_result.json"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _require_absent_output(args.out)
    result = evaluate_trusted_identity(args.matrix)
    _write_new_result(
        args.out,
        json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    print(args.out)
    return 0 if result.release_pass else 1


def _require_absent_output(path: Path) -> None:
    target = Path(path)
    try:
        target.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise FileExistsError(
            f"identity evaluation output cannot be validated: {target}"
        ) from exc
    raise FileExistsError(f"identity evaluation output already exists: {target}")


def _write_new_result(path: Path, text: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = text.encode("utf-8")
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(target, flags, 0o600)
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise OSError("identity evaluation result write made no progress")
            written += count
        os.fsync(descriptor)
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
            descriptor = None
            target.unlink(missing_ok=True)
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
