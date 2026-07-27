from __future__ import annotations

import argparse
import http.client
import json
import time
from urllib.parse import urlsplit


_MAX_RESPONSE_BYTES = 65_536


def _connection(base_url: str, timeout_seconds: float) -> http.client.HTTPConnection:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("deployment probe requires a numeric IPv4 loopback URL")
    return http.client.HTTPConnection(
        "127.0.0.1",
        parsed.port or 80,
        timeout=timeout_seconds,
    )


def _get_json(
    base_url: str,
    path: str,
    *,
    timeout_seconds: float,
) -> tuple[int, dict[str, object]]:
    connection = _connection(base_url, timeout_seconds)
    try:
        connection.request("GET", path, headers={"Accept": "application/json"})
        response = connection.getresponse()
        payload = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(payload) > _MAX_RESPONSE_BYTES:
            raise RuntimeError("deployment probe response exceeds size limit")
        decoded = json.loads(payload.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise RuntimeError("deployment probe response must be a JSON object")
        return response.status, decoded
    finally:
        connection.close()


def probe_deployment(
    base_url: str,
    *,
    deadline_seconds: float,
    request_timeout_seconds: float,
    expected_index_run_id: str | None = None,
) -> dict[str, object]:
    if not 0 < deadline_seconds <= 300:
        raise ValueError("probe deadline must be between 0 and 300 seconds")
    if not 0 < request_timeout_seconds <= 30:
        raise ValueError("probe request timeout must be between 0 and 30 seconds")
    validation_connection = _connection(base_url, request_timeout_seconds)
    validation_connection.close()
    deadline = time.monotonic() + deadline_seconds
    last_error = "readiness was not attempted"
    liveness_seen = False
    while time.monotonic() < deadline:
        try:
            live_status, live = _get_json(
                base_url,
                "/health/live",
                timeout_seconds=request_timeout_seconds,
            )
            liveness_seen = live_status == 200 and live.get("status") == "alive"
            if not liveness_seen:
                last_error = "liveness contract failed"
            else:
                ready_status, ready = _get_json(
                    base_url,
                    "/health/ready",
                    timeout_seconds=request_timeout_seconds,
                )
                index = ready.get("index")
                index_matches = (
                    expected_index_run_id is None
                    or (
                        isinstance(index, dict)
                        and index.get("run_id") == expected_index_run_id
                    )
                )
                if (
                    ready_status == 200
                    and ready.get("status") == "ready"
                    and index_matches
                ):
                    return {
                        "index_run_id": (
                            index.get("run_id")
                            if isinstance(index, dict)
                            else None
                        ),
                        "liveness": "alive",
                        "readiness": "ready",
                    }
                last_error = "readiness contract failed"
        except (
            ConnectionError,
            http.client.HTTPException,
            json.JSONDecodeError,
            OSError,
            RuntimeError,
            UnicodeDecodeError,
            ValueError,
        ) as exc:
            last_error = str(exc)
        time.sleep(0.2)
    state = "alive" if liveness_seen else "unavailable"
    raise RuntimeError(
        f"deployment probe deadline exceeded; liveness={state}; {last_error}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe a loopback-only deployed RAG API."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--deadline-seconds", type=float, default=90.0)
    parser.add_argument("--request-timeout-seconds", type=float, default=2.0)
    parser.add_argument("--expected-index-run-id", default=None)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = probe_deployment(
            args.base_url,
            deadline_seconds=args.deadline_seconds,
            request_timeout_seconds=args.request_timeout_seconds,
            expected_index_run_id=args.expected_index_run_id,
        )
    except (RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()


__all__ = ["build_parser", "main", "probe_deployment"]
