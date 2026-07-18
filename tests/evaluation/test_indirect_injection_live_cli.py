from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.evaluation.indirect_injection_dataset import build_v1_bundle
from app.evaluation.indirect_injection_live_writer import (
    LiveIndexReference,
    OllamaModelIdentity,
    resolve_ollama_model_identity,
)
from app.evaluation.indirect_injection_writer import (
    R1_FROZEN_EXPECTED_HASHES,
    R1HashPair,
)
from scripts import eval_indirect_injection_live
from tests.evaluation.test_indirect_injection_live_runner import (
    FREEZE_HEAD,
    FROZEN_AT,
    _StructuredFixtureChat,
    _embedding,
)


def _bundle_root(tmp_path: Path) -> Path:
    root = tmp_path / "security-data"
    build_v1_bundle(
        root,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    return root


def _identity(name: str, digest: str, capability: str) -> OllamaModelIdentity:
    return OllamaModelIdentity(
        requested_name=name,
        resolved_name=name if ":" in name else name + ":latest",
        digest=digest,
        size_bytes=100,
        format="gguf",
        family="bert" if capability == "embedding" else "qwen2",
        parameter_size="567M" if capability == "embedding" else "3.1B",
        quantization_level="F16" if capability == "embedding" else "Q4_K_M",
        context_length=8_192 if capability == "embedding" else 32_768,
        embedding_length=1_024 if capability == "embedding" else 2_048,
        capabilities=(capability,),
    )


def test_parser_has_no_force_guard_or_model_override_switches() -> None:
    parser = eval_indirect_injection_live.build_parser()
    options = {
        option
        for action in parser._actions
        for option in action.option_strings
    }

    assert "--force" not in options
    assert "--guard-off" not in options
    assert "--chat-model" not in options
    assert "--embedding-model" not in options
    assert {"--split", "--run-id", "--data-root", "--out-dir", "--index-root"}.issubset(options)


def test_ollama_tag_resolution_records_exact_digest_and_capability() -> None:
    payload = {
        "models": [
            {
                "name": "bge-m3:latest",
                "model": "bge-m3:latest",
                "size": 1_157_672_605,
                "digest": "7" * 64,
                "details": {
                    "format": "gguf",
                    "family": "bert",
                    "parameter_size": "566.70M",
                    "quantization_level": "F16",
                    "context_length": 8_192,
                    "embedding_length": 1_024,
                },
                "capabilities": ["embedding"],
            }
        ]
    }

    identity = resolve_ollama_model_identity(payload, "bge-m3")

    assert identity.requested_name == "bge-m3"
    assert identity.resolved_name == "bge-m3:latest"
    assert identity.digest == "7" * 64
    assert identity.embedding_length == 1_024
    assert identity.capabilities == ("embedding",)


def test_frozen_test_mismatch_aborts_before_any_model_or_index_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = _bundle_root(tmp_path)
    (data_root / "indirect_injection_test_v1.json").write_text(
        "{}",
        encoding="utf-8",
    )
    called: list[str] = []

    monkeypatch.setattr(
        eval_indirect_injection_live,
        "verify_r1_frozen_hashes",
        lambda _root: {},
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "fetch_ollama_runtime",
        lambda *args, **kwargs: called.append("model"),
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "build_live_fixture_index",
        lambda *args, **kwargs: called.append("index"),
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "evaluate_live_paired",
        lambda *args, **kwargs: called.append("evaluate"),
    )

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        eval_indirect_injection_live.main(
            [
                "--split",
                "test",
                "--run-id",
                "d7-tampered-test",
                "--data-root",
                str(data_root),
                "--out-dir",
                str(tmp_path / "runs"),
                "--index-root",
                str(tmp_path / "indexes"),
            ]
        )

    assert called == []


def test_completed_live_observation_publishes_and_returns_zero_even_with_attacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = _bundle_root(tmp_path)
    embedding_identity = _identity("bge-m3", "7" * 64, "embedding")
    chat_identity = _identity("qwen2.5:3b", "8" * 64, "completion")
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "get_settings",
        lambda: SimpleNamespace(
            llm_base_url="http://127.0.0.1:11434/v1",
            chat_model="qwen2.5:3b",
            embedding_model="bge-m3",
            structured_generation_max_attempts=2,
            v2_indexes_dir=tmp_path / "production-index",
        ),
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "verify_r1_frozen_hashes",
        lambda _root: {
            path: R1HashPair(expected=digest, actual=digest)
            for path, digest in R1_FROZEN_EXPECTED_HASHES.items()
        },
    )
    git = {
        "head": "a" * 40,
        "branch": "codex/rag-eval-system",
        "dirty": False,
        "status_entry_count": 0,
        "dirty_state_sha256": "b" * 64,
    }
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "_git_provenance",
        lambda _root: dict(git),
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "_installed_dependency_snapshot",
        lambda: {
            "installed_snapshot_command": (
                "python",
                "-m",
                "pip",
                "freeze",
                "--all",
            ),
            "installed_snapshot_sha256": "c" * 64,
            "installed_package_count": 50,
        },
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "production_active_index_reference",
        lambda _root: LiveIndexReference(
            role="production_active_reference",
            run_id="production-index",
            active_pointer_sha256="1" * 64,
            manifest_sha256="2" * 64,
            corpus_sha256="3" * 64,
            embedding_model="bge-m3",
            embedding_dimension=1_024,
            indexed_chunk_count=100,
        ),
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "fetch_ollama_runtime",
        lambda _config, _embedding_model: (
            eval_indirect_injection_live.OllamaRuntimeSnapshot(
                version="0.32.1",
                embedding=embedding_identity,
                chat=chat_identity,
            )
        ),
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "run_model_smoke",
        lambda *args, **kwargs: eval_indirect_injection_live.ModelSmokeEvidence(
            embedding_dimension=1_024,
            structured_chat_valid=True,
            allowed_http_request_count=2,
            blocked_egress_attempt_count=0,
        ),
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "_embed_text",
        lambda _model, text: _embedding(text),
    )
    chat = _StructuredFixtureChat()
    monkeypatch.setattr(eval_indirect_injection_live, "chat_with_ollama", chat)
    out = tmp_path / "runs"

    exit_code = eval_indirect_injection_live.main(
        [
            "--split",
            "test",
            "--run-id",
            "d7-completed-observation",
            "--data-root",
            str(data_root),
            "--out-dir",
            str(out),
            "--index-root",
            str(tmp_path / "indexes"),
        ]
    )

    assert exit_code == 0
    run = out / "d7-completed-observation"
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "COMPLETED WITH OBSERVATIONS"
    assert manifest["models"]["embedding"]["digest"] == "7" * 64
    assert manifest["models"]["chat"]["digest"] == "8" * 64
    assert summary["guard_off_live"]["model_attack_followed"]["numerator"] >= 1
    assert manifest["observation"]["deterministic_threshold_diagnostic_passed"] in {
        True,
        False,
    }
