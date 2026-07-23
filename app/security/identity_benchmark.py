from __future__ import annotations

import math
import platform
import secrets
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from app.security.identity import IdentityVerifier
from app.security.token_source import BearerTokenSource


@dataclass(frozen=True)
class IdentityBenchmarkResult:
    schema_version: str
    run_id: str
    recorded_at_utc: str
    algorithm: str
    iterations: int
    warmup_iterations: int
    latency_ms: dict[str, float]
    target_p95_ms: float
    target_met: bool
    method: dict[str, str]
    environment: dict[str, str]


def benchmark_identity_verification(
    verifier: IdentityVerifier,
    token_source: BearerTokenSource,
    *,
    iterations: int = 1_000,
    warmup_iterations: int = 50,
    target_p95_ms: float = 10.0,
    clock_ns: Callable[[], int] = time.perf_counter_ns,
) -> IdentityBenchmarkResult:
    if iterations < 1 or warmup_iterations < 0 or target_p95_ms <= 0:
        raise ValueError("identity benchmark arguments are invalid")
    verifier.ready()
    authorization = f"Bearer {token_source.get_token()}"
    for _ in range(warmup_iterations):
        verifier.verify_bearer(authorization)

    durations: list[float] = []
    for _ in range(iterations):
        started = clock_ns()
        verifier.verify_bearer(authorization)
        durations.append(max(0, clock_ns() - started) / 1_000_000.0)

    latency = {
        "min": round(min(durations), 6),
        "p50": round(_nearest_rank(durations, 0.50), 6),
        "p95": round(_nearest_rank(durations, 0.95), 6),
        "p99": round(_nearest_rank(durations, 0.99), 6),
        "max": round(max(durations), 6),
    }
    recorded_at = datetime.now(timezone.utc)
    return IdentityBenchmarkResult(
        schema_version="identity-verification-benchmark-v2",
        run_id=(
            "identity-benchmark-"
            + recorded_at.strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + secrets.token_hex(6)
        ),
        recorded_at_utc=recorded_at.isoformat(timespec="seconds").replace(
            "+00:00",
            "Z",
        ),
        algorithm="RS256",
        iterations=iterations,
        warmup_iterations=warmup_iterations,
        latency_ms=latency,
        target_p95_ms=target_p95_ms,
        target_met=latency["p95"] <= target_p95_ms,
        method={
            "clock": "time.perf_counter_ns",
            "execution": "single_process_serial",
            "scope": "warm_verifier_only",
        },
        environment={
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "executable_bits": str(64 if sys.maxsize > 2**32 else 32),
        },
    )


def _nearest_rank(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(quantile * len(ordered)))
    return ordered[rank - 1]


__all__ = ["IdentityBenchmarkResult", "benchmark_identity_verification"]
