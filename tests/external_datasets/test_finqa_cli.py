import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.external_datasets.finqa import (
    FINQA_REVISION,
    FINQA_TEST_SHA256,
)
from scripts import eval_finqa


def test_repository_finqa_holdout_protocol_v2_is_source_bound() -> None:
    payload = json.loads(
        eval_finqa.DEFAULT_FREEZE_PROTOCOL.read_text(encoding="utf-8")
    )

    assert payload["schema_version"] == "finqa_holdout_protocol_v2"
    assert payload["status"] == "FROZEN"
    assert payload["test_split_structurally_validated_before_v2_freeze"] is True
    assert payload["test_metrics_observed_before_v2_freeze"] is False
    assert payload["model_generation_calls_before_v2_freeze"] == 0
    assert payload["sample_count"] == 100
    assert payload["top_k"] == 10
    eval_finqa._validate_frozen_source_hashes(payload)


def _args(protocol: Path, *, mode: str = "oracle") -> argparse.Namespace:
    return argparse.Namespace(
        freeze_protocol=protocol,
        sample_count=100,
        sample_seed="finqa-test-holdout-v1",
        retrieval_mode=mode,
        top_k=5,
        timeout_seconds=120.0,
        max_attempts=2,
        answer_strategy="program",
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
                "answer_strategy": "program",
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


def test_finqa_test_protocol_rejects_answer_strategy_change(
    tmp_path: Path,
) -> None:
    protocol = tmp_path / "protocol.json"
    _write_protocol(protocol)
    args = _args(protocol)
    args.answer_strategy = "direct"

    with pytest.raises(ValueError, match="does not match frozen protocol"):
        eval_finqa._validate_frozen_test_configuration(
            args,
            "qwen3:8b",
        )


def test_finqa_cli_defaults_to_program_answer_strategy() -> None:
    args = eval_finqa.build_parser().parse_args(["--run-id", "dev-run"])

    assert args.answer_strategy == "program"


def test_finqa_frozen_source_hashes_reject_code_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "app" / "scorer.py"
    source.parent.mkdir()
    source.write_text("frozen\n", encoding="utf-8")
    monkeypatch.setattr(
        eval_finqa,
        "FINQA_FROZEN_SOURCE_FILES",
        ("app/scorer.py",),
    )
    payload = {
        "source_file_sha256": {
            "app/scorer.py": hashlib.sha256(source.read_bytes()).hexdigest(),
        }
    }

    eval_finqa._validate_frozen_source_hashes(payload, root=tmp_path)
    source.write_text("changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="source hash mismatch"):
        eval_finqa._validate_frozen_source_hashes(payload, root=tmp_path)


def test_finqa_frozen_model_identity_rejects_digest_change() -> None:
    payload = {
        "answer_model_sha256": "a" * 64,
        "embedding_model": "bge-m3",
        "embedding_model_sha256": "b" * 64,
    }

    eval_finqa._validate_frozen_model_identity(
        payload,
        retrieval_mode="hybrid",
        answer_model_sha256="a" * 64,
        embedding_model="bge-m3",
        embedding_model_sha256="b" * 64,
    )
    with pytest.raises(ValueError, match="model identity"):
        eval_finqa._validate_frozen_model_identity(
            payload,
            retrieval_mode="hybrid",
            answer_model_sha256="c" * 64,
            embedding_model="bge-m3",
            embedding_model_sha256="b" * 64,
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
