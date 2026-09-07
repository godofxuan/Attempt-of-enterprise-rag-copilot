"""Mechanism tests, not GPU throughput measurements."""

import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from threading import Event
from types import SimpleNamespace

import pytest

from app.retrieval.local_cross_encoder import LocalCrossEncoder


def fake_inference_modules(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(inference_mode=nullcontext))
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(AutoModelForSequenceClassification=None, AutoTokenizer=None),
    )


def test_failure_releases_capacity_without_caching_a_result(tmp_path, monkeypatch):
    fake_inference_modules(monkeypatch)
    scorer = LocalCrossEncoder(tmp_path)
    scorer._model = object()
    calls = []

    def failing_tokenizer(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("injected inference failure")

    scorer._tokenizer = failing_tokenizer
    for _ in range(2):
        with pytest.raises(RuntimeError, match="injected"):
            scorer("query", ("evidence",))
    assert len(calls) == 2
    assert not scorer._lock.locked()


def test_four_requests_allow_only_one_inflight_inference(tmp_path, monkeypatch):
    fake_inference_modules(monkeypatch)
    scorer = LocalCrossEncoder(tmp_path)
    scorer._model = object()
    entered, release = Event(), Event()
    calls = []

    def blocked_tokenizer(*args, **kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(5), "test failed to release owner"
        raise RuntimeError("owner finished")

    scorer._tokenizer = blocked_tokenizer
    with ThreadPoolExecutor(max_workers=4) as pool:
        owner = pool.submit(scorer, "query", ("evidence",))
        try:
            assert entered.wait(2)
            waiters = [pool.submit(scorer, "query", ("evidence",)) for _ in range(3)]
            for waiter in waiters:
                with pytest.raises(TimeoutError, match="capacity exhausted"):
                    waiter.result(timeout=2)
            assert len(calls) == 1
        finally:
            release.set()
        with pytest.raises(RuntimeError, match="owner finished"):
            owner.result(timeout=2)
    assert not scorer._lock.locked()


def test_candidate_limit_rejects_before_model_loading(tmp_path):
    scorer = LocalCrossEncoder(tmp_path)
    with pytest.raises(ValueError, match="at most 50"):
        scorer("query", ("evidence",) * 51)
    assert scorer._model is None
    assert scorer("query", ()) == []
