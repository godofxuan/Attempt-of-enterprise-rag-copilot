import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.external_datasets.finqa import (
    FINQA_REVISION,
    FINQA_TEST_SHA256,
)
from scripts import eval_finqa


def _args(protocol: Path, *, mode: str = "oracle") -> argparse.Namespace:
    return argparse.Namespace(
        freeze_protocol=protocol,
        sample_count=100,
        sample_seed="finqa-test-holdout-v1",
        retrieval_mode=mode,
        top_k=5,
        timeout_seconds=120.0,
        max_attempts=2,
    )


def _write_protocol(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "status": "FROZEN",
                "dataset_revision": FINQA_REVISION,
                "test_sha256": FINQA_TEST_SHA256,
                "sample_count": 100,
                "sample_seed": "finqa-test-holdout-v1",
                "retrieval_modes": ["oracle", "hybrid"],
                "top_k": 5,
                "answer_model": "qwen3:8b",
                "timeout_seconds": 120.0,
                "max_attempts": 2,
            }
        ),
        encoding="utf-8",
    )


def test_finqa_test_protocol_accepts_only_frozen_arms(tmp_path: Path) -> None:
    protocol = tmp_path / "protocol.json"
    _write_protocol(protocol)

    eval_finqa._validate_frozen_test_configuration(
        _args(protocol),
        "qwen3:8b",
    )
    eval_finqa._validate_frozen_test_configuration(
        _args(protocol, mode="hybrid"),
        "qwen3:8b",
    )

    with pytest.raises(ValueError, match="retrieval mode is not frozen"):
        eval_finqa._validate_frozen_test_configuration(
            _args(protocol, mode="bm25"),
            "qwen3:8b",
        )


def test_finqa_test_protocol_rejects_post_freeze_parameter_change(
    tmp_path: Path,
) -> None:
    protocol = tmp_path / "protocol.json"
    _write_protocol(protocol)
    args = _args(protocol)
    args.sample_count = 101

    with pytest.raises(ValueError, match="does not match frozen protocol"):
        eval_finqa._validate_frozen_test_configuration(
            args,
            "qwen3:8b",
        )


def test_finqa_model_identity_uses_chat_transport_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = {}

    class Response:
        def json(self):
            return {
                "models": [
                    {
                        "name": "qwen3:8b",
                        "digest": "a" * 64,
                    }
                ]
            }

    def perform(send, **kwargs):
        observed.update(kwargs)
        return SimpleNamespace(response=Response())

    monkeypatch.setattr(eval_finqa, "perform_model_request", perform)
    monkeypatch.setattr(
        eval_finqa.requests,
        "Session",
        lambda: SimpleNamespace(trust_env=True),
    )
    settings = SimpleNamespace(
        llm_base_url="http://127.0.0.1:11434/v1",
        model_request_timeout_seconds=12,
        model_max_attempts=2,
        model_retry_backoff_ms=100,
    )

    digest = eval_finqa._ollama_model_digest(settings, "qwen3:8b")

    assert digest == "a" * 64
    assert observed["operation"] == "chat"
