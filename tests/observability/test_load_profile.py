from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import deque
from email.message import Message
from pathlib import Path
from threading import Lock

import pytest
import requests

import scripts.load_profile as load_profile
from app.security.identity import IdentityConfigurationError
from app.security.private_fs import harden_private_directory
from scripts.load_profile import (
    DETAIL_FIELDS,
    LoadProfileConfig,
    RequestsHttpClient,
    parse_concurrency,
    percentile,
    resolve_environment_token_sources,
    run_load_profile,
)


SECRET_QUESTION = "PROJECT NIGHTFALL password=test-question-secret"
SECRET_ANSWER = "D:/vault/answer-secret"
USER_TOKEN = "dXNlcg.cGF5bG9hZA.c2lnbmF0dXJl"
OPERATOR_TOKEN = "b3BlcmF0b3I.cGF5bG9hZA.c2lnbmF0dXJl"


class RecordingTokenSource:
    def __init__(self, token: str) -> None:
        self._token = token
        self.calls = 0

    def get_token(self) -> str:
        self.calls += 1
        return self._token


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
        self.calls: list[tuple[str, str, dict[str, str], str]] = []
        self.chat_calls = 0
        self.metrics_calls = 0

    def __call__(
        self,
        method: str,
        url: str,
        payload: dict | None,
        timeout: float,
        headers: dict[str, str],
        identity_channel: str,
    ):
        path = url.split("http://127.0.0.1:8000", 1)[-1]
        with self._lock:
            self.calls.append((method, path, dict(headers), identity_channel))
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
                            "identity": "ok",
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
        "base_url": "http://127.0.0.1:8000",
        "profile": "demo",
        "concurrency": (1, 2),
        "requests_per_level": 2,
        "run_id": "test-run",
        "out_dir": tmp_path / "load_runs",
        "timeout_seconds": 1.0,
        "user_token_source": RecordingTokenSource(USER_TOKEN),
        "operator_token_source": RecordingTokenSource(OPERATOR_TOKEN),
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
            RuntimeError("password=test-socket-secret D:/private"),
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


def test_chat_and_metrics_use_separate_tokens_resolved_for_every_call(tmp_path) -> None:
    user = RecordingTokenSource(USER_TOKEN)
    operator = RecordingTokenSource(OPERATOR_TOKEN)
    fake = FakeHttp()

    run_load_profile(
        make_config(
            tmp_path,
            concurrency=(1,),
            requests_per_level=1,
            user_token_source=user,
            operator_token_source=operator,
        ),
        http_call=fake,
    )

    chat_calls = [call for call in fake.calls if call[1] == "/agent/v2/chat"]
    metrics_calls = [
        call for call in fake.calls if call[1] == "/observability/metrics"
    ]
    public_calls = [
        call for call in fake.calls if call[1] in {"/health/live", "/health/ready"}
    ]
    assert user.calls == len(chat_calls) == 2
    assert operator.calls == len(metrics_calls) == 2
    assert all(
        call[2] == {"Authorization": f"Bearer {USER_TOKEN}"}
        and call[3] == "persona"
        for call in chat_calls
    )
    assert all(
        call[2] == {"Authorization": f"Bearer {OPERATOR_TOKEN}"}
        and call[3] == "operator"
        for call in metrics_calls
    )
    assert all(call[2] == {} and call[3] == "public" for call in public_calls)
    assert "user_context" not in load_profile.PROFILE_PAYLOADS["demo"]


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:8000",
        "http://[::1]:8000",
        "http://user@127.0.0.1:8000",
        "http://127.0.0.1:8000/path",
        "http://127.0.0.1:8000?next=evil",
        "http://127.0.0.1:8000#fragment",
        "https://127.0.0.1:8000",
        "http://127.0.0.2:8000",
        " http://127.0.0.1:8000",
    ],
)
def test_load_profile_rejects_non_numeric_loopback_base_url(
    tmp_path: Path,
    base_url: str,
) -> None:
    with pytest.raises(ValueError, match="base URL"):
        make_config(tmp_path, base_url=base_url)


def test_environment_token_sources_reject_missing_or_ambiguous_configuration(
    tmp_path: Path,
) -> None:
    user_file = tmp_path / "user.token"
    operator_file = tmp_path / "operator.token"
    user_file.write_text(USER_TOKEN, encoding="ascii")
    operator_file.write_text(OPERATOR_TOKEN, encoding="ascii")
    harden_private_directory(tmp_path)

    user, operator = resolve_environment_token_sources(
        {
            "RAG_BEARER_TOKEN_FILE": str(user_file),
            "RAG_OPERATOR_BEARER_TOKEN_FILE": str(operator_file),
        }
    )
    assert user.get_token() == USER_TOKEN
    assert operator.get_token() == OPERATOR_TOKEN

    for environ in [
        {},
        {
            "RAG_BEARER_TOKEN": USER_TOKEN,
            "RAG_BEARER_TOKEN_FILE": str(user_file),
            "RAG_OPERATOR_BEARER_TOKEN": OPERATOR_TOKEN,
        },
        {
            "RAG_BEARER_TOKEN": USER_TOKEN,
            "RAG_OPERATOR_BEARER_TOKEN": OPERATOR_TOKEN,
            "RAG_OPERATOR_BEARER_TOKEN_FILE": str(operator_file),
        },
    ]:
        with pytest.raises(ValueError, match="exactly one"):
            resolve_environment_token_sources(environ)


def test_environment_token_sources_reject_equal_role_credentials(
    tmp_path: Path,
    capsys,
) -> None:
    user_file = tmp_path / "user.token"
    operator_file = tmp_path / "operator.token"
    user_file.write_text(USER_TOKEN, encoding="ascii")
    operator_file.write_text(USER_TOKEN, encoding="ascii")
    harden_private_directory(tmp_path)

    with pytest.raises(IdentityConfigurationError) as exc_info:
        resolve_environment_token_sources(
            {
                "RAG_BEARER_TOKEN_FILE": str(user_file),
                "RAG_OPERATOR_BEARER_TOKEN_FILE": str(operator_file),
            }
        )

    captured = capsys.readouterr()
    assert str(exc_info.value) == "user and operator bearer tokens must differ"
    assert USER_TOKEN not in captured.out
    assert USER_TOKEN not in captured.err


def test_requests_http_client_isolates_channels_and_rejects_response_cookies(
    monkeypatch,
) -> None:
    sessions: list[object] = []

    class FakeSession:
        def __init__(self) -> None:
            self.cookies = requests.cookies.RequestsCookieJar()
            self.trust_env = True
            self.calls: list[dict] = []
            sessions.append(self)

        def request(self, method: str, url: str, **kwargs):
            prepared = requests.Request(
                method,
                url,
                headers=kwargs.get("headers"),
            ).prepare()
            self.calls.append(
                {
                    "method": method,
                    "url": url,
                    "outgoing_cookie": requests.cookies.get_cookie_header(
                        self.cookies,
                        prepared,
                    ),
                    **kwargs,
                }
            )
            response_headers = Message()
            response_headers.add_header(
                "Set-Cookie",
                "server_cookie=credential; Path=/; HttpOnly",
            )
            self.cookies.extract_cookies(
                requests.cookies.MockResponse(response_headers),
                requests.cookies.MockRequest(prepared),
            )
            return FakeResponse(200, {})

    monkeypatch.setattr(load_profile.requests, "Session", FakeSession)
    client = RequestsHttpClient()

    client(
        "GET",
        "http://127.0.0.1:8000/health/live",
        None,
        1.0,
        {},
        "public",
    )
    client(
        "POST",
        "http://127.0.0.1:8000/agent/v2/chat",
        {},
        1.0,
        {"Authorization": f"Bearer {USER_TOKEN}"},
        "persona",
    )
    client(
        "GET",
        "http://127.0.0.1:8000/observability/metrics",
        None,
        1.0,
        {"Authorization": f"Bearer {OPERATOR_TOKEN}"},
        "operator",
    )
    client(
        "POST",
        "http://127.0.0.1:8000/agent/v2/chat",
        {},
        1.0,
        {"Authorization": f"Bearer {USER_TOKEN}"},
        "persona",
    )

    assert len(sessions) == 3
    assert sorted(len(session.calls) for session in sessions) == [1, 1, 2]
    assert all(session.trust_env is False for session in sessions)
    assert all(
        call["allow_redirects"] is False
        and call["outgoing_cookie"] is None
        for session in sessions
        for call in session.calls
    )
    assert all(not session.cookies for session in sessions)


def test_tokens_never_enter_load_artifacts(tmp_path) -> None:
    target = run_load_profile(
        make_config(tmp_path, concurrency=(1,), requests_per_level=1),
        http_call=FakeHttp(),
    )

    serialized = b"\n".join(path.read_bytes() for path in target.iterdir())
    assert USER_TOKEN.encode() not in serialized
    assert OPERATOR_TOKEN.encode() not in serialized
