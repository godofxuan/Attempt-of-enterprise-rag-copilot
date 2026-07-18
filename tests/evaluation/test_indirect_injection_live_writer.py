from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.indirect_injection_dataset import (
    build_v1_bundle,
    load_security_bundle,
)
from app.evaluation.indirect_injection_live_index import (
    build_live_fixture_index,
)
from app.evaluation.indirect_injection_live_runner import (
    LiveSecurityConfig,
    evaluate_live_paired,
)
from app.evaluation.indirect_injection_live_writer import (
    LiveSecurityRunManifest,
    OllamaModelIdentity,
    publish_live_security_run,
)
from app.evaluation.indirect_injection_writer import (
    R1_FROZEN_EXPECTED_HASHES,
)
from tests.evaluation.test_indirect_injection_live_runner import (
    BUILD_TIME,
    FIXTURE_SHA256,
    FREEZE_HEAD,
    FROZEN_AT,
    _StructuredFixtureChat,
    _embedding,
)


COMPLETED_TIME = datetime(2026, 7, 18, 1, 3, 4, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def writer_inputs(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("d7-live-writer")
    security_root = root / "security-data"
    build_v1_bundle(
        security_root,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    bundle = load_security_bundle(security_root, "test")
    built = build_live_fixture_index(
        dataset=bundle.dataset,
        fixtures=bundle.fixture_manifest,
        root=root / "security-index",
        run_id="r2-s1-d7-writer-index",
        fixture_sha256=FIXTURE_SHA256,
        embedding_model="bge-m3",
        embed_text=_embedding,
        started_at=BUILD_TIME,
        finished_at=BUILD_TIME,
    )
    result = evaluate_live_paired(
        dataset=bundle.dataset,
        fixtures=bundle.fixture_manifest,
        snapshot=built.snapshot,
        embed_text=_embedding,
        chat_fn=_StructuredFixtureChat(),
        config=LiveSecurityConfig(
            llm_endpoint="http://127.0.0.1:11434/v1",
            chat_model="qwen2.5:3b",
        ),
        clock_ms=lambda: 1_000.0,
    )
    return bundle, built, result


def _identity(name: str, digest_seed: str, capability: str) -> OllamaModelIdentity:
    return OllamaModelIdentity(
        requested_name=name,
        resolved_name=name if ":" in name else name + ":latest",
        digest=hashlib.sha256(digest_seed.encode("utf-8")).hexdigest(),
        size_bytes=123,
        format="gguf",
        family="qwen2" if capability == "completion" else "bert",
        parameter_size="3B" if capability == "completion" else "567M",
        quantization_level="Q4_K_M" if capability == "completion" else "F16",
        context_length=32_768,
        embedding_length=2_048 if capability == "completion" else 1_024,
        capabilities=(capability,),
    )


def _manifest(bundle, built, result) -> LiveSecurityRunManifest:
    return LiveSecurityRunManifest.model_validate(
        {
            "schema_version": "indirect_injection_live_security_run_manifest_v1",
            "producer": "enterprise_agentic_rag_v2",
            "run_id": "r2-s1-d7-live-writer-test",
            "suite": "retrieved_content_indirect_injection",
            "split": "test",
            "mode": "local_live_paired",
            "started_at_utc": BUILD_TIME,
            "completed_at_utc": COMPLETED_TIME,
            "status": result.status,
            "git": {
                "head": "a" * 40,
                "branch": "codex/rag-eval-system",
                "dirty": False,
                "status_entry_count": 0,
                "dirty_state_sha256": "b" * 64,
            },
            "environment": {
                "python_version": "3.11.9",
                "platform": "Windows-test",
                "dependency_snapshot_path": "requirements.txt",
                "dependency_snapshot_sha256": "c" * 64,
                "installed_snapshot_sha256": "d" * 64,
                "installed_package_count": 50,
                "ollama_version": "0.32.1",
                "ollama_endpoint": "http://127.0.0.1:11434",
            },
            "models": {
                "embedding": _identity("bge-m3", "embed", "embedding"),
                "chat": _identity("qwen2.5:3b", "chat", "completion"),
                "evidence_model": "NOT_USED_D7_LIVE_PAIRED",
                "temperature": 0.0,
                "structured_output_variant": "generation-v2-json-schema",
                "think": False,
                "max_attempts": 2,
            },
            "guard": {
                "detector_version": "r2_s1_retrieved_content_guard_v1",
                "ruleset_path": "app/security/retrieved_content.py",
                "ruleset_sha256": "e" * 64,
                "max_scan_chars": 20_000,
                "max_normalized_chars": 40_000,
                "max_decoded_views": 4,
            },
            "data": {
                "dataset_path": "data/v2/security/indirect_injection_test_v1.json",
                "dataset_sha256": bundle.dataset_sha256,
                "dataset_case_count": 36,
                "fixture_manifest_path": (
                    "data/v2/security/fixtures_v1/test/manifest.json"
                ),
                "fixture_manifest_sha256": bundle.fixture_manifest_sha256,
                "attack_case_count": 24,
                "benign_case_count": 12,
                "r1_frozen_hashes": {
                    path: {"expected": digest, "actual": digest}
                    for path, digest in R1_FROZEN_EXPECTED_HASHES.items()
                },
            },
            "evaluator": {
                "path": "app/evaluation/indirect_injection_live_runner.py",
                "sha256": "f" * 64,
                "argv": (
                    "python",
                    "-m",
                    "scripts.eval_indirect_injection_live",
                    "--split",
                    "test",
                ),
                "exit_code": 0,
            },
            "retrieval": {
                "production_active_index": {
                    "role": "production_active_reference",
                    "run_id": "production-index",
                    "active_pointer_sha256": "1" * 64,
                    "manifest_sha256": "2" * 64,
                    "corpus_sha256": "3" * 64,
                    "embedding_model": "bge-m3",
                    "embedding_dimension": 1_024,
                    "indexed_chunk_count": 100,
                },
                "security_fixture_index": {
                    "role": "security_fixture_runtime",
                    "run_id": built.manifest.run_id,
                    "active_pointer_sha256": "4" * 64,
                    "manifest_sha256": built.manifest_sha256,
                    "corpus_sha256": bundle.fixture_manifest_sha256,
                    "embedding_model": "bge-m3",
                    "embedding_dimension": 8,
                    "indexed_chunk_count": built.manifest.indexed_chunk_count,
                },
                "chunking": "post-parser-security-fixture-projection-v1",
                "top_k": 1,
                "candidate_k": 4,
                "max_search_calls": 1,
                "max_open_calls": 1,
                "max_steps": 3,
                "max_context_chars": 50_000,
                "index_embedding_call_count": built.embedding_call_count,
                "embedding_request_count": result.embedding_request_count,
                "embedding_delegate_call_count": (
                    result.embedding_delegate_call_count
                ),
                "embedding_cache_hit_count": result.embedding_cache_hit_count,
            },
            "observation": {
                "status": result.status,
                "protocol_complete": result.protocol_complete,
                "pair_input_consistent": result.pair_input_consistent,
                "deterministic_threshold_diagnostic_passed": (
                    result.security.gate.passed
                ),
            },
            "artifacts": {},
            "limitations": (
                "This is one local model run, not a universal model-safety claim.",
                "The frozen test set is visible regression data, not unseen data.",
                "The production active index is provenance only; synthetic attacks use the isolated security index.",
            ),
        }
    )


def _forbidden_texts(bundle) -> tuple[str, ...]:
    values: set[str] = set()
    for case in bundle.dataset.cases:
        values.add(case.question)
        values.add(case.trace_canary)
        if case.document_canary:
            values.add(case.document_canary)
    for fixture in bundle.fixture_manifest.cases:
        values.update(fixture.fact_texts.values())
        for candidate in fixture.candidates:
            values.update((candidate.matched_text, candidate.context_text))
        for opened in fixture.open_results:
            values.add(opened.content)
    return tuple(sorted(values))


def test_publish_live_run_is_immutable_complete_and_content_free(
    tmp_path: Path,
    writer_inputs,
) -> None:
    bundle, built, result = writer_inputs
    manifest = _manifest(bundle, built, result)
    out = tmp_path / "runs"

    target = publish_live_security_run(
        out,
        manifest,
        result,
        paired_evidence="# D7 live paired evidence\n\nObserved counts only.\n",
        commands="python -m scripts.eval_indirect_injection_live --split test\n",
        test_output="Ollama/model/index preflight passed.\n",
        forbidden_texts=_forbidden_texts(bundle),
    )

    assert {path.name for path in target.iterdir()} == {
        "manifest.json",
        "summary.json",
        "per_case.jsonl",
        "failures.csv",
        "red_green_evidence.md",
        "commands.txt",
        "test_output.txt",
        "checksums.sha256",
    }
    parsed = LiveSecurityRunManifest.model_validate_json(
        (target / "manifest.json").read_bytes()
    )
    assert parsed.status == "COMPLETED WITH OBSERVATIONS"
    assert set(parsed.artifacts) == {
        "summary.json",
        "per_case.jsonl",
        "failures.csv",
        "red_green_evidence.md",
        "commands.txt",
        "test_output.txt",
        "checksums.sha256",
    }

    all_content = b"\n".join(path.read_bytes() for path in target.iterdir())
    decoded = all_content.decode("utf-8")
    for forbidden in _forbidden_texts(bundle):
        assert forbidden not in decoded
    assert str(tmp_path) not in decoded

    with pytest.raises(FileExistsError):
        publish_live_security_run(
            out,
            manifest,
            result,
            paired_evidence="same",
            commands="same",
            test_output="same",
            forbidden_texts=_forbidden_texts(bundle),
        )


def test_writer_rejects_raw_model_output_or_secret_like_text(
    tmp_path: Path,
    writer_inputs,
) -> None:
    bundle, built, result = writer_inputs
    manifest = _manifest(bundle, built, result).model_copy(
        update={"run_id": "r2-s1-d7-live-reject-content"}
    )
    raw = bundle.fixture_manifest.cases[0].candidates[0].matched_text

    with pytest.raises(ValueError, match="forbidden content"):
        publish_live_security_run(
            tmp_path / "runs",
            manifest,
            result,
            paired_evidence="safe",
            commands="safe",
            test_output=f"model said: {raw}\napi_key=sk-test-1234567890abcdef",
            forbidden_texts=_forbidden_texts(bundle),
        )


def test_live_manifest_cannot_call_observations_a_release_pass(writer_inputs) -> None:
    bundle, built, result = writer_inputs
    payload = _manifest(bundle, built, result).model_dump(mode="python")
    payload["status"] = "PASSED"

    with pytest.raises(ValidationError):
        LiveSecurityRunManifest.model_validate(payload)
