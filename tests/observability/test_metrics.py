from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.observability.metrics import (
    MetricsRegistry,
    nearest_rank_percentile,
    process_peak_rss_bytes,
    process_rss_bytes,
)


def test_nearest_rank_percentile_is_deterministic() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 100.0]

    assert nearest_rank_percentile(values, 0.5) == 3.0
    assert nearest_rank_percentile(values, 0.95) == 100.0
    assert nearest_rank_percentile([], 0.95) is None


def test_peak_rss_is_available_and_not_below_current_or_recorded_rss() -> None:
    current = process_rss_bytes()
    peak = process_peak_rss_bytes()

    assert current is not None
    assert peak is not None
    assert peak >= current


def test_metrics_track_request_status_latency_and_model_counters() -> None:
    registry = MetricsRegistry(
        latency_buffer_size=10,
        allowed_routes={"/agent/v2/chat"},
        memory_provider=lambda: 123_456,
    )

    registry.request_started()
    registry.request_finished(
        method="POST",
        route="/agent/v2/chat",
        status_code=200,
        duration_ms=10.0,
        model_calls=2,
        model_retries=1,
        model_errors=0,
    )
    registry.request_started()
    registry.request_finished(
        method="POST",
        route="/agent/v2/chat",
        status_code=503,
        duration_ms=30.0,
        model_calls=1,
        model_retries=0,
        model_errors=1,
    )

    snapshot = registry.snapshot()
    route = snapshot["requests"]["by_route"]["POST /agent/v2/chat"]
    assert snapshot["requests"]["in_flight"] == 0
    assert snapshot["requests"]["total"] == 2
    assert snapshot["requests"]["errors"] == 1
    assert route["status"] == {"2xx": 1, "5xx": 1}
    assert route["latency_ms"]["count"] == 2
    assert route["latency_ms"]["p50"] == 10.0
    assert route["latency_ms"]["p95"] == 30.0
    assert snapshot["models"] == {"calls": 3, "retries": 1, "errors": 1}
    assert snapshot["process"]["rss_bytes"] == 123_456


def test_metrics_bound_samples_and_collapse_unknown_routes() -> None:
    registry = MetricsRegistry(
        latency_buffer_size=2,
        allowed_routes={"/health/live"},
        memory_provider=lambda: None,
    )
    for duration in [1.0, 2.0, 100.0]:
        registry.request_started()
        registry.request_finished(
            method="GET",
            route="/private/secret-value",
            status_code=404,
            duration_ms=duration,
        )

    snapshot = registry.snapshot()
    assert list(snapshot["requests"]["by_route"]) == ["GET __unmatched__"]
    stats = snapshot["requests"]["by_route"]["GET __unmatched__"]["latency_ms"]
    assert stats["count"] == 3
    assert stats["sample_count"] == 2
    assert stats["p50"] == 2.0
    assert stats["p95"] == 100.0
    assert snapshot["process"]["rss_bytes"] is None


def test_metrics_updates_are_thread_safe() -> None:
    registry = MetricsRegistry(
        latency_buffer_size=100,
        allowed_routes={"/health/live"},
        memory_provider=lambda: 1,
    )

    def record(_: int) -> None:
        registry.request_started()
        registry.request_finished(
            method="GET",
            route="/health/live",
            status_code=200,
            duration_ms=1.0,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(record, range(100)))

    snapshot = registry.snapshot()
    assert snapshot["requests"]["total"] == 100
    assert snapshot["requests"]["in_flight"] == 0
    assert snapshot["requests"]["errors"] == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows process API regression")
def test_windows_process_rss_probe_returns_a_positive_value() -> None:
    rss = process_rss_bytes()

    assert isinstance(rss, int)
    assert rss > 0
