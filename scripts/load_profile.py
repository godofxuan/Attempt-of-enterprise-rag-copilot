from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlparse

import requests

from app.observability.metrics import nearest_rank_percentile
from app.runtime.resources import ReadinessSnapshot


DETAIL_FIELDS = (
    "phase",
    "sequence",
    "concurrency",
    "status_code",
    "success",
    "mode",
    "request_id",
    "latency_ms",
    "error_code",
)
SAFE_MODES = frozenset(
    {"answered", "unsafe", "permission", "not_found", "system", "budget"}
)
SUCCESS_MODES = frozenset({"answered", "unsafe", "permission", "not_found"})
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")

DEMO_PAYLOAD = {
    "question": "当前制度每周最多允许远程办公几天？",
    "user_context": {
        "user_id": "load-demo-employee",
        "tenant_id": "starbridge-cn",
        "region": "cn",
        "groups": ["all_employees"],
        "roles": [],
    },
    "top_k": 5,
}
PROFILE_PAYLOADS = {"demo": DEMO_PAYLOAD}


class ResponseLike(Protocol):
    status_code: int
    headers: Mapping[str, str]

    def json(self) -> Any: ...


HttpCall = Callable[[str, str, dict | None, float], ResponseLike]


class LoadProfileError(RuntimeError):
    pass


@dataclass(frozen=True)
class LoadProfileConfig:
    base_url: str
    profile: str
    concurrency: tuple[int, ...]
    requests_per_level: int
    run_id: str
    out_dir: Path
    timeout_seconds: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", normalize_base_url(self.base_url))
        object.__setattr__(self, "out_dir", Path(self.out_dir))
        if self.profile not in PROFILE_PAYLOADS:
            raise ValueError("unknown load profile")
        if not self.concurrency or any(value < 1 for value in self.concurrency):
            raise ValueError("concurrency levels must be positive")
        if len(set(self.concurrency)) != len(self.concurrency):
            raise ValueError("concurrency levels must be unique")
        if self.requests_per_level < 1:
            raise ValueError("requests per level must be positive")
        if not RUN_ID_PATTERN.fullmatch(self.run_id):
            raise ValueError("run ID contains unsupported characters")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout must be positive")


@dataclass(frozen=True)
class RequestDetail:
    phase: str
    sequence: int
    concurrency: int
    status_code: int | None
    success: bool
    mode: str | None
    request_id: str | None
    latency_ms: float
    error_code: str | None

    def csv_row(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "sequence": self.sequence,
            "concurrency": self.concurrency,
            "status_code": self.status_code if self.status_code is not None else "",
            "success": str(self.success).lower(),
            "mode": self.mode or "",
            "request_id": self.request_id or "",
            "latency_ms": f"{self.latency_ms:.3f}",
            "error_code": self.error_code or "",
        }


class RequestsHttpClient:
    def __init__(self) -> None:
        self._local = threading.local()

    def __call__(
        self,
        method: str,
        url: str,
        payload: dict | None,
        timeout: float,
    ) -> requests.Response:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.trust_env = False
            self._local.session = session
        return session.request(
            method,
            url,
            json=payload,
            timeout=timeout,
        )


def normalize_base_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base URL must be an absolute HTTP URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("base URL cannot contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("base URL cannot contain a path")
    return f"{parsed.scheme}://{parsed.netloc}"


def parse_concurrency(value: str) -> tuple[int, ...]:
    try:
        parts = [part.strip() for part in value.split(",")]
        if not parts or any(not part for part in parts):
            raise ValueError
        levels = tuple(int(part) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "concurrency must be comma-separated positive integers"
        ) from exc
    if any(level < 1 for level in levels):
        raise argparse.ArgumentTypeError("concurrency levels must be positive")
    if len(set(levels)) != len(levels):
        raise argparse.ArgumentTypeError("concurrency levels must be unique")
    return levels


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be positive") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def percentile(values: list[float], quantile: float) -> float | None:
    return nearest_rank_percentile(values, quantile)


def run_load_profile(
    config: LoadProfileConfig,
    *,
    http_call: HttpCall | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> Path:
    target = config.out_dir / config.run_id
    if target.exists():
        raise FileExistsError(f"load run already exists: {config.run_id}")

    call = http_call or RequestsHttpClient()
    started_at = datetime.now(timezone.utc)
    liveness = _require_liveness(config, call)
    readiness = _require_readiness(config, call)
    metrics_before = _read_metrics(config, call)

    payload = PROFILE_PAYLOADS[config.profile]
    details: list[RequestDetail] = [
        _measure_request(
            config,
            call,
            payload,
            phase="cold",
            sequence=1,
            concurrency=1,
            clock=clock,
        )
    ]
    next_sequence = 2
    for level in config.concurrency:
        level_details = _run_warm_level(
            config,
            call,
            payload,
            concurrency=level,
            first_sequence=next_sequence,
            clock=clock,
        )
        details.extend(level_details)
        next_sequence += config.requests_per_level

    metrics_after = _read_metrics(config, call)
    completed_at = datetime.now(timezone.utc)
    summary = _build_summary(config, details, started_at, completed_at)
    manifest_base = {
        "schema_version": "load-manifest-v1",
        "run_id": config.run_id,
        "profile": config.profile,
        "started_at_utc": _utc_text(started_at),
        "completed_at_utc": _utc_text(completed_at),
        "configuration": {
            "concurrency": list(config.concurrency),
            "requests_per_level": config.requests_per_level,
            "timeout_seconds": config.timeout_seconds,
        },
        "liveness": liveness,
        "readiness": readiness,
        "metrics": {"before": metrics_before, "after": metrics_after},
    }
    return _write_run(target, details, summary, manifest_base)


def _run_warm_level(
    config: LoadProfileConfig,
    call: HttpCall,
    payload: dict,
    *,
    concurrency: int,
    first_sequence: int,
    clock: Callable[[], float],
) -> list[RequestDetail]:
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                _measure_request,
                config,
                call,
                payload,
                phase="warm",
                sequence=first_sequence + offset,
                concurrency=concurrency,
                clock=clock,
            )
            for offset in range(config.requests_per_level)
        ]
        return sorted(
            (future.result() for future in as_completed(futures)),
            key=lambda item: item.sequence,
        )


def _measure_request(
    config: LoadProfileConfig,
    call: HttpCall,
    payload: dict,
    *,
    phase: str,
    sequence: int,
    concurrency: int,
    clock: Callable[[], float],
) -> RequestDetail:
    started = clock()
    status_code: int | None = None
    mode: str | None = None
    request_id: str | None = None
    error_code: str | None = None
    success = False
    try:
        response = call(
            "POST",
            f"{config.base_url}/agent/v2/chat",
            payload,
            config.timeout_seconds,
        )
        status_code = int(response.status_code)
        request_id = _safe_request_id(response.headers)
        body = _safe_json(response)
        if 200 <= status_code < 300:
            candidate_mode = body.get("mode") if isinstance(body, dict) else None
            mode = candidate_mode if candidate_mode in SAFE_MODES else None
            if mode is None or request_id is None:
                error_code = "response_shape_error"
            elif mode in SUCCESS_MODES:
                success = True
            else:
                error_code = f"agent_{mode}"
        else:
            error_code = _safe_error_code(body)
    except Exception:
        error_code = "request_error"
    duration_ms = max(0.0, (clock() - started) * 1000.0)
    return RequestDetail(
        phase=phase,
        sequence=sequence,
        concurrency=concurrency,
        status_code=status_code,
        success=success,
        mode=mode,
        request_id=request_id,
        latency_ms=duration_ms,
        error_code=error_code,
    )


def _require_liveness(config: LoadProfileConfig, call: HttpCall) -> dict[str, Any]:
    try:
        response = call(
            "GET",
            f"{config.base_url}/health/live",
            None,
            config.timeout_seconds,
        )
        body = _safe_json(response)
        if response.status_code != 200 or body.get("status") != "alive":
            raise LoadProfileError("service liveness check failed")
        return {"status_code": 200, "status": "alive"}
    except LoadProfileError:
        raise
    except Exception as exc:
        raise LoadProfileError("service liveness check failed") from exc


def _require_readiness(config: LoadProfileConfig, call: HttpCall) -> dict[str, Any]:
    try:
        response = call(
            "GET",
            f"{config.base_url}/health/ready",
            None,
            config.timeout_seconds,
        )
        snapshot = ReadinessSnapshot.model_validate(_safe_json(response))
        if response.status_code != 200 or snapshot.status != "ready":
            raise LoadProfileError("service readiness check failed")
        return snapshot.model_dump(mode="json")
    except LoadProfileError:
        raise
    except Exception as exc:
        raise LoadProfileError("service readiness check failed") from exc


def _read_metrics(config: LoadProfileConfig, call: HttpCall) -> dict[str, Any]:
    try:
        response = call(
            "GET",
            f"{config.base_url}/observability/metrics",
            None,
            config.timeout_seconds,
        )
        if response.status_code != 200:
            raise LoadProfileError("metrics snapshot failed")
        return _safe_metrics(_safe_json(response))
    except LoadProfileError:
        raise
    except Exception as exc:
        raise LoadProfileError("metrics snapshot failed") from exc


def _safe_metrics(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise LoadProfileError("metrics snapshot failed")
    requests_data = payload.get("requests")
    models_data = payload.get("models")
    process_data = payload.get("process")
    if not all(isinstance(item, dict) for item in (requests_data, models_data, process_data)):
        raise LoadProfileError("metrics snapshot failed")
    return {
        "requests": {
            "in_flight": _nonnegative_int(requests_data.get("in_flight")),
            "total": _nonnegative_int(requests_data.get("total")),
            "errors": _nonnegative_int(requests_data.get("errors")),
        },
        "models": {
            "calls": _nonnegative_int(models_data.get("calls")),
            "retries": _nonnegative_int(models_data.get("retries")),
            "errors": _nonnegative_int(models_data.get("errors")),
        },
        "process": {"rss_bytes": _nullable_nonnegative_int(process_data.get("rss_bytes"))},
    }


def _nonnegative_int(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LoadProfileError("metrics snapshot failed")
    return value


def _nullable_nonnegative_int(value: Any) -> int | None:
    if value is None:
        return None
    return _nonnegative_int(value)


def _safe_json(response: ResponseLike) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_request_id(headers: Mapping[str, str]) -> str | None:
    candidate = next(
        (value for key, value in headers.items() if key.lower() == "x-request-id"),
        None,
    )
    if not isinstance(candidate, str) or not REQUEST_ID_PATTERN.fullmatch(candidate):
        return None
    return candidate


def _safe_error_code(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    candidate = error.get("code") if isinstance(error, dict) else None
    if isinstance(candidate, str) and ERROR_CODE_PATTERN.fullmatch(candidate):
        return candidate
    return "http_error"


def _build_summary(
    config: LoadProfileConfig,
    details: list[RequestDetail],
    started_at: datetime,
    completed_at: datetime,
) -> dict[str, Any]:
    cold = [item for item in details if item.phase == "cold"]
    warm = [
        _summarize(
            [
                item
                for item in details
                if item.phase == "warm" and item.concurrency == level
            ],
            concurrency=level,
        )
        for level in config.concurrency
    ]
    successful = sum(item.success for item in details)
    return {
        "schema_version": "load-summary-v1",
        "run_id": config.run_id,
        "profile": config.profile,
        "started_at_utc": _utc_text(started_at),
        "completed_at_utc": _utc_text(completed_at),
        "totals": {
            "requests": len(details),
            "successful": successful,
            "failed": len(details) - successful,
        },
        "cold": _summarize(cold, concurrency=1),
        "warm": warm,
    }


def _summarize(
    details: list[RequestDetail],
    *,
    concurrency: int,
) -> dict[str, Any]:
    latencies = [item.latency_ms for item in details]
    successful = sum(item.success for item in details)
    return {
        "concurrency": concurrency,
        "requests": len(details),
        "successful": successful,
        "failed": len(details) - successful,
        "latency_ms": {
            "mean": round(fmean(latencies), 3) if latencies else None,
            "p50": _rounded_percentile(latencies, 0.5),
            "p95": _rounded_percentile(latencies, 0.95),
            "min": round(min(latencies), 3) if latencies else None,
            "max": round(max(latencies), 3) if latencies else None,
        },
    }


def _rounded_percentile(values: list[float], quantile: float) -> float | None:
    result = percentile(values, quantile)
    return round(result, 3) if result is not None else None


def _write_run(
    target: Path,
    details: list[RequestDetail],
    summary: dict[str, Any],
    manifest_base: dict[str, Any],
) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".{target.name}.staging-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        _write_json(staging / "summary.json", summary)
        _write_csv(staging / "details.csv", details)
        artifacts = {
            name: _artifact_evidence(staging / name)
            for name in ("summary.json", "details.csv")
        }
        _write_json(
            staging / "manifest.json",
            {**manifest_base, "artifacts": artifacts},
        )
        if target.exists():
            raise FileExistsError(f"load run already exists: {target.name}")
        staging.rename(target)
        return target
    except Exception:
        if staging.exists() and staging.parent == target.parent:
            shutil.rmtree(staging)
        raise


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, details: list[RequestDetail]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DETAIL_FIELDS)
        writer.writeheader()
        writer.writerows(item.csv_row() for item in details)


def _artifact_evidence(path: Path) -> dict[str, int | str]:
    payload = path.read_bytes()
    return {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def default_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}_demo_load"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure the local Agentic RAG API and write immutable safe artifacts."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--profile", choices=sorted(PROFILE_PAYLOADS), default="demo")
    parser.add_argument("--concurrency", type=parse_concurrency, default=(1, 5, 10))
    parser.add_argument("--requests-per-level", type=positive_int, default=10)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--out-dir", type=Path, default=Path("load_runs"))
    parser.add_argument("--timeout-seconds", type=positive_float, default=30.0)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = LoadProfileConfig(
            base_url=args.base_url,
            profile=args.profile,
            concurrency=args.concurrency,
            requests_per_level=args.requests_per_level,
            run_id=args.run_id or default_run_id(),
            out_dir=args.out_dir,
            timeout_seconds=args.timeout_seconds,
        )
        target = run_load_profile(config)
    except (ValueError, FileExistsError, LoadProfileError) as exc:
        parser.error(str(exc))
    print(target)


if __name__ == "__main__":
    main()


__all__ = [
    "DETAIL_FIELDS",
    "LoadProfileConfig",
    "LoadProfileError",
    "build_parser",
    "parse_concurrency",
    "percentile",
    "run_load_profile",
]
