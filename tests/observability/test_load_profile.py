from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import deque
from pathlib import Path
from threading import Lock

import pytest

import scripts.load_profile as load_profile
from scripts.load_profile import (
    DETAIL_FIELDS,
    LoadProfileConfig,
    parse_concurrency,
    percentile,
    run_load_profile,
)


SECRET_QUESTION = "PROJECT NIGHTFALL password=question-secret"
SECRET_ANSWER = "D:/vault/answer-secret"


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict,
        *,
        request_id: str | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = {"X-Request-ID": request_id} if request_id else {}

    def json(self) -> dict:
        return self._payload


class FakeHttp:
    def __init__(self, chat_results: list[FakeResponse | Exception] | None = None) -> None:
        self._chat_results = deque(chat_results or [])
        self._lock = Lock()
        self.calls: list[tuple[str, str]] = []
        self.chat_calls = 0
        self.metrics_calls = 0

    def __call__(self, method: str, url: str, payload: dict | None, timeout: float):
        path = url.split("http://service.test", 1)[-1]
        with self._lock:
            self.calls.append((method, path))
            if path == "/observability/metrics":
                self.metrics_calls += 1
                return FakeResponse(
                    200,
                    {
                        "requests": {
                            "in_flight": 0,
                            "total": 10 * self.metrics_calls,
                            "errors": 0,
                            "by_route": {},
                        },
                        "models": {
                            "calls": 2 * self.metrics_calls,
                            "retries": 0,
                            "errors": 0,
                        },
                        "process": {"rss_bytes": 123_456 + self.metrics_calls},
                    },
                )
            if path == "/health/live":
                return FakeResponse(200, {"status": "alive"})
            if path == "/health/ready":
                return FakeResponse(
                    200,
                    {
                        "status": "ready",
                        "checks": {
                            "database": "ok",
                            "index": "ok",
                            "models": "ok",
                        },
                        "retrieved_guard": "ready",
                        "index": {
                            "run_id": "test-index",
                            "chunk_count": 64,
                            "embedding_model": "bge-m3",
                            "embedding_dimension": 1024,
                            "build_duration_ms": 100,
                            "index_size_bytes": 1000,
                        },
                        "checked_at_utc": "2026-07-17T00:00:00Z",
                    },
                )
            if path == "/agent/v2/chat":
                self.chat_calls += 1
                result = self._chat_results.popleft() if self._chat_results else FakeResponse(
                    200,
                    {
                        "mode": "answered",
                        "answer": SECRET_ANSWER,
                        "sources": [{"preview": SECRET_ANSWER}],
                        "trace": {"request_id": f"trace-{self.chat_calls}"},
                    },
                    request_id=f"req-{self.chat_calls}",
                )
                if isinstance(result, Exception):
                    raise result
                return result
        raise AssertionError(f"unexpected request: {method} {path}")


def make_config(tmp_path: Path, **overrides) -> LoadProfileConfig:
    values = {
        "base_url": "http://service.test",
        "profile": "demo",
        "concurrency": (1, 2),
        "requests_per_level": 2,
        "run_id": "test-run",
        "out_dir": tmp_path / "load_runs",
        "timeout_seconds": 1.0,
    }
    values.update(overrides)
    return LoadProfileConfig(**values)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_concurrency_parser_and_percentile_are_deterministic() -> None:
    assert parse_concurrency("1,5,10") == (1, 5, 10)
    assert percentile([40.0, 10.0, 30.0, 20.0], 0.5) == 20.0
    assert percentile([40.0, 10.0, 30.0, 20.0], 0.95) == 40.0

    for invalid in ["", "0", "1,-2", "1,1", "1,two"]:
        with pytest.raises(argparse.ArgumentTypeError):
            parse_concurrency(invalid)


def test_profile_separates_cold_and_warm_and_never_persists_content(tmp_path) -> None:
    fake = FakeHttp()
    target = run_load_profile(make_config(tmp_path), http_call=fake)

    summary = read_json(target / "summary.json")
    assert summary["cold"]["requests"] == 1
    assert [level["concurrency"] for level in summary["warm"]] == [1, 2]
    assert [level["requests"] for level in summary["warm"]] == [2, 2]
    assert summary["totals"] == {"requests": 5, "successful": 5, "failed": 0}
    assert fake.chat_calls == 5

    with (target / "details.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert tuple(rows[0]) == DETAIL_FIELDS
    assert [row["phase"] for row in rows] == ["cold", "warm", "warm", "warm", "warm"]
    assert {row["concurrency"] for row in rows[1:]} == {"1", "2"}

    serialized = "\n".join(
        path.read_text(encoding="utf-8-sig", errors="ignore")
        for path in target.iterdir()
        if path.is_file()
    )
    for forbidden in [
        SECRET_QUESTION,
        SECRET_ANSWER,
        "question-secret",
        "answer-secret",
        "sources",
        "preview",
    ]:
        assert forbidden not in serialized


def test_failures_are_counted_with_safe_codes_only(tmp_path) -> None:
    fake = FakeHttp(
        [
            FakeResponse(200, {"mode": "not_found"}, request_id="req-cold"),
            FakeResponse(200, {"mode": "system"}, request_id="req-system"),
            FakeResponse(
                503,
                {
                    "error": {
                        "code": "model_unavailable",
                        "message": "password=never-show D:/vault",
                    }
                },
                request_id="req-503",
            ),
            RuntimeError("password=socket-secret D:/private"),
        ]
    )
    target = run_load_profile(
        make_config(tmp_path, concurrency=(1,), requests_per_level=3),
        http_call=fake,
    )

    summary = read_json(target / "summary.json")
    assert summary["totals"] == {"requests": 4, "successful": 1, "failed": 3}
    with (target / "details.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["error_code"] for row in rows] == [
        "",
        "agent_system",
        "model_unavailable",
        "request_error",
    ]
    serialized = json.dumps(summary) + (target / "details.csv").read_text(
        encoding="utf-8-sig"
    )
    assert "never-show" not in serialized
    assert "socket-secret" not in serialized
    assert "vault" not in serialized


def test_existing_run_is_refused_before_any_http_call(tmp_path) -> None:
    config = make_config(tmp_path)
    target = config.out_dir / config.run_id
    target.mkdir(parents=True)
    fake = FakeHttp()

    with pytest.raises(FileExistsError, match="already exists"):
        run_load_profile(config, http_call=fake)

    assert fake.calls == []


def test_staging_directory_is_cleaned_when_artifact_write_fails(
    monkeypatch,
    tmp_path,
) -> None:
    config = make_config(tmp_path, concurrency=(1,), requests_per_level=1)

    def fail_write(*args, **kwargs):
        raise OSError("simulated write failure")

    monkeypatch.setattr(load_profile, "_write_json", fail_write)
    with pytest.raises(OSError, match="simulated write failure"):
        run_load_profile(config, http_call=FakeHttp())

    assert not (config.out_dir / config.run_id).exists()
    assert list(config.out_dir.glob(f".{config.run_id}.staging-*")) == []


def test_manifest_hashes_match_immutable_artifacts(tmp_path) -> None:
    target = run_load_profile(
        make_config(tmp_path, concurrency=(1,), requests_per_level=1),
        http_call=FakeHttp(),
    )
    manifest = read_json(target / "manifest.json")

    assert set(manifest["artifacts"]) == {"summary.json", "details.csv"}
    for name, evidence in manifest["artifacts"].items():
        payload = (target / name).read_bytes()
        assert evidence == {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
        }
    assert manifest["readiness"]["index"]["run_id"] == "test-index"
    assert manifest["metrics"]["before"]["models"]["calls"] == 2
    assert manifest["metrics"]["after"]["models"]["calls"] == 4
