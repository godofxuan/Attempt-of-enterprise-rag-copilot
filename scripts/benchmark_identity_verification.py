from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from app.config import BASE_DIR, Settings, get_settings
from app.security.demo_identity import initialize_demo_identity
from app.security.identity import build_identity_verifier
from app.security.identity_benchmark import (
    IdentityBenchmarkResult,
    benchmark_identity_verification,
)
from app.security.token_source import BearerTokenFileSource


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure local RS256 verification without publishing secrets."
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        default=Path(".private/identity/operator_token.txt"),
    )
    parser.add_argument("--iterations", type=int, default=1_000)
    parser.add_argument("--warmup-iterations", type=int, default=50)
    parser.add_argument("--target-p95-ms", type=float, default=10.0)
    parser.add_argument(
        "--ephemeral-demo",
        action="store_true",
        help="Generate an isolated managed identity for this benchmark run.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("security_runs/r2_s5/identity_benchmark.json"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    if args.ephemeral_demo:
        with TemporaryDirectory(prefix="r2-s5-identity-benchmark-") as temporary:
            root = Path(temporary)
            initialize_demo_identity(
                root,
                issuer=settings.identity_issuer,
                audience=settings.identity_audience,
                token_lifetime_seconds=900,
            )
            benchmark_settings = settings.model_copy(
                update={"identity_jwks_path": root / "jwks.json"}
            )
            result = _run_benchmark(
                args,
                settings=benchmark_settings,
                token_file=root / "operator_token.txt",
            )
            input_mode = "ephemeral_managed_identity"
    else:
        result = _run_benchmark(
            args,
            settings=settings,
            token_file=args.token_file,
        )
        input_mode = "configured_token_source"
    _write_result(args.out, result, input_mode=input_mode)
    print(args.out)
    return 0 if result.target_met else 1


def _run_benchmark(
    args: argparse.Namespace,
    *,
    settings: Settings,
    token_file: Path,
) -> IdentityBenchmarkResult:
    result = benchmark_identity_verification(
        build_identity_verifier(settings),
        BearerTokenFileSource(token_file),
        iterations=args.iterations,
        warmup_iterations=args.warmup_iterations,
        target_p95_ms=args.target_p95_ms,
    )
    return result


def _write_result(
    path: Path,
    result: IdentityBenchmarkResult,
    *,
    input_mode: str,
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **asdict(result),
        "provenance": {
            "input_mode": input_mode,
            "source_sha256": {
                relative: hashlib.sha256((BASE_DIR / relative).read_bytes()).hexdigest()
                for relative in (
                    "app/security/identity.py",
                    "app/security/identity_benchmark.py",
                    "scripts/benchmark_identity_verification.py",
                )
            },
        },
    }
    raw = (
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
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
        while written < len(raw):
            count = os.write(descriptor, raw[written:])
            if count <= 0:
                raise OSError("identity benchmark write made no progress")
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
