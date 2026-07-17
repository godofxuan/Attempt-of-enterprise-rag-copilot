from __future__ import annotations

import math
import os
from collections import Counter, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from threading import Lock
from typing import Any


MemoryProvider = Callable[[], int | None]


def nearest_rank_percentile(values: Iterable[float], percentile: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if percentile <= 0 or percentile > 1:
        raise ValueError("percentile must be in (0, 1]")
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


@dataclass
class _LatencySeries:
    max_samples: int
    count: int = 0
    total: float = 0.0
    samples: deque[float] = field(init=False)

    def __post_init__(self) -> None:
        self.samples = deque(maxlen=self.max_samples)

    def observe(self, value: float) -> None:
        safe = max(0.0, float(value))
        self.count += 1
        self.total += safe
        self.samples.append(safe)

    def snapshot(self) -> dict[str, int | float | None]:
        return {
            "count": self.count,
            "sample_count": len(self.samples),
            "sum": self.total,
            "p50": nearest_rank_percentile(self.samples, 0.5),
            "p95": nearest_rank_percentile(self.samples, 0.95),
        }


@dataclass
class _RouteMetrics:
    latency: _LatencySeries
    status: Counter[str] = field(default_factory=Counter)


class MetricsRegistry:
    def __init__(
        self,
        *,
        latency_buffer_size: int,
        allowed_routes: set[str] | frozenset[str],
        memory_provider: MemoryProvider | None = None,
    ) -> None:
        if latency_buffer_size < 1:
            raise ValueError("latency_buffer_size must be positive")
        self._latency_buffer_size = latency_buffer_size
        self._allowed_routes = frozenset(allowed_routes)
        self._memory_provider = memory_provider or process_rss_bytes
        self._lock = Lock()
        self._in_flight = 0
        self._total = 0
        self._errors = 0
        self._model_calls = 0
        self._model_retries = 0
        self._model_errors = 0
        self._routes: dict[str, _RouteMetrics] = {}

    def request_started(self) -> None:
        with self._lock:
            self._in_flight += 1

    def normalize_route(self, route: str) -> str:
        return route if route in self._allowed_routes else "__unmatched__"

    def request_finished(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_ms: float,
        model_calls: int = 0,
        model_retries: int = 0,
        model_errors: int = 0,
    ) -> None:
        safe_route = self.normalize_route(route)
        route_key = f"{method.upper()} {safe_route}"
        status_class = f"{status_code // 100}xx"
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            self._total += 1
            self._errors += int(status_code >= 400)
            self._model_calls += max(0, model_calls)
            self._model_retries += max(0, model_retries)
            self._model_errors += max(0, model_errors)
            metrics = self._routes.get(route_key)
            if metrics is None:
                metrics = _RouteMetrics(
                    latency=_LatencySeries(self._latency_buffer_size)
                )
                self._routes[route_key] = metrics
            metrics.status[status_class] += 1
            metrics.latency.observe(duration_ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            routes = {
                key: {
                    "status": dict(sorted(value.status.items())),
                    "latency_ms": value.latency.snapshot(),
                }
                for key, value in sorted(self._routes.items())
            }
            payload = {
                "requests": {
                    "in_flight": self._in_flight,
                    "total": self._total,
                    "errors": self._errors,
                    "by_route": routes,
                },
                "models": {
                    "calls": self._model_calls,
                    "retries": self._model_retries,
                    "errors": self._model_errors,
                },
            }
        try:
            rss = self._memory_provider()
        except Exception:
            rss = None
        payload["process"] = {"rss_bytes": rss}
        return payload


def process_rss_bytes() -> int | None:
    if os.name == "nt":
        return _windows_rss_bytes()
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(usage * 1024)
    except Exception:
        return None


def _windows_rss_bytes() -> int | None:
    try:
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        get_current_process = kernel32.GetCurrentProcess
        get_current_process.argtypes = []
        get_current_process.restype = wintypes.HANDLE
        get_process_memory_info = psapi.GetProcessMemoryInfo
        get_process_memory_info.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        get_process_memory_info.restype = wintypes.BOOL
        process = get_current_process()
        success = get_process_memory_info(
            process,
            ctypes.byref(counters),
            counters.cb,
        )
        return int(counters.WorkingSetSize) if success else None
    except Exception:
        return None


__all__ = [
    "MetricsRegistry",
    "nearest_rank_percentile",
    "process_rss_bytes",
]
