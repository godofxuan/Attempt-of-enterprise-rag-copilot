from __future__ import annotations

import json
import hashlib
import shutil
from pathlib import Path

import pytest

from app.domain.retrieved_security import (
    DETECTOR_VERSION,
    MAX_DECODED_VIEWS,
    MAX_NORMALIZED_CHARS,
    MAX_SCAN_CHARS,
)
from app.evaluation.indirect_injection_cross_model import (
    COMPARISON_METRIC_IDS,
    CrossModelArmObservation,
    CrossModelCaseRow,
    CrossModelMetric,
    _comparison_decision,
    _metric_delta,
    _non_release_safety_diagnostic,
    _summarize_model,
    load_cross_model_plan,
)
from app.evaluation.indirect_injection_cross_model_writer import (
    CrossModelRunManifest,
    _CODE_BINDING_PATHS,
    _checksum_bytes,
    _finalize_manifest,
    _json_bytes,
    _sha256_bytes,
    publish_cross_model_run,
    validate_current_cross_model_bindings,
    verify_cross_model_run,
)
from app.evaluation import indirect_injection_cross_model_writer as matrix_writer
from app.evaluation.indirect_injection_live_runner import _summarize_live_mode
from app.evaluation.indirect_injection_live_writer import (
    LiveSecurityRunManifestV3,
    publish_live_security_run,
)
from tests.evaluation import test_indirect_injection_live_writer as live_fixtures
from tests.evaluation.path_redirect_helpers import directory_redirect


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = (
    REPO_ROOT / "data" / "v2" / "evaluation" / "r2_s4_cross_model_matrix_v1.json"
)
CLEAN_GIT_STATE_SHA256 = hashlib.sha256(b"\0\0").hexdigest()


@pytest.fixture(scope="module")
def writer_v3_inputs(tmp_path_factory: pytest.TempPathFactory):
    return live_fixtures.writer_v3_inputs.__wrapped__(tmp_path_factory)


def _component_manifest(
    bundle,
    built,
    result,
    role: str,
    *,
    python_version=None,
    run_id=None,
    dirty_git=False,
    dataset_sha256=None,
    guard_sha256=None,
):
    plan, _ = load_cross_model_plan(PLAN_PATH)
    planned = plan.model_for_role(role)
    payload = live_fixtures._manifest_v3(bundle, built, result).model_dump(
        mode="python"
    )
    payload["run_id"] = run_id or planned.run_id
    payload["git"] = {
        "head": "a" * 40,
        "branch": "codex/rag-eval-system",
        "dirty": dirty_git,
        "status_entry_count": 1 if dirty_git else 0,
        "dirty_state_sha256": (
            "f" * 64 if dirty_git else CLEAN_GIT_STATE_SHA256
        ),
    }
    if dataset_sha256 is not None:
        payload["data"]["dataset_sha256"] = dataset_sha256
    payload["guard"]["ruleset_sha256"] = guard_sha256 or hashlib.sha256(
        (REPO_ROOT / "app" / "security" / "retrieved_content.py").read_bytes()
    ).hexdigest()
    payload["guard"].update(
        {
            "detector_version": DETECTOR_VERSION,
            "max_scan_chars": MAX_SCAN_CHARS,
            "max_normalized_chars": MAX_NORMALIZED_CHARS,
            "max_decoded_views": MAX_DECODED_VIEWS,
        }
    )
    payload["experiment"]["model_role"] = role
    payload["models"]["chat"] = live_fixtures._identity(
        planned.requested_name,
        f"{role}-chat",
        "completion",
    ).model_copy(
        update={
            "resolved_name": planned.resolved_name,
            "digest": planned.digest,
            "family": planned.family,
            "parameter_size": planned.parameter_size,
        }
    )
    if python_version is not None:
        payload["environment"]["python_version"] = python_version
    return LiveSecurityRunManifestV3.model_validate(payload)


def _publish_components(
    tmp_path: Path,
    writer_v3_inputs,
    *,
    replication_result=None,
    replication_python_version=None,
    baseline_run_id=None,
    dirty_git=False,
    dataset_sha256=None,
    guard_sha256=None,
):
    bundle, built, result = writer_v3_inputs
    replication_result = replication_result or result
    root = tmp_path / "components"
    root.mkdir()
    forbidden = live_fixtures._forbidden_texts(bundle)
    baseline_manifest = _component_manifest(
        bundle,
        built,
        result,
        "baseline",
        run_id=baseline_run_id,
        dirty_git=dirty_git,
        dataset_sha256=dataset_sha256,
        guard_sha256=guard_sha256,
    )
    replication_manifest = _component_manifest(
        bundle,
        built,
        replication_result,
        "replication",
        python_version=replication_python_version,
        dirty_git=dirty_git,
        dataset_sha256=dataset_sha256,
        guard_sha256=guard_sha256,
    )
    baseline = publish_live_security_run(
        root,
        baseline_manifest,
        result,
        paired_evidence="offline fixture\n",
        commands="offline fixture\n",
        test_output="offline fixture\n",
        forbidden_texts=forbidden,
    )
    replication = publish_live_security_run(
        root,
        replication_manifest,
        replication_result,
        paired_evidence="offline fixture\n",
        commands="offline fixture\n",
        test_output="offline fixture\n",
        forbidden_texts=forbidden,
    )
    return bundle, {"baseline": baseline, "replication": replication}, forbidden


def _compare(bundle, components):
    from app.evaluation.indirect_injection_cross_model import compare_verified_runs

    plan, plan_sha256 = load_cross_model_plan(PLAN_PATH)
    return compare_verified_runs(
        components["baseline"],
        components["replication"],
        plan=plan,
        plan_sha256=plan_sha256,
        dataset=bundle.dataset,
    )


def _reseal_package(package: Path) -> None:
    manifest_path = package / "manifest.json"
    witness_path = package / "verification_witness.json"
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    witness_payload = json.loads(witness_path.read_text(encoding="utf-8"))

    witness_payload["summary_sha256"] = _sha256_bytes(
        (package / "summary.json").read_bytes()
    )
    witness_payload["rows_sha256"] = _sha256_bytes(
        (package / "per_case_redacted.jsonl").read_bytes()
    )
    witness_payload["decision"] = manifest_payload["decision"]
    witness_bytes = _json_bytes(witness_payload)
    witness_path.write_bytes(witness_bytes)

    content = {
        name: (package / name).read_bytes()
        for name in (
            "commands.txt",
            "per_case_redacted.jsonl",
            "summary.json",
            "verification_witness.json",
        )
    }
    checksum_bytes = _checksum_bytes(content)
    (package / "checksums.sha256").write_bytes(checksum_bytes)
    content["checksums.sha256"] = checksum_bytes
    for name, payload in content.items():
        manifest_payload["artifacts"][name]["bytes"] = len(payload)
        manifest_payload["artifacts"][name]["sha256"] = _sha256_bytes(payload)

    draft = CrossModelRunManifest.model_validate_json(_json_bytes(manifest_payload))
    _, manifest_bytes = _finalize_manifest(draft)
    manifest_path.write_bytes(manifest_bytes)


def _metric_scaled(metric: CrossModelMetric, factor: int) -> CrossModelMetric:
    if metric.kind == "count_rate":
        return CrossModelMetric.from_counts(
            int(metric.numerator or 0) * factor,
            int(metric.denominator or 0) * factor,
        )
    if metric.kind == "count":
        return CrossModelMetric.from_count(int(metric.value or 0) * factor)
    return CrossModelMetric.from_milliseconds(metric.value if factor else None)


def _rewrite_summary_for_72_baseline(package: Path) -> None:
    summary_path = package / "summary.json"
    summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest_payload = json.loads(
        (package / "manifest.json").read_text(encoding="utf-8")
    )
    from app.evaluation.indirect_injection_cross_model_writer import (
        CrossModelSummaryDocument,
    )

    parsed = CrossModelSummaryDocument.model_validate_json(_json_bytes(summary_payload))
    baseline = parsed.summaries["baseline"].model_copy(
        update={
            "metrics": {
                name: _metric_scaled(metric, 2)
                for name, metric in parsed.summaries["baseline"].metrics.items()
            }
        }
    )
    replication = parsed.summaries["replication"].model_copy(
        update={
            "metrics": {
                name: _metric_scaled(metric, 0)
                for name, metric in parsed.summaries["replication"].metrics.items()
            }
        }
    )
    summaries = {"baseline": baseline, "replication": replication}
    deltas = {
        name: _metric_delta(
            baseline.metrics[name],
            replication.metrics[name],
        )
        for name in COMPARISON_METRIC_IDS
    }
    rows = tuple(
        CrossModelCaseRow.model_validate_json(line)
        for line in (package / "per_case_redacted.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    decision, reasons = _comparison_decision(
        summaries,
        rows,
        tuple(manifest_payload["invariant_mismatches"]),
    )
    summary_payload["summaries"] = {
        role: value.model_dump(mode="json") for role, value in summaries.items()
    }
    summary_payload["deltas"] = {
        name: value.model_dump(mode="json") for name, value in deltas.items()
    }
    summary_payload["decision"] = decision
    summary_payload["decision_reasons"] = list(reasons)
    summary_path.write_bytes(_json_bytes(summary_payload))
    manifest_payload["decision"] = decision
    (package / "manifest.json").write_bytes(_json_bytes(manifest_payload))


def test_compare_verified_v3_runs_recomputes_72_redacted_rows(
    tmp_path: Path,
    writer_v3_inputs,
) -> None:
    bundle, components, _ = _publish_components(tmp_path, writer_v3_inputs)

    result = _compare(bundle, components)

    assert len(result.rows) == 72
    assert [row.row_ordinal for row in result.rows] == list(range(1, 73))
    assert sum(row.model_role == "baseline" for row in result.rows) == 36
    assert sum(row.model_role == "replication" for row in result.rows) == 36
    assert all(row.off.guard_mode == "off" for row in result.rows)
    assert all(row.on.guard_mode == "on" for row in result.rows)
    assert tuple(result.summaries["baseline"].metrics) == COMPARISON_METRIC_IDS
    assert tuple(result.summaries["replication"].metrics) == COMPARISON_METRIC_IDS
    assert result.invariant_mismatches == ()
    assert result.decision == "CONSISTENT_OBSERVATION"

    serialized = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    assert '"question"' not in serialized
    assert '"answer"' not in serialized
    assert '"source_text"' not in serialized
    assert '"raw_text"' not in serialized
    for case in bundle.dataset.cases:
        assert case.case_id not in serialized
        assert case.question not in serialized
        assert case.trace_canary not in serialized
        if case.document_canary:
            assert case.document_canary not in serialized


def test_non_chat_invariant_mismatch_is_inconclusive(
    tmp_path: Path,
    writer_v3_inputs,
) -> None:
    bundle, components, _ = _publish_components(
        tmp_path,
        writer_v3_inputs,
        replication_python_version="3.12-different",
    )

    result = _compare(bundle, components)

    assert result.decision == "INCONCLUSIVE"
    assert "environment.python_version" in result.invariant_mismatches


def test_valid_security_observation_difference_is_divergent(
    tmp_path: Path,
    writer_v3_inputs,
) -> None:
    bundle, _, result = writer_v3_inputs
    changed_off = list(result.guard_off)
    changed_off[0] = changed_off[0].model_copy(
        update={
            "raw_document_canary_exposure": False,
            "raw_system_canary_exposure": False,
            "raw_trace_canary_exposure": False,
            "model_attack_followed": False,
        }
    )
    changed_off_tuple = tuple(changed_off)
    changed = result.model_copy(
        update={
            "guard_off": changed_off_tuple,
            "guard_off_summary": _summarize_live_mode(
                "off",
                changed_off_tuple,
                result.security.guard_off.cases,
            ),
        }
    )
    bundle, components, _ = _publish_components(
        tmp_path,
        writer_v3_inputs,
        replication_result=changed,
    )

    comparison = _compare(bundle, components)

    assert comparison.decision == "DIVERGENT_OBSERVATION"
    delta = comparison.deltas["off_raw_follow_signal"]
    assert delta.baseline.numerator != delta.replication.numerator


def test_equal_unsafe_observations_are_consistent_but_not_safe(
    tmp_path: Path,
    writer_v3_inputs,
) -> None:
    bundle, components, _ = _publish_components(tmp_path, writer_v3_inputs)
    comparison = _compare(bundle, components)
    changed_roles: set[str] = set()
    rows = []
    for row in comparison.rows:
        if row.case_class.label == "attack" and row.model_role not in changed_roles:
            row = row.model_copy(
                update={
                    "on": row.on.model_copy(
                        update={"user_boundary_attack_success": True}
                    )
                }
            )
            changed_roles.add(row.model_role)
        rows.append(row)
    rows_tuple = tuple(rows)
    summaries = {
        role: _summarize_model(
            role,
            comparison.summaries[role].model_digest,
            tuple(row for row in rows_tuple if row.model_role == role),
            True,
        )
        for role in ("baseline", "replication")
    }

    decision, reasons = _comparison_decision(summaries, rows_tuple, ())

    assert decision == "CONSISTENT_OBSERVATION"
    assert reasons == ("complete_equal_security_and_utility_observations",)
    assert all(
        not summary.non_release_safety_diagnostic.passed
        for summary in summaries.values()
    )


def test_equal_safe_observations_are_consistent_with_separate_diagnostic(
    tmp_path: Path,
    writer_v3_inputs,
) -> None:
    bundle, components, _ = _publish_components(tmp_path, writer_v3_inputs)
    comparison = _compare(bundle, components)
    source = comparison.summaries["baseline"]
    metrics = dict(source.metrics)
    metrics.update(
        {
            "on_user_boundary_attack_success": CrossModelMetric.from_counts(0, 24),
            "on_conditional_quarantine": CrossModelMetric.from_counts(15, 15),
            "on_benign_quarantine": CrossModelMetric.from_counts(
                0,
                int(metrics["on_benign_quarantine"].denominator or 0),
            ),
            "model_error_count": CrossModelMetric.from_count(0),
            "blocked_egress": CrossModelMetric.from_count(0),
        }
    )
    summaries = {
        role: comparison.summaries[role].model_copy(
            update={
                "metrics": metrics,
                "non_release_safety_diagnostic": (
                    _non_release_safety_diagnostic(metrics)
                ),
            }
        )
        for role in ("baseline", "replication")
    }

    decision, _ = _comparison_decision(summaries, comparison.rows, ())

    assert decision == "CONSISTENT_OBSERVATION"
    assert all(
        summary.non_release_safety_diagnostic.passed
        for summary in summaries.values()
    )


def test_incomplete_equal_observations_are_inconclusive(
    tmp_path: Path,
    writer_v3_inputs,
) -> None:
    bundle, components, _ = _publish_components(tmp_path, writer_v3_inputs)
    comparison = _compare(bundle, components)
    summaries = {
        role: _summarize_model(
            role,
            comparison.summaries[role].model_digest,
            tuple(row for row in comparison.rows if row.model_role == role),
            False,
        )
        for role in ("baseline", "replication")
    }

    decision, reasons = _comparison_decision(summaries, comparison.rows, ())

    assert decision == "INCONCLUSIVE"
    assert reasons == ("component_protocol_incomplete",)


def test_wrong_component_run_id_is_invalid_not_inconclusive(
    tmp_path: Path,
    writer_v3_inputs,
) -> None:
    bundle, components, _ = _publish_components(
        tmp_path,
        writer_v3_inputs,
        baseline_run_id="r2-s4-wrong-baseline-run",
    )

    with pytest.raises(ValueError, match="run ID"):
        _compare(bundle, components)


def test_dirty_component_git_is_invalid_before_comparison(
    tmp_path: Path,
    writer_v3_inputs,
) -> None:
    bundle, components, _ = _publish_components(
        tmp_path,
        writer_v3_inputs,
        dirty_git=True,
    )

    with pytest.raises(ValueError, match="clean Git"):
        _compare(bundle, components)


def test_redacted_model_error_codes_use_producer_allowlist(
    tmp_path: Path,
    writer_v3_inputs,
) -> None:
    bundle, components, _ = _publish_components(tmp_path, writer_v3_inputs)
    arm = _compare(bundle, components).rows[0].off.model_dump(mode="json")
    arm.update(
        {
            "model_call_count": 1,
            "successful_model_call_count": 0,
            "model_error_codes": ["tenant-specific-secret-error"],
        }
    )

    with pytest.raises(ValueError, match="model_error_codes"):
        CrossModelArmObservation.model_validate_json(_json_bytes(arm))


def test_selected_code_witnesses_cover_live_behavior_dependencies() -> None:
    assert {
        "scripts/eval_indirect_injection_live.py",
        "app/evaluation/indirect_injection_contracts.py",
        "app/evaluation/indirect_injection_dataset.py",
        "app/evaluation/indirect_injection_live_index.py",
        "app/domain/retrieved_security.py",
        "app/config.py",
        "app/ollama_chat.py",
        "app/retriever.py",
        "app/indexing/store.py",
        "app/runtime/model_transport.py",
    } <= set(_CODE_BINDING_PATHS)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ({"dataset_sha256": "0" * 64}, "dataset"),
        ({"guard_sha256": "1" * 64}, "Guard"),
    ],
)
def test_publish_rejects_stale_current_data_or_guard_before_target(
    tmp_path: Path,
    writer_v3_inputs,
    mutation: dict[str, str],
    expected: str,
) -> None:
    bundle, components, forbidden = _publish_components(
        tmp_path,
        writer_v3_inputs,
        **mutation,
    )
    comparison = _compare(bundle, components)
    root = tmp_path / "matrix"
    root.mkdir()

    with pytest.raises(ValueError, match=expected):
        publish_cross_model_run(
            root,
            comparison,
            plan_path=PLAN_PATH,
            component_runs=components,
            commands="offline fixture\n",
            forbidden_texts=forbidden,
            code_root=REPO_ROOT,
        )
    assert not (root / comparison.matrix_run_id).exists()


def test_publish_verify_and_exact_existing_reuse(
    tmp_path: Path,
    writer_v3_inputs,
) -> None:
    bundle, components, forbidden = _publish_components(
        tmp_path,
        writer_v3_inputs,
    )
    comparison = _compare(bundle, components)
    matrix_root = tmp_path / "matrix"
    matrix_root.mkdir()

    first = publish_cross_model_run(
        matrix_root,
        comparison,
        plan_path=PLAN_PATH,
        component_runs=components,
        commands="python -m scripts.eval_indirect_injection_cross_model\n",
        forbidden_texts=forbidden,
        code_root=REPO_ROOT,
    )
    second = publish_cross_model_run(
        matrix_root,
        comparison,
        plan_path=PLAN_PATH,
        component_runs=components,
        commands="python -m scripts.eval_indirect_injection_cross_model\n",
        forbidden_texts=forbidden,
        code_root=REPO_ROOT,
    )
    manifest = verify_cross_model_run(first)

    assert second == first
    assert manifest.matrix_run_id == comparison.matrix_run_id
    assert manifest.decision == comparison.decision
    assert set(path.name for path in first.iterdir()) == {
        "manifest.json",
        "summary.json",
        "per_case_redacted.jsonl",
        "checksums.sha256",
        "commands.txt",
        "verification_witness.json",
    }
    assert len((first / "per_case_redacted.jsonl").read_text().splitlines()) == 72


@pytest.mark.parametrize(
    ("artifact", "mutation"),
    [
        ("per_case_redacted.jsonl", b"\n"),
        ("summary.json", b" "),
        ("manifest.json", b" "),
        ("checksums.sha256", b" "),
    ],
)
def test_private_matrix_verifier_rejects_artifact_mutation(
    tmp_path: Path,
    writer_v3_inputs,
    artifact: str,
    mutation: bytes,
) -> None:
    bundle, components, forbidden = _publish_components(
        tmp_path,
        writer_v3_inputs,
    )
    comparison = _compare(bundle, components)
    root = tmp_path / "matrix"
    root.mkdir()
    package = publish_cross_model_run(
        root,
        comparison,
        plan_path=PLAN_PATH,
        component_runs=components,
        commands="offline fixture\n",
        forbidden_texts=forbidden,
        code_root=REPO_ROOT,
    )
    path = package / artifact
    path.write_bytes(path.read_bytes() + mutation)

    with pytest.raises(ValueError):
        verify_cross_model_run(package)


def test_private_matrix_verifier_rejects_extra_file(
    tmp_path: Path,
    writer_v3_inputs,
) -> None:
    bundle, components, forbidden = _publish_components(
        tmp_path,
        writer_v3_inputs,
    )
    comparison = _compare(bundle, components)
    root = tmp_path / "matrix"
    root.mkdir()
    package = publish_cross_model_run(
        root,
        comparison,
        plan_path=PLAN_PATH,
        component_runs=components,
        commands="offline fixture\n",
        forbidden_texts=forbidden,
        code_root=REPO_ROOT,
    )
    (package / "extra.txt").write_text("unexpected", encoding="utf-8")

    with pytest.raises(ValueError, match="artifact set"):
        verify_cross_model_run(package)


def test_verifier_rejects_resealed_72_baseline_zero_replication_rows(
    tmp_path: Path,
    writer_v3_inputs,
) -> None:
    bundle, components, forbidden = _publish_components(
        tmp_path,
        writer_v3_inputs,
    )
    comparison = _compare(bundle, components)
    root = tmp_path / "matrix"
    root.mkdir()
    package = publish_cross_model_run(
        root,
        comparison,
        plan_path=PLAN_PATH,
        component_runs=components,
        commands="offline fixture\n",
        forbidden_texts=forbidden,
        code_root=REPO_ROOT,
    )
    rows_path = package / "per_case_redacted.jsonl"
    rows = [json.loads(line) for line in rows_path.read_text().splitlines()]
    for row in rows:
        row["model_role"] = "baseline"
    rows_path.write_bytes(b"".join(_json_bytes(row, compact=True) for row in rows))
    _rewrite_summary_for_72_baseline(package)
    _reseal_package(package)

    with pytest.raises(ValueError, match="role order|36 baseline"):
        verify_cross_model_run(package)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_digest", "f" * 64),
        ("candidate_order_sha256", "e" * 64),
    ],
)
def test_verifier_rejects_resealed_row_binding_mutation(
    tmp_path: Path,
    writer_v3_inputs,
    field: str,
    value: str,
) -> None:
    bundle, components, forbidden = _publish_components(
        tmp_path,
        writer_v3_inputs,
    )
    comparison = _compare(bundle, components)
    root = tmp_path / "matrix"
    root.mkdir()
    package = publish_cross_model_run(
        root,
        comparison,
        plan_path=PLAN_PATH,
        component_runs=components,
        commands="offline fixture\n",
        forbidden_texts=forbidden,
        code_root=REPO_ROOT,
    )
    rows_path = package / "per_case_redacted.jsonl"
    rows = [json.loads(line) for line in rows_path.read_text().splitlines()]
    rows[0][field] = value
    rows_path.write_bytes(b"".join(_json_bytes(row, compact=True) for row in rows))
    _reseal_package(package)

    with pytest.raises(ValueError, match="digest|row binding"):
        verify_cross_model_run(package)


def test_existing_invalid_matrix_fails_without_overwrite(
    tmp_path: Path,
    writer_v3_inputs,
) -> None:
    bundle, components, forbidden = _publish_components(
        tmp_path,
        writer_v3_inputs,
    )
    comparison = _compare(bundle, components)
    root = tmp_path / "matrix"
    root.mkdir()
    package = publish_cross_model_run(
        root,
        comparison,
        plan_path=PLAN_PATH,
        component_runs=components,
        commands="offline fixture\n",
        forbidden_texts=forbidden,
        code_root=REPO_ROOT,
    )
    before = (package / "summary.json").read_bytes()
    (package / "summary.json").write_bytes(before + b" ")

    with pytest.raises(ValueError):
        publish_cross_model_run(
            root,
            comparison,
            plan_path=PLAN_PATH,
            component_runs=components,
            commands="offline fixture\n",
            forbidden_texts=forbidden,
            code_root=REPO_ROOT,
        )
    assert (package / "summary.json").read_bytes() == before + b" "


@pytest.mark.parametrize(
    ("artifact", "canary"),
    [
        ("manifest.json", "tenant-r2s4-secret-4471"),
        ("summary.json", "source-id-r2s4-secret-4472"),
        ("per_case_redacted.jsonl", "C:/private/r2s4-secret-4473.txt"),
        ("checksums.sha256", "payload-r2s4-secret-4474"),
        ("commands.txt", "fixture-fact-r2s4-secret-4475"),
        ("verification_witness.json", "document-id-r2s4-secret-4476"),
    ],
)
def test_every_private_artifact_is_scanned_for_privacy_canaries(
    tmp_path: Path,
    writer_v3_inputs,
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
    canary: str,
) -> None:
    bundle, components, forbidden = _publish_components(
        tmp_path,
        writer_v3_inputs,
    )
    comparison = _compare(bundle, components)
    original = matrix_writer._build_package_bytes

    def poisoned(*args, **kwargs):
        files, manifest = original(*args, **kwargs)
        files = dict(files)
        files[artifact] += canary.encode("utf-8")
        return files, manifest

    monkeypatch.setattr(matrix_writer, "_build_package_bytes", poisoned)
    root = tmp_path / "matrix"
    root.mkdir()

    with pytest.raises(ValueError, match="forbidden content"):
        publish_cross_model_run(
            root,
            comparison,
            plan_path=PLAN_PATH,
            component_runs=components,
            commands="offline fixture\n",
            forbidden_texts=forbidden + (canary,),
            code_root=REPO_ROOT,
        )
    assert not (root / comparison.matrix_run_id).exists()


def test_private_matrix_verifier_rejects_directory_redirect_when_supported(
    tmp_path: Path,
) -> None:
    referent = tmp_path / "referent"
    referent.mkdir()
    redirect = tmp_path / "redirect"
    try:
        redirect.symlink_to(referent, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this host")

    with pytest.raises(ValueError, match="redirect|symlink"):
        verify_cross_model_run(redirect)


def test_verifier_rejects_parent_junction_before_resolve(
    tmp_path: Path,
    writer_v3_inputs,
) -> None:
    bundle, components, forbidden = _publish_components(
        tmp_path,
        writer_v3_inputs,
    )
    comparison = _compare(bundle, components)
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    package = publish_cross_model_run(
        real_parent,
        comparison,
        plan_path=PLAN_PATH,
        component_runs=components,
        commands="offline fixture\n",
        forbidden_texts=forbidden,
        code_root=REPO_ROOT,
    )
    alias = tmp_path / "alias"
    with directory_redirect(alias, real_parent, windows_junction_only=True):
        with pytest.raises(ValueError, match="redirect|reparse|junction"):
            verify_cross_model_run(alias / package.name)


def test_publication_rejects_parent_junction_before_staging(
    tmp_path: Path,
    writer_v3_inputs,
) -> None:
    bundle, components, forbidden = _publish_components(
        tmp_path,
        writer_v3_inputs,
    )
    comparison = _compare(bundle, components)
    real_parent = tmp_path / "real-publication-parent"
    matrix_root = real_parent / "matrix"
    matrix_root.mkdir(parents=True)
    alias = tmp_path / "publication-alias"
    with directory_redirect(alias, real_parent, windows_junction_only=True):
        with pytest.raises(ValueError, match="redirect|reparse|junction"):
            publish_cross_model_run(
                alias / "matrix",
                comparison,
                plan_path=PLAN_PATH,
                component_runs=components,
                commands="offline fixture\n",
                forbidden_texts=forbidden,
                code_root=REPO_ROOT,
            )
    assert not (matrix_root / comparison.matrix_run_id).exists()


def test_current_git_mismatch_rejects_existing_matrix(
    tmp_path: Path,
    writer_v3_inputs,
) -> None:
    bundle, components, forbidden = _publish_components(
        tmp_path,
        writer_v3_inputs,
    )
    comparison = _compare(bundle, components)
    root = tmp_path / "matrix"
    root.mkdir()
    package = publish_cross_model_run(
        root,
        comparison,
        plan_path=PLAN_PATH,
        component_runs=components,
        commands="offline fixture\n",
        forbidden_texts=forbidden,
        code_root=REPO_ROOT,
    )

    with pytest.raises(ValueError, match="current Git|Git binding"):
        validate_current_cross_model_bindings(
            package,
            plan_path=PLAN_PATH,
            component_runs=components,
            code_root=REPO_ROOT,
            current_git={
                "head": "b" * 40,
                "branch": "codex/rag-eval-system",
                "dirty": False,
                "status_entry_count": 0,
                "dirty_state_sha256": CLEAN_GIT_STATE_SHA256,
            },
        )


def test_verifier_cli_accepts_only_a_verified_matrix(
    tmp_path: Path,
    writer_v3_inputs,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.verify_indirect_injection_cross_model import main

    bundle, components, forbidden = _publish_components(
        tmp_path,
        writer_v3_inputs,
    )
    comparison = _compare(bundle, components)
    root = tmp_path / "matrix"
    root.mkdir()
    package = publish_cross_model_run(
        root,
        comparison,
        plan_path=PLAN_PATH,
        component_runs=components,
        commands="offline fixture\n",
        forbidden_texts=forbidden,
        code_root=REPO_ROOT,
    )

    assert main([str(package)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["matrix_run_id"] == comparison.matrix_run_id
    assert payload["decision"] == comparison.decision
