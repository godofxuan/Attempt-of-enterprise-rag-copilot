from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import app.evaluation.indirect_injection_public_writer as public_writer_module
from app.evaluation.indirect_injection_live_writer import publish_live_security_run
from app.evaluation.indirect_injection_public_writer import (
    PUBLIC_PACKAGE_FILES,
    PublicCaseEvidence,
    PublicMetric,
    export_public_evidence,
)
from tests.evaluation.test_indirect_injection_live_writer import (
    _forbidden_texts,
    _manifest,
    writer_inputs,
)


PUBLIC_ROW_KEYS = {
    "allowed_local_model_http_request_count",
    "answer_mode",
    "attack_unit_count",
    "attack_unit_quarantined_count",
    "attack_unit_reached_guard_count",
    "benign_unit_count",
    "benign_unit_quarantined_count",
    "blocked_egress_attempt_count",
    "candidate_count",
    "candidate_order_sha256",
    "case_id",
    "category",
    "decoded_candidate_count",
    "external_egress_attempt",
    "failure_codes",
    "forbidden_tool_attempt",
    "guard_error_count",
    "guard_latency_ms",
    "guard_mode",
    "input_fingerprint",
    "label",
    "model_call_count",
    "model_context_exposure",
    "model_error_codes",
    "model_latency_ms",
    "nonce_fingerprint",
    "pair_input_fingerprint",
    "raw_canary_or_forbidden_action_follow",
    "raw_document_canary_exposure",
    "raw_system_canary_exposure",
    "raw_trace_canary_exposure",
    "resource_bound_violation",
    "retrieval_completed",
    "risk_categories",
    "rule_ids",
    "scanned_chars",
    "scanned_content_unit_count",
    "schema_version",
    "security_filtered_correct",
    "stop_reason",
    "successful_model_call_count",
    "task_applicable",
    "task_success",
    "top_up_attempts",
    "user_visible_attack_success",
    "utility_bucket",
    "variant_id",
}


@pytest.fixture(scope="module")
def private_source_run(tmp_path_factory: pytest.TempPathFactory, writer_inputs):
    bundle, built, result = writer_inputs
    root = tmp_path_factory.mktemp("public-evidence-source")
    source = publish_live_security_run(
        root / "private-runs",
        _manifest(bundle, built, result),
        result,
        paired_evidence="# Private paired evidence\n",
        commands="python -m scripts.eval_indirect_injection_live --split test\n",
        test_output="private live test completed\n",
        forbidden_texts=_forbidden_texts(bundle),
    )
    digest = hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()
    return bundle, source, digest


def _export(tmp_path: Path, private_source_run, *, package_name: str = "unit_d7"):
    bundle, source, digest = private_source_run
    return export_public_evidence(
        source,
        tmp_path / "public",
        package_name=package_name,
        expected_source_manifest_sha256=digest,
        expected_source_run_id="r2-s1-d7-live-writer-test",
        forbidden_texts=_forbidden_texts(bundle),
    )


def _rows(package: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (package / "per_case.redacted.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]


def test_public_writer_emits_exact_allowlisted_package_and_metrics(
    tmp_path: Path,
    private_source_run,
) -> None:
    package = _export(tmp_path, private_source_run)

    assert {path.name for path in package.iterdir()} == PUBLIC_PACKAGE_FILES
    rows = _rows(package)
    assert len(rows) == 72
    assert all(set(row) == PUBLIC_ROW_KEYS for row in rows)

    summary = json.loads((package / "summary.json").read_text(encoding="utf-8"))
    off_attack = [
        row
        for row in rows
        if row["guard_mode"] == "off" and row["label"] == "attack"
    ]
    expected_context = sum(bool(row["model_context_exposure"]) for row in off_attack)
    metric = summary["metrics"]["off_model_context_exposure"]
    assert metric["numerator"] == expected_context
    assert metric["denominator"] == 24
    assert metric["rate"] == expected_context / 24

    on_rows = [row for row in rows if row["guard_mode"] == "on"]
    expected_benign_quarantine = sum(
        int(row["benign_unit_quarantined_count"]) for row in on_rows
    )
    expected_benign_units = sum(int(row["benign_unit_count"]) for row in on_rows)
    assert summary["metrics"]["on_benign_unit_quarantine"] == {
        "denominator": expected_benign_units,
        "numerator": expected_benign_quarantine,
        "rate": expected_benign_quarantine / expected_benign_units,
    }


def test_public_case_validation_uses_versioned_raw_follow_helper(
    tmp_path: Path,
    private_source_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _export(tmp_path, private_source_run)
    payload = _rows(package)[0]
    observed: list[dict[str, bool]] = []

    def recording_helper(**signals: bool) -> bool:
        observed.append(signals)
        return any(signals.values())

    monkeypatch.setattr(
        public_writer_module,
        "raw_canary_or_forbidden_action_follow",
        recording_helper,
    )

    PublicCaseEvidence.model_validate_json(
        json.dumps(payload, ensure_ascii=False)
    )

    assert observed == [
        {
            "raw_document_canary_exposure": False,
            "raw_system_canary_exposure": False,
            "raw_trace_canary_exposure": False,
            "forbidden_tool_attempt": False,
        }
    ]


def test_public_writer_output_is_content_free_and_uses_hashes_not_raw_ids(
    tmp_path: Path,
    private_source_run,
) -> None:
    bundle, source, _ = private_source_run
    package = _export(tmp_path, private_source_run)
    decoded = b"\n".join(
        path.read_bytes() for path in sorted(package.iterdir())
    ).decode("utf-8")

    for forbidden in _forbidden_texts(bundle):
        assert forbidden not in decoded
    assert str(source) not in decoded
    assert "candidate_order\"" not in decoded
    assert "attack_unit_ids" not in decoded
    assert "benign_unit_ids" not in decoded
    assert "unit_outcomes" not in decoded


def test_public_writer_refuses_wrong_source_hash_without_creating_target(
    tmp_path: Path,
    private_source_run,
) -> None:
    bundle, source, _ = private_source_run

    with pytest.raises(ValueError, match="source manifest SHA-256 mismatch"):
        export_public_evidence(
            source,
            tmp_path / "public",
            package_name="wrong_hash",
            expected_source_manifest_sha256="0" * 64,
            expected_source_run_id="r2-s1-d7-live-writer-test",
            forbidden_texts=_forbidden_texts(bundle),
        )

    assert not (tmp_path / "public" / "wrong_hash").exists()


def test_public_writer_refuses_overwrite_and_path_traversal(
    tmp_path: Path,
    private_source_run,
) -> None:
    package = _export(tmp_path, private_source_run)

    with pytest.raises(FileExistsError, match="already exists"):
        _export(tmp_path, private_source_run)

    with pytest.raises(ValueError, match="unsafe"):
        _export(tmp_path, private_source_run, package_name="../escape")

    assert package.is_dir()
    assert not (tmp_path / "escape").exists()


def test_public_writer_is_byte_deterministic_and_orders_case_pairs(
    tmp_path: Path,
    private_source_run,
) -> None:
    first = _export(tmp_path / "first", private_source_run)
    second = _export(tmp_path / "second", private_source_run)

    assert {
        path.name: path.read_bytes() for path in first.iterdir()
    } == {
        path.name: path.read_bytes() for path in second.iterdir()
    }
    observed = [(row["case_id"], row["guard_mode"]) for row in _rows(first)]
    expected = sorted(
        observed,
        key=lambda item: (str(item[0]), {"off": 0, "on": 1}[str(item[1])]),
    )
    assert observed == expected


def test_public_writer_does_not_publish_with_replace_capable_directory_rename(
    tmp_path: Path,
    private_source_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_directory_rename(self: Path, target: Path) -> Path:
        raise AssertionError("directory rename can replace a raced empty target on POSIX")

    monkeypatch.setattr(Path, "rename", reject_directory_rename)

    package = _export(tmp_path, private_source_run)

    assert package.is_dir()


def test_public_metric_uses_null_for_zero_denominator() -> None:
    assert PublicMetric.from_counts(0, 0).model_dump(mode="json") == {
        "numerator": 0,
        "denominator": 0,
        "rate": None,
    }


def test_checksums_cover_every_other_file_without_self_reference(
    tmp_path: Path,
    private_source_run,
) -> None:
    package = _export(tmp_path, private_source_run)
    rows = (package / "checksums.sha256").read_text(encoding="utf-8").splitlines()
    names = [row.split("  ", 1)[1] for row in rows]

    assert names == sorted(PUBLIC_PACKAGE_FILES - {"checksums.sha256"})
    assert "checksums.sha256" not in names
    for row in rows:
        digest, name = row.split("  ", 1)
        assert digest == hashlib.sha256((package / name).read_bytes()).hexdigest()
