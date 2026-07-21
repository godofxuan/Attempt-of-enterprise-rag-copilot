from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.evaluation.indirect_injection_cross_model import (
    COMPARISON_METRIC_IDS,
    load_cross_model_plan,
)
from app.evaluation.indirect_injection_cross_model_writer import (
    publish_cross_model_run,
    verify_cross_model_run,
)
from app.evaluation.indirect_injection_live_runner import _summarize_live_mode
from app.evaluation.indirect_injection_live_writer import (
    LiveSecurityRunManifestV3,
    publish_live_security_run,
)
from tests.evaluation import test_indirect_injection_live_writer as live_fixtures


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = (
    REPO_ROOT / "data" / "v2" / "evaluation" / "r2_s4_cross_model_matrix_v1.json"
)


@pytest.fixture(scope="module")
def writer_v3_inputs(tmp_path_factory: pytest.TempPathFactory):
    return live_fixtures.writer_v3_inputs.__wrapped__(tmp_path_factory)


def _component_manifest(bundle, built, result, role: str, *, python_version=None):
    plan, _ = load_cross_model_plan(PLAN_PATH)
    planned = plan.model_for_role(role)
    payload = live_fixtures._manifest_v3(bundle, built, result).model_dump(
        mode="python"
    )
    payload["run_id"] = f"r2-s4-task4-{role}-fixture"
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
):
    bundle, built, result = writer_v3_inputs
    replication_result = replication_result or result
    root = tmp_path / "components"
    root.mkdir()
    forbidden = live_fixtures._forbidden_texts(bundle)
    baseline_manifest = _component_manifest(bundle, built, result, "baseline")
    replication_manifest = _component_manifest(
        bundle,
        built,
        replication_result,
        "replication",
        python_version=replication_python_version,
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
