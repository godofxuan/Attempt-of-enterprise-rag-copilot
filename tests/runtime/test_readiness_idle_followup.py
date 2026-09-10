"""Reproduce expiry during periodic refresh without real sockets or sleeps."""

import threading

from app.config import Settings
from app.runtime.resources import RuntimeResources


def test_periodic_refresh_starts_before_snapshot_expires_without_requests():
    clock = [0.0]
    resource = RuntimeResources(
        Settings(_env_file=None, readiness_ttl_seconds=10), clock=lambda: clock[0]
    )
    resource.started = True
    resource._database_initialization_attempted = True
    resource._stop_refresh = threading.Event()
    waits = []
    observed = []
    calls = []

    class Wakeup:
        def wait(self, timeout):
            waits.append(timeout)
            clock[0] += timeout

        def clear(self):
            pass

    resource._refresh_wakeup = Wakeup()

    def collect():
        calls.append(1)
        if len(calls) == 2:
            # A request arrives during the next probe, before it publishes.
            observed.append(resource.refresh_if_stale().status)
            resource._stop_refresh.set()
        return resource._unavailable_snapshot().model_copy(update={"status": "ready"})

    resource._collect_snapshot = collect
    resource._background_refresh_loop()
    assert observed == ["ready"]
    assert waits == [5.0]
