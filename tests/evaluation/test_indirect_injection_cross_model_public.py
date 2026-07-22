from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.evaluation import indirect_injection_cross_model_public as public_exporter
from app.evaluation import (
    indirect_injection_cross_model_public_verifier as public_verifier,
)
from app.evaluation.indirect_injection_cross_model_public import (
    export_cross_model_public,
)
from app.evaluation.indirect_injection_cross_model_public_verifier import (
    BASELINE_MODEL_DIGEST,
    CHECKSUM_CONTENT_NAMES,
    PUBLIC_ARM_KEYS,
    PUBLIC_CROSS_MODEL_FILES,
    PUBLIC_ROW_KEYS,
    REPLICATION_MODEL_DIGEST,
    PublicCrossModelVerificationError,
    verify_public_package,
)
from app.evaluation.indirect_injection_cross_model_writer import (
    load_verified_cross_model_run_snapshot,
    publish_cross_model_run,
)
from tests.evaluation import (
    test_indirect_injection_cross_model_writer as private_fixtures,
)
from tests.evaluation.path_redirect_helpers import directory_redirect


REPO_ROOT = Path(__file__).resolve().parents[2]
ZERO_SHA256 = "0" * 64


@pytest.fixture(scope="module")
def writer_v3_inputs(tmp_path_factory: pytest.TempPathFactory):
    return private_fixtures.writer_v3_inputs.__wrapped__(tmp_path_factory)


@pytest.fixture(scope="module")
def private_matrix(
    tmp_path_factory: pytest.TempPathFactory,
    writer_v3_inputs,
) -> tuple[Path, object]:
    root = tmp_path_factory.mktemp("r2-s4-task5-private")
    bundle, components, forbidden = private_fixtures._publish_components(
        root,
        writer_v3_inputs,
    )
    comparison = private_fixtures._compare(bundle, components)
    matrix_root = root / "matrix"
    matrix_root.mkdir()
    package = publish_cross_model_run(
        matrix_root,
        comparison,
        plan_path=private_fixtures.PLAN_PATH,
        component_runs=components,
        commands="offline writer-generated Task 5 fixture\n",
        forbidden_texts=forbidden,
        code_root=REPO_ROOT,
    )
    return package, bundle


@pytest.fixture(scope="module")
def public_package(
    tmp_path_factory: pytest.TempPathFactory,
    private_matrix: tuple[Path, object],
) -> Path:
    output = tmp_path_factory.mktemp("r2-s4-task5-public") / "package"
    return export_cross_model_public(private_matrix[0], output)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _json_line(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _rows(package: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (package / "per_case_redacted.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]


def _private_metric(metric: object) -> dict[str, object]:
    return {
        "kind": metric.kind,
        "numerator": metric.numerator,
        "denominator": metric.denominator,
        "rate": metric.rate,
        "value": metric.value,
    }


def _private_diagnostic(diagnostic: object) -> dict[str, object]:
    return {
        "diagnostic_id": diagnostic.diagnostic_id,
        "release_pass": diagnostic.release_pass,
        "on_attack_success_zero_of_24": (
            diagnostic.on_attack_success_zero_of_24
        ),
        "on_conditional_quarantine_15_of_15": (
            diagnostic.on_conditional_quarantine_15_of_15
        ),
        "on_benign_quarantine_zero_of_32": (
            diagnostic.on_benign_quarantine_zero_of_32
        ),
        "model_errors_zero": diagnostic.model_errors_zero,
        "blocked_egress_zero": diagnostic.blocked_egress_zero,
        "passed": diagnostic.passed,
    }


def _private_summary_evidence(snapshot: object) -> dict[str, object]:
    summaries = {}
    for role in ("baseline", "replication"):
        source = snapshot.summary.summaries[role]
        summaries[role] = {
            "model_role": source.model_role,
            "model_digest": source.model_digest,
            "case_count": source.case_count,
            "protocol_complete": source.protocol_complete,
            "non_release_safety_diagnostic": _private_diagnostic(
                source.non_release_safety_diagnostic
            ),
            "metrics": {
                metric_id: _private_metric(source.metrics[metric_id])
                for metric_id in source.metrics
            },
        }
    deltas = {}
    for metric_id, source in snapshot.summary.deltas.items():
        deltas[metric_id] = {
            "baseline": _private_metric(source.baseline),
            "replication": _private_metric(source.replication),
            "delta": source.delta,
        }
    return {
        "summaries": summaries,
        "deltas": deltas,
        "decision": snapshot.summary.decision,
        "decision_reasons": list(snapshot.summary.decision_reasons),
    }


def _copy_package(source: Path, root: Path) -> Path:
    target = root / "package"
    shutil.copytree(source, target)
    return target


def _manifest_core_sha256(manifest: dict[str, object]) -> str:
    normalized = json.loads(json.dumps(manifest))
    artifacts = normalized["artifacts"]
    assert isinstance(artifacts, dict)
    for name in (
        "manifest.json",
        "verification_witness.json",
        "checksums.sha256",
    ):
        evidence = artifacts[name]
        assert isinstance(evidence, dict)
        evidence["bytes"] = 0
        evidence["sha256"] = ZERO_SHA256
    return hashlib.sha256(_json_bytes(normalized)).hexdigest()


def _refresh_transport(package: Path) -> None:
    """Reseal transport hashes so semantic mutation tests reach recomputation."""

    manifest_path = package / "manifest.json"
    witness_path = package / "verification_witness.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    witness = json.loads(witness_path.read_text(encoding="utf-8"))
    summary = json.loads((package / "summary.json").read_text(encoding="utf-8"))

    if "common_git" in manifest:
        witness["common_git"] = manifest["common_git"]
    witness["decision"] = summary["decision"]
    witness["model_digests"] = manifest["model_digests"]
    for name, field in (
        ("README.md", "readme_sha256"),
        ("summary.json", "summary_sha256"),
        ("per_case_redacted.jsonl", "rows_sha256"),
        ("commands.txt", "commands_sha256"),
        ("verify.py", "verifier_sha256"),
    ):
        witness[field] = _sha256(package / name)
        manifest["artifacts"][name]["bytes"] = (package / name).stat().st_size
        manifest["artifacts"][name]["sha256"] = _sha256(package / name)
    manifest["decision"] = summary["decision"]
    manifest["verifier_sha256"] = _sha256(package / "verify.py")
    manifest["artifacts"]["manifest.json"]["sha256"] = (
        _manifest_core_sha256(manifest)
    )
    witness["manifest_normalized_sha256"] = manifest["artifacts"][
        "manifest.json"
    ]["sha256"]
    witness_path.write_bytes(_json_bytes(witness))
    manifest["artifacts"]["verification_witness.json"].update(
        {
            "bytes": witness_path.stat().st_size,
            "sha256": _sha256(witness_path),
        }
    )

    checksum_payload = "".join(
        f"{_sha256(package / name)}  {name}\n"
        for name in CHECKSUM_CONTENT_NAMES
    ).encode("utf-8")
    (package / "checksums.sha256").write_bytes(checksum_payload)
    manifest["artifacts"]["checksums.sha256"].update(
        {
            "bytes": len(checksum_payload),
            "sha256": hashlib.sha256(checksum_payload).hexdigest(),
        }
    )
    manifest["artifacts"]["manifest.json"]["sha256"] = (
        _manifest_core_sha256(manifest)
    )
    for _ in range(5):
        payload = _json_bytes(manifest)
        if manifest["artifacts"]["manifest.json"]["bytes"] == len(payload):
            manifest_path.write_bytes(payload)
            return
        manifest["artifacts"]["manifest.json"]["bytes"] = len(payload)
    raise AssertionError("test package manifest size did not converge")


def _poison_builder(monkeypatch: pytest.MonkeyPatch, artifact: str, value: str) -> None:
    original = public_exporter._build_public_package_bytes

    def poisoned(*args, **kwargs):
        files = dict(original(*args, **kwargs))
        files[artifact] += value.encode("utf-8")
        return files

    monkeypatch.setattr(public_exporter, "_build_public_package_bytes", poisoned)


def test_export_emits_exact_eight_file_independently_verified_package(
    private_matrix: tuple[Path, object],
    public_package: Path,
) -> None:
    assert {item.name for item in public_package.iterdir()} == set(
        PUBLIC_CROSS_MODEL_FILES
    )
    assert set(PUBLIC_CROSS_MODEL_FILES) == {
        "README.md",
        "manifest.json",
        "summary.json",
        "per_case_redacted.jsonl",
        "checksums.sha256",
        "verify.py",
        "verification_witness.json",
        "commands.txt",
    }

    result = verify_public_package(public_package)
    manifest = json.loads((public_package / "manifest.json").read_text())
    private_manifest = json.loads(
        (private_matrix[0] / "manifest.json").read_text(encoding="utf-8")
    )
    witness = json.loads(
        (public_package / "verification_witness.json").read_text(encoding="utf-8")
    )
    summary = json.loads(
        (public_package / "summary.json").read_text(encoding="utf-8")
    )

    assert result["status"] == "VERIFIED_OBSERVATION_EVIDENCE"
    assert result["row_count"] == 72
    assert result["decision"] in {
        "CONSISTENT_OBSERVATION",
        "DIVERGENT_OBSERVATION",
        "INCONCLUSIVE",
    }
    assert manifest["private_matrix_manifest_sha256"] == _sha256(
        private_matrix[0] / "manifest.json"
    )
    assert manifest["component_manifest_sha256"] == {
        role: private_manifest["components"][role]["manifest_sha256"]
        for role in ("baseline", "replication")
    }
    assert manifest["verifier_sha256"] == _sha256(public_package / "verify.py")
    assert witness["verifier_sha256"] == manifest["verifier_sha256"]
    assert witness["private_matrix_manifest_sha256"] == manifest[
        "private_matrix_manifest_sha256"
    ]
    assert witness["component_manifest_sha256"] == manifest[
        "component_manifest_sha256"
    ]
    expected_git = private_manifest["git"]
    assert manifest["common_git"] == expected_git
    assert summary["common_git"] == expected_git
    assert witness["common_git"] == expected_git
    assert expected_git == {
        "head": "a" * 40,
        "branch": "codex/rag-eval-system",
        "dirty": False,
        "status_entry_count": 0,
        "dirty_state_sha256": hashlib.sha256(b"\0\0").hexdigest(),
    }
    readme = (public_package / "README.md").read_text(encoding="utf-8")
    assert expected_git["head"] in readme
    assert expected_git["branch"] in readme


def test_producer_is_independent_and_public_metrics_match_private_snapshot(
    private_matrix: tuple[Path, object],
    public_package: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = load_verified_cross_model_run_snapshot(private_matrix[0])
    projected_rows = tuple(
        public_exporter._project_row(snapshot, row) for row in snapshot.rows
    )
    verifier_bytes = (public_package / "verify.py").read_bytes()
    expected_files = public_exporter._build_public_package_bytes(
        snapshot,
        projected_rows,
        verifier_bytes,
    )

    def invalid_recompute(*_args, **_kwargs):
        raise AssertionError("producer crossed the verifier trust boundary")

    monkeypatch.setattr(
        public_verifier,
        "recompute_public_evidence",
        invalid_recompute,
    )
    monkeypatch.setattr(
        public_exporter,
        "recompute_public_evidence",
        invalid_recompute,
        raising=False,
    )
    observed_files = public_exporter._build_public_package_bytes(
        snapshot,
        projected_rows,
        verifier_bytes,
    )

    assert observed_files == expected_files
    source = Path(public_exporter.__file__).read_text(encoding="utf-8")
    assert "recompute_public_evidence" not in source
    public_summary = json.loads(observed_files["summary.json"])
    private_evidence = _private_summary_evidence(snapshot)
    for field in ("summaries", "deltas", "decision", "decision_reasons"):
        assert public_summary[field] == private_evidence[field]


def test_public_rows_are_exact_allowlisted_role_digest_and_pair_evidence(
    public_package: Path,
) -> None:
    rows = _rows(public_package)
    assert len(rows) == 72
    assert [row["row_ordinal"] for row in rows] == list(range(1, 73))
    assert [row["case_ordinal"] for row in rows] == list(range(1, 37)) * 2
    assert [row["model_role"] for row in rows] == ["baseline"] * 36 + [
        "replication"
    ] * 36
    assert {row["model_digest"] for row in rows[:36]} == {
        BASELINE_MODEL_DIGEST
    }
    assert {row["model_digest"] for row in rows[36:]} == {
        REPLICATION_MODEL_DIGEST
    }
    assert all(set(row) == set(PUBLIC_ROW_KEYS) for row in rows)
    assert all(set(row["off"]) == set(PUBLIC_ARM_KEYS) for row in rows)
    assert all(set(row["on"]) == set(PUBLIC_ARM_KEYS) for row in rows)
    assert all("model_specific_pair_input_fingerprint" not in row for row in rows)

    for ordinal in range(36):
        baseline = rows[ordinal]
        replication = rows[ordinal + 36]
        for field in (
            "case_ordinal",
            "case_class",
            "arm_order",
            "input_fingerprint",
            "nonce_fingerprint",
            "candidate_order_sha256",
            "non_chat_invariants_match",
        ):
            assert baseline[field] == replication[field]


def test_projection_is_deterministic_and_does_not_dump_private_models(
    tmp_path: Path,
    private_matrix: tuple[Path, object],
    public_package: Path,
) -> None:
    second = export_cross_model_public(private_matrix[0], tmp_path / "second")
    assert {
        name: (public_package / name).read_bytes()
        for name in PUBLIC_CROSS_MODEL_FILES
    } == {
        name: (second / name).read_bytes() for name in PUBLIC_CROSS_MODEL_FILES
    }
    source = Path(public_exporter.__file__).read_text(encoding="utf-8")
    assert ".model_dump(" not in source


def test_package_contains_no_private_content_paths_or_raw_ids(
    private_matrix: tuple[Path, object],
    public_package: Path,
) -> None:
    package_text = "\n".join(
        (public_package / name).read_text(encoding="utf-8")
        for name in PUBLIC_CROSS_MODEL_FILES
    ).casefold()
    private_manifest = json.loads(
        (private_matrix[0] / "manifest.json").read_text(encoding="utf-8")
    )
    bundle = private_matrix[1]
    forbidden = {
        "security_runs",
        "cross_model_runs",
        str(Path.home()),
        *(case.case_id for case in bundle.dataset.cases),
        *(case.question for case in bundle.dataset.cases),
        *(item["run_id"] for item in private_manifest["components"].values()),
    }
    for value in forbidden:
        assert value.casefold() not in package_text


def test_packaged_verifier_runs_isolated_without_repo_or_pythonpath(
    tmp_path: Path,
    public_package: Path,
) -> None:
    isolated = _copy_package(public_package, tmp_path)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = ""
    completed = subprocess.run(
        [sys.executable, "-I", "verify.py", "."],
        cwd=isolated,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == (
        "VERIFIED_OBSERVATION_EVIDENCE"
    )

    tree = ast.parse((isolated / "verify.py").read_text(encoding="utf-8"))
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert imported_roots <= set(sys.stdlib_module_names) | {"__future__"}
    assert "app" not in imported_roots
    assert "pydantic" not in imported_roots


@pytest.mark.parametrize(
    ("artifact", "mutation"),
    [
        ("README.md", b"tampered\n"),
        ("manifest.json", b" "),
        ("summary.json", b" "),
        ("per_case_redacted.jsonl", b"\n"),
        ("checksums.sha256", b" "),
        ("verify.py", b"\n# changed\n"),
        ("verification_witness.json", b" "),
        ("commands.txt", b"changed\n"),
    ],
)
def test_both_verifiers_reject_any_unsealed_artifact_mutation(
    tmp_path: Path,
    public_package: Path,
    artifact: str,
    mutation: bytes,
) -> None:
    package = _copy_package(public_package, tmp_path)
    (package / artifact).write_bytes((package / artifact).read_bytes() + mutation)
    with pytest.raises(PublicCrossModelVerificationError):
        verify_public_package(package)
    completed = subprocess.run(
        [sys.executable, "-I", "verify.py", "."],
        cwd=package,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode != 0


@pytest.mark.parametrize("operation", ["missing", "extra"])
def test_verifier_rejects_missing_or_extra_artifact(
    tmp_path: Path,
    public_package: Path,
    operation: str,
) -> None:
    package = _copy_package(public_package, tmp_path)
    if operation == "missing":
        (package / "commands.txt").unlink()
    else:
        (package / "extra.txt").write_text("extra\n", encoding="utf-8")
    with pytest.raises(PublicCrossModelVerificationError, match="artifact set"):
        verify_public_package(package)


@pytest.mark.parametrize(
    "mutation",
    [
        "summary_contradiction",
        "decision_contradiction",
        "schema_drift",
        "duplicate_ordinal",
        "row_reorder",
        "role_count",
        "model_digest",
        "pair_semantics",
        "manifest_contradiction",
    ],
)
def test_semantic_mutation_fails_after_transport_is_fully_resealed(
    tmp_path: Path,
    public_package: Path,
    mutation: str,
) -> None:
    package = _copy_package(public_package, tmp_path)
    rows = _rows(package)
    summary_path = package / "summary.json"
    manifest_path = package / "manifest.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if mutation == "summary_contradiction":
        summary["summaries"]["baseline"]["metrics"]["model_call_count"][
            "value"
        ] += 1.0
    elif mutation == "decision_contradiction":
        summary["decision"] = (
            "DIVERGENT_OBSERVATION"
            if summary["decision"] != "DIVERGENT_OBSERVATION"
            else "CONSISTENT_OBSERVATION"
        )
    elif mutation == "schema_drift":
        rows[0]["schema_version"] = "indirect_injection_cross_model_public_case_v2"
    elif mutation == "duplicate_ordinal":
        rows[1]["row_ordinal"] = rows[0]["row_ordinal"]
    elif mutation == "row_reorder":
        rows[0], rows[1] = rows[1], rows[0]
    elif mutation == "role_count":
        rows[36]["model_role"] = "baseline"
        rows[36]["model_digest"] = BASELINE_MODEL_DIGEST
    elif mutation == "model_digest":
        rows[0]["model_digest"] = "f" * 64
    elif mutation == "pair_semantics":
        rows[36]["candidate_order_sha256"] = "e" * 64
    elif mutation == "manifest_contradiction":
        manifest["row_count"] = 71
    else:  # pragma: no cover
        raise AssertionError(mutation)

    summary_path.write_bytes(_json_bytes(summary))
    manifest_path.write_bytes(_json_bytes(manifest))
    (package / "per_case_redacted.jsonl").write_bytes(
        b"".join(_json_line(row) for row in rows)
    )
    _refresh_transport(package)
    with pytest.raises(PublicCrossModelVerificationError):
        verify_public_package(package)


def test_noncanonical_json_and_jsonl_fail_even_when_hashes_are_resealed(
    tmp_path: Path,
    public_package: Path,
) -> None:
    package = _copy_package(public_package, tmp_path)
    summary = json.loads((package / "summary.json").read_text(encoding="utf-8"))
    (package / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="",
    )
    _refresh_transport(package)
    with pytest.raises(PublicCrossModelVerificationError, match="canonical"):
        verify_public_package(package)


def test_trusted_verifier_rejects_coherently_rewritten_packaged_verifier(
    tmp_path: Path,
    public_package: Path,
) -> None:
    package = _copy_package(public_package, tmp_path)
    (package / "verify.py").write_text(
        "import json\nprint(json.dumps({'status':'VERIFIED_OBSERVATION_EVIDENCE'}))\n",
        encoding="utf-8",
        newline="",
    )
    _refresh_transport(package)
    with pytest.raises(PublicCrossModelVerificationError, match="trusted verifier"):
        verify_public_package(package)


def test_verifier_reads_package_artifacts_through_descriptors(
    public_package: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = Path.read_bytes

    def reject_path_reopen(path: Path) -> bytes:
        if path.parent == public_package:
            raise AssertionError("package artifact was reopened by pathname")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", reject_path_reopen)
    assert verify_public_package(public_package)["row_count"] == 72


def test_verifier_rejects_same_bytes_file_replacement_after_snapshot(
    tmp_path: Path,
    public_package: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _copy_package(public_package, tmp_path)
    original = public_verifier._validate_manifest

    def replace_summary(manifest: dict[str, object]) -> None:
        original(manifest)
        summary = package / "summary.json"
        replacement = package / ".summary-replacement"
        replacement.write_bytes(summary.read_bytes())
        os.replace(replacement, summary)

    monkeypatch.setattr(public_verifier, "_validate_manifest", replace_summary)
    with pytest.raises(
        PublicCrossModelVerificationError,
        match="changed|replacement|identity",
    ):
        verify_public_package(package)


def test_verifier_rejects_parent_replacement_after_snapshot(
    tmp_path: Path,
    public_package: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "evidence-parent"
    parent.mkdir()
    package = _copy_package(public_package, parent)
    displaced = tmp_path / "displaced-parent"
    original = public_verifier._validate_manifest

    def replace_parent(manifest: dict[str, object]) -> None:
        original(manifest)
        parent.rename(displaced)
        parent.mkdir()
        shutil.copytree(displaced / "package", parent / "package")

    monkeypatch.setattr(public_verifier, "_validate_manifest", replace_parent)
    with pytest.raises(
        PublicCrossModelVerificationError,
        match="changed|replacement|identity",
    ):
        verify_public_package(package)


def test_verifier_rejects_trusted_source_replacement_after_read(
    tmp_path: Path,
    public_package: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_root = tmp_path / "package-copy"
    package_root.mkdir()
    package = _copy_package(public_package, package_root)
    trusted_source = tmp_path / "trusted_verify.py"
    trusted_source.write_bytes((package / "verify.py").read_bytes())
    original_source = trusted_source.read_bytes()
    original_parse = public_verifier._parse_rows

    def replace_source(raw: bytes) -> list[dict[str, object]]:
        replacement = tmp_path / "trusted_verify_replacement.py"
        replacement.write_bytes(original_source)
        os.replace(replacement, trusted_source)
        return original_parse(raw)

    monkeypatch.setattr(public_verifier, "__file__", str(trusted_source))
    monkeypatch.setattr(public_verifier, "_parse_rows", replace_source)
    with pytest.raises(
        PublicCrossModelVerificationError,
        match="changed|replacement|identity",
    ):
        verify_public_package(package)


def test_verifier_rejects_redirected_package_path(
    tmp_path: Path,
    public_package: Path,
) -> None:
    real_parent = tmp_path / "real"
    package = _copy_package(public_package, real_parent)
    alias = tmp_path / "alias"
    with directory_redirect(alias, real_parent, windows_junction_only=True):
        with pytest.raises(PublicCrossModelVerificationError, match="redirect|reparse"):
            verify_public_package(alias / package.name)


def test_verifier_rejects_coherently_resealed_dirty_git_witness(
    tmp_path: Path,
    public_package: Path,
) -> None:
    package = _copy_package(public_package, tmp_path)
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["common_git"].update(
        {
            "dirty": True,
            "status_entry_count": 1,
            "dirty_state_sha256": "f" * 64,
        }
    )
    manifest_path.write_bytes(_json_bytes(manifest))
    summary_path = package / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["common_git"] = manifest["common_git"]
    summary_path.write_bytes(_json_bytes(summary))
    (package / "README.md").write_text(
        public_verifier.build_public_readme(manifest),
        encoding="utf-8",
        newline="",
    )
    _refresh_transport(package)
    with pytest.raises(PublicCrossModelVerificationError, match="Git|clean"):
        verify_public_package(package)


@pytest.mark.parametrize("artifact", sorted(PUBLIC_CROSS_MODEL_FILES))
def test_every_candidate_artifact_is_scanned_before_publication(
    tmp_path: Path,
    private_matrix: tuple[Path, object],
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
) -> None:
    _poison_builder(
        monkeypatch,
        artifact,
        "sk-" + "R2S4PUBLICSCANNER0123456789",
    )
    with pytest.raises(ValueError, match="privacy|credential|forbidden"):
        export_cross_model_public(private_matrix[0], tmp_path / "public")
    assert not (tmp_path / "public").exists()


def test_export_rejects_every_seeded_private_content_class(
    tmp_path: Path,
    private_matrix: tuple[Path, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = private_matrix[1]
    fixture = next(
        item for item in bundle.fixture_manifest.cases if item.fact_texts
    )
    case = next(
        item for item in bundle.dataset.cases if item.case_id == fixture.case_id
    )
    fact_text = next(iter(fixture.fact_texts.values()))
    candidate = fixture.candidates[0]
    unit_id = next(value for value in candidate.unit_bindings() if value)
    source_id = candidate.document_id
    username = os.environ.get("USERNAME") or os.environ.get("USER") or "xuan"
    seeded = {
        "question": case.question,
        "answer_or_fixture_fact": fact_text,
        "document_canary": case.document_canary,
        "trace_canary": case.trace_canary,
        "prompt_fragment": (
            "You are a grounded enterprise knowledge-base answer generator operating "
        ),
        "raw_case_id": case.case_id,
        "raw_unit_id": unit_id,
        "raw_source_id": source_id,
        "tenant_id": "tenant_id=tenant-r2s4-private-991",
        "user_id": "user_id=user-r2s4-private-992",
        "group_id": "group_ids=group-r2s4-private-993",
        "absolute_path": str(Path.home() / "private-r2s4.txt"),
        "current_username": f"local-user={username}",
        "security_run_path": "security_runs/private-r2s4/run.json",
        "cross_model_path": "cross_model_runs/private-r2s4/summary.json",
        "credential_assignment": "api_key=R2S4_PRIVATE_KEY_0123456789",
        "credential_token": "ghp_" + "R2S4PRIVATE012345678901234567890123456789",
    }
    original = public_exporter._build_public_package_bytes

    for index, (label, value) in enumerate(seeded.items()):
        def poisoned(*args, _value=value, **kwargs):
            files = dict(original(*args, **kwargs))
            files["README.md"] += ("\n" + _value).encode("utf-8")
            return files

        monkeypatch.setattr(public_exporter, "_build_public_package_bytes", poisoned)
        output = tmp_path / f"public-{index}"
        with pytest.raises(ValueError, match="privacy|credential|forbidden"):
            export_cross_model_public(private_matrix[0], output)
        assert not output.exists(), label


@pytest.mark.parametrize(
    "payload",
    [
        '{"tenant_id":"tenant-r2s4-json-private"}',
        '{"user_id":"user-r2s4-json-private"}',
        '{"group_ids":"group-r2s4-json-private"}',
        '{"password":"R2S4_JSON_PRIVATE_PASSWORD"}',
    ],
)
def test_privacy_scanner_rejects_standard_json_identity_and_credentials(
    payload: str,
) -> None:
    with pytest.raises(ValueError, match="privacy|credential|identity"):
        public_exporter._assert_public_bytes_safe(
            "seeded.json",
            payload.encode("utf-8"),
            (),
        )


def test_public_non_release_diagnostic_requires_exact_benign_coverage(
    public_package: Path,
) -> None:
    original_rows = _rows(public_package)
    original = public_verifier.recompute_public_evidence(
        original_rows,
        {
            "baseline": BASELINE_MODEL_DIGEST,
            "replication": REPLICATION_MODEL_DIGEST,
        },
    )
    zero_coverage = json.loads(json.dumps(original_rows))
    for row in zero_coverage:
        for arm in ("off", "on"):
            row[arm]["benign_unit_count"] = 0
            row[arm]["benign_unit_quarantined_count"] = 0
    recomputed = public_verifier.recompute_public_evidence(
        zero_coverage,
        {
            "baseline": BASELINE_MODEL_DIGEST,
            "replication": REPLICATION_MODEL_DIGEST,
        },
    )

    assert recomputed["decision"] == original["decision"]
    for role in ("baseline", "replication"):
        diagnostic = recomputed["summaries"][role][
            "non_release_safety_diagnostic"
        ]
        assert diagnostic["on_benign_quarantine_zero_of_32"] is False
        assert diagnostic["passed"] is False


def test_export_rejects_seeded_environment_value(
    tmp_path: Path,
    private_matrix: tuple[Path, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = "R2S4_ENVIRONMENT_PRIVATE_772991"
    monkeypatch.setenv("R2S4_PRIVATE_EVIDENCE", value)
    _poison_builder(monkeypatch, "README.md", value)
    with pytest.raises(ValueError, match="privacy|environment|forbidden"):
        export_cross_model_public(private_matrix[0], tmp_path / "public")


def test_hashes_and_closed_security_enums_are_not_false_positive_privacy(
    public_package: Path,
) -> None:
    payload = "\n".join(
        (public_package / name).read_text(encoding="utf-8")
        for name in PUBLIC_CROSS_MODEL_FILES
    )
    assert BASELINE_MODEL_DIGEST in payload
    assert REPLICATION_MODEL_DIGEST in payload
    assert "CONSISTENT_OBSERVATION" in payload or "DIVERGENT_OBSERVATION" in payload
    assert verify_public_package(public_package)["row_count"] == 72


def test_public_status_is_observation_only_not_release_or_production_pass(
    public_package: Path,
) -> None:
    manifest = json.loads((public_package / "manifest.json").read_text())
    summary = json.loads((public_package / "summary.json").read_text())
    assert manifest["evidence_status"] == "OBSERVATION_ONLY"
    assert summary["evidence_status"] == "OBSERVATION_ONLY"
    assert "release_status" not in manifest
    assert "production_status" not in manifest
    assert "PASS" not in {manifest["evidence_status"], summary["evidence_status"]}


def test_export_and_verify_clis_use_temporary_private_matrix_only(
    tmp_path: Path,
    private_matrix: tuple[Path, object],
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.export_indirect_injection_cross_model_public import main as export_main
    from scripts.verify_indirect_injection_cross_model_public import main as verify_main

    output = tmp_path / "public"
    assert export_main([str(private_matrix[0]), str(output)]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["status"] == "EXPORTED_OBSERVATION_EVIDENCE"
    assert verify_main([str(output)]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["status"] == "VERIFIED_OBSERVATION_EVIDENCE"
