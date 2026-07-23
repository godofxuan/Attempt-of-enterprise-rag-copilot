from __future__ import annotations

import hashlib
import json
import re

import pytest

from app.config import BASE_DIR
from app.security.identity_benchmark import (
    IdentityBenchmarkResult,
    benchmark_identity_verification,
)
import scripts.benchmark_identity_verification as benchmark_cli
from scripts.benchmark_identity_verification import main


class FakeVerifier:
    def __init__(self) -> None:
        self.calls = 0

    def ready(self) -> None:
        return None

    def verify_bearer(self, authorization):
        assert authorization == "Bearer aaa.bbb.ccc"
        self.calls += 1
        return object()


class FakeTokenSource:
    def get_token(self) -> str:
        return "aaa.bbb.ccc"


def test_identity_benchmark_records_distribution_without_token_or_claims() -> None:
    ticks = iter([0, 1_000_000, 2_000_000, 4_000_000, 5_000_000, 8_000_000])
    verifier = FakeVerifier()

    result = benchmark_identity_verification(
        verifier,
        FakeTokenSource(),
        iterations=3,
        warmup_iterations=2,
        target_p95_ms=3.0,
        clock_ns=lambda: next(ticks),
    )

    assert verifier.calls == 5
    assert result.latency_ms == {
        "min": 1.0,
        "p50": 2.0,
        "p95": 3.0,
        "p99": 3.0,
        "max": 3.0,
    }
    assert result.target_met is True
    assert result.schema_version == "identity-verification-benchmark-v2"
    assert re.fullmatch(
        r"identity-benchmark-\d{8}T\d{6}Z-[0-9a-f]{12}",
        result.run_id,
    )
    assert result.recorded_at_utc.endswith("Z")
    assert result.method["scope"] == "warm_verifier_only"
    serialized = repr(result)
    assert "aaa.bbb.ccc" not in serialized
    assert "subject" not in serialized


def test_identity_benchmark_cli_can_use_an_ephemeral_managed_identity(
    tmp_path,
) -> None:
    output = tmp_path / "benchmark.json"

    exit_code = main(
        [
            "--ephemeral-demo",
            "--iterations",
            "3",
            "--warmup-iterations",
            "1",
            "--out",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["iterations"] == 3
    assert payload["warmup_iterations"] == 1
    assert payload["provenance"]["input_mode"] == "ephemeral_managed_identity"
    assert set(payload["provenance"]["source_sha256"]) == {
        "app/security/identity.py",
        "app/security/identity_benchmark.py",
        "scripts/benchmark_identity_verification.py",
    }
    serialized = output.read_text(encoding="utf-8")
    assert "PRIVATE KEY" not in serialized
    assert "operator_token" not in serialized
    assert str(tmp_path) not in serialized

    with pytest.raises(FileExistsError):
        main(
            [
                "--ephemeral-demo",
                "--iterations",
                "1",
                "--warmup-iterations",
                "0",
                "--out",
                str(output),
            ]
        )


def test_identity_benchmark_cli_returns_failure_when_latency_target_is_missed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "missed-target.json"
    missed = IdentityBenchmarkResult(
        schema_version="identity-verification-benchmark-v2",
        run_id="identity-benchmark-20260723T000000Z-000000000000",
        recorded_at_utc="2026-07-23T00:00:00Z",
        algorithm="RS256",
        iterations=3,
        warmup_iterations=1,
        latency_ms={
            "min": 11.0,
            "p50": 12.0,
            "p95": 13.0,
            "p99": 13.0,
            "max": 13.0,
        },
        target_p95_ms=10.0,
        target_met=False,
        method={
            "clock": "time.perf_counter_ns",
            "execution": "single_process_serial",
            "scope": "warm_verifier_only",
        },
        environment={
            "python": "3.11.9",
            "implementation": "CPython",
            "platform": "test",
            "machine": "test",
            "executable_bits": "64",
        },
    )
    monkeypatch.setattr(
        benchmark_cli,
        "_run_benchmark",
        lambda *args, **kwargs: missed,
    )

    exit_code = main(
        [
            "--token-file",
            str(tmp_path / "not-read.txt"),
            "--out",
            str(output),
        ]
    )

    assert exit_code == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["target_met"] is False
    assert payload["latency_ms"]["p95"] > payload["target_p95_ms"]


def test_public_identity_benchmark_is_current_passing_evidence() -> None:
    evidence_path = (
        BASE_DIR
        / "docs"
        / "security"
        / "r2_s5"
        / "evidence"
        / "identity_benchmark_windows.json"
    )
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "identity-verification-benchmark-v2"
    assert payload["provenance"]["input_mode"] == "ephemeral_managed_identity"
    assert payload["iterations"] == 1_000
    assert payload["target_met"] is True
    assert payload["latency_ms"]["p95"] <= payload["target_p95_ms"]
    expected_sources = {
        "app/security/identity.py",
        "app/security/identity_benchmark.py",
        "scripts/benchmark_identity_verification.py",
    }
    assert set(payload["provenance"]["source_sha256"]) == expected_sources
    assert payload["provenance"]["source_sha256"] == {
        relative: hashlib.sha256((BASE_DIR / relative).read_bytes()).hexdigest()
        for relative in sorted(expected_sources)
    }
