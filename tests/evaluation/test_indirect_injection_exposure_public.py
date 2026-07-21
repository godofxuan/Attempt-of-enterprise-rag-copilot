from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from app.evaluation import indirect_injection_exposure_public as public_writer
from app.evaluation import indirect_injection_exposure_writer as private_writer
from app.evaluation.indirect_injection_dataset import load_security_bundle
from app.evaluation.indirect_injection_exposure import (
    EXPOSURE_LIMITATIONS,
    ExposureAnalysisResult,
    ExposureUnitObservation,
    _build_exposure_strata,
    compute_exposure_unit_evidence_sha256,
)
from app.evaluation.indirect_injection_exposure_public import (
    export_exposure_public_evidence,
)
from app.evaluation.indirect_injection_exposure_public_verifier import (
    METRIC_DEFINITIONS,
    PUBLIC_EXPOSURE_FILES,
    PUBLIC_UNIT_ROW_KEYS,
    ExposurePublicVerificationError,
    verify_exposure_public_package,
)
from scripts import export_indirect_injection_exposure_public as export_cli
from scripts.export_indirect_injection_exposure_public import main as export_main
from scripts.verify_indirect_injection_exposure_public import main as verify_main
from tests.evaluation.test_indirect_injection_exposure import source_material
from tests.evaluation.test_indirect_injection_exposure_writer import (
    _publish,
    exposure_result,
    verification_inputs,
)
from tests.evaluation.path_redirect_helpers import (
    directory_redirect,
    with_reparse_point_attribute,
)


CHECKSUM_NAMES = tuple(sorted(PUBLIC_EXPOSURE_FILES - {"checksums.sha256"}))
FORMAL_SCENARIO_TAGS = (
    "mixed_clean_poison",
    "poison_only",
    "top_ranked_poison",
    "same_chunk_fact_attack",
    "title_section_metadata",
    "parent_open_context",
    "split_payload",
)
PUBLISHED_AGGREGATE_DEFINITION_NAMES = {
    "arm_event_count",
    "attack_case_count",
    "attack_unit_count",
    "benign_case_count",
    "benign_quarantine",
    "benign_quarantine_count",
    "benign_unit_count",
    "blocked_egress_attempt_count",
    "candidate_pool_presence",
    "case_count",
    "clean_case_count",
    "clean_task_success",
    "clean_task_success_count",
    "consumed_tool_paths_guard_covered",
    "counterfactual_search_reach",
    "counterfactual_total_reach",
    "decision",
    "live_guard_quarantine",
    "live_guard_reach",
    "model_error_count",
    "off_then_on_count",
    "on_then_off_count",
    "quarantine_given_live_guard_reach",
    "replay_additional_scan_input_chars",
    "replay_additional_scan_units",
    "replay_guard_quarantine",
    "replay_guard_reach",
    "replay_live_aggregate_match",
    "replay_selected_attack_units",
    "row_count",
    "search_addressable_attack_unit_count",
    "unreached_attack_unit_count",
    "unreached_case_attack_success",
    "unreached_case_count",
    "unreached_case_downstream_exposure",
}
PUBLIC_ROW_IDENTITY_FIELDS = {
    "case_fingerprint",
    "unit_fingerprint",
}
PUBLIC_ROW_METADATA_FIELDS = {
    "category",
    "location",
    "scenario_tags",
    "schema_version",
    "source_surface",
}
MAX_WIRE_DNS_HOSTNAME = ".".join(
    ("a" * 63, "b" * 63, "c" * 63, "d" * 61)
)
OVERLONG_WIRE_DNS_HOSTNAME = ".".join(
    ("a" * 63, "b" * 63, "c" * 63, "d" * 62)
)
REPLAY_DEPENDENCY_PAYLOADS = (
    {
        "dependency_id": "guard_ruleset",
        "path": "app/security/retrieved_content.py",
        "sha256": (
            "78ed0509144820ccd05aff61c1509357dd8fe3dbfc8a0c6df30fc304a15e9cd2"
        ),
    },
    {
        "dependency_id": "retrieved_admission",
        "path": "app/security/retrieved_admission.py",
        "sha256": (
            "1f835ba3aa79b1450e8ae906946bba019c21b531fce114cd375b094411c88afb"
        ),
    },
    {
        "dependency_id": "search_surface_constructor",
        "path": "app/evaluation/indirect_injection_runner.py",
        "sha256": (
            "c2c5c5e1815d8a77beebb5027384ea58dd3e73b8536533c8d7898d40668ed36c"
        ),
    },
    {
        "dependency_id": "source_live_evaluator",
        "path": "app/evaluation/indirect_injection_live_runner.py",
        "sha256": (
            "a5eec5619a5ac9f44357fc6063232dca6021538ca5988aab6ae2f962d9b85958"
        ),
    },
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_bytes(package: Path) -> dict[str, bytes]:
    return {
        item.name: item.read_bytes()
        for item in sorted(package.iterdir(), key=lambda value: value.name)
    }


def _rows(package: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (package / "per_unit.redacted.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]


def _refresh_checksums(package: Path) -> None:
    (package / "checksums.sha256").write_bytes(
        "".join(
            f"{_sha256(package / name)}  {name}\n" for name in CHECKSUM_NAMES
        ).encode("utf-8")
    )


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="",
    )


def _with_two_scenario_tags(
    result: ExposureAnalysisResult,
) -> ExposureAnalysisResult:
    units = list(result.units)
    first_tag = units[0].scenario_tags[0]
    second_tag = next(tag for tag in FORMAL_SCENARIO_TAGS if tag != first_tag)
    units[0] = units[0].model_copy(
        update={"scenario_tags": (first_tag, second_tag)}
    )
    updated_units = tuple(units)
    return result.model_copy(
        update={
            "units": updated_units,
            "unit_evidence_sha256": compute_exposure_unit_evidence_sha256(
                updated_units
            ),
            "strata": _build_exposure_strata(updated_units),
        }
    )


def _reorder_summary_bytes(source_run: Path) -> None:
    path = source_run / "summary.json"
    payload = json.loads(path.read_bytes())
    reordered = {key: payload[key] for key in reversed(tuple(payload))}
    path.write_text(
        json.dumps(reordered, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )


def _reorder_first_scenario_tags(source_run: Path) -> None:
    path = source_run / "per_unit.jsonl"
    lines = path.read_bytes().splitlines()
    payload = json.loads(lines[0])
    original_tags = tuple(payload["scenario_tags"])
    assert len(original_tags) == 2
    payload["scenario_tags"] = list(reversed(original_tags))
    lines[0] = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    path.write_bytes(b"\n".join(lines) + b"\n")


@pytest.fixture
def formal_exposure_result(
    exposure_result: ExposureAnalysisResult,
) -> ExposureAnalysisResult:
    units = tuple(
        ExposureUnitObservation.model_validate(
            {
                **item.model_dump(mode="python"),
                "scenario_tags": (FORMAL_SCENARIO_TAGS[index % 7],),
            }
        )
        for index, item in enumerate(exposure_result.units)
    )
    return ExposureAnalysisResult(
        schema_version=exposure_result.schema_version,
        source=exposure_result.source,
        units=units,
        unit_evidence_sha256=compute_exposure_unit_evidence_sha256(units),
        verification_inputs=exposure_result.verification_inputs,
        verification_inputs_sha256=(
            exposure_result.verification_inputs_sha256
        ),
        summary=exposure_result.summary,
        strata=_build_exposure_strata(units),
        decision=exposure_result.decision,
        unguarded_path_findings=exposure_result.unguarded_path_findings,
        limitations=exposure_result.limitations,
    )


@pytest.fixture
def private_exposure_run(
    tmp_path: Path,
    formal_exposure_result: ExposureAnalysisResult,
) -> Path:
    return _publish(tmp_path / "private", formal_exposure_result)


@pytest.fixture
def public_exposure_package(
    tmp_path: Path,
    private_exposure_run: Path,
) -> Path:
    return export_exposure_public_evidence(
        private_exposure_run,
        tmp_path / "public",
        package_name="fixture",
        expected_source_manifest_sha256=_sha256(
            private_exposure_run / "manifest.json"
        ),
        expected_source_run_id=private_exposure_run.name,
        forbidden_texts=("raw question", "raw attack"),
    )


def test_public_producer_emits_v2_dependency_manifest(
    public_exposure_package: Path,
) -> None:
    manifest = json.loads(
        (public_exposure_package / "manifest.redacted.json").read_text(
            encoding="utf-8"
        )
    )

    assert manifest["schema_version"] == (
        "indirect_injection_exposure_public_manifest_v2"
    )
    assert tuple(manifest["replay_dependencies"]) == REPLAY_DEPENDENCY_PAYLOADS


def test_public_v2_manifest_requires_dependency_schema(
    public_exposure_package: Path,
    tmp_path: Path,
) -> None:
    target = shutil.copytree(public_exposure_package, tmp_path / "missing-deps")
    manifest_path = target / "manifest.redacted.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = (
        "indirect_injection_exposure_public_manifest_v2"
    )
    manifest.pop("replay_dependencies", None)
    _write_json(manifest_path, manifest)
    _refresh_checksums(target)

    with pytest.raises(
        ExposurePublicVerificationError,
        match="public manifest keys",
    ):
        verify_exposure_public_package(target)


@pytest.mark.parametrize("dependency_index", range(4))
@pytest.mark.parametrize("field", ("path", "sha256"))
def test_public_v2_manifest_rejects_dependency_substitution(
    public_exposure_package: Path,
    tmp_path: Path,
    dependency_index: int,
    field: str,
) -> None:
    target = shutil.copytree(
        public_exposure_package,
        tmp_path / f"dependency-{dependency_index}-{field}",
    )
    manifest_path = target / "manifest.redacted.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = (
        "indirect_injection_exposure_public_manifest_v2"
    )
    dependencies = [dict(item) for item in REPLAY_DEPENDENCY_PAYLOADS]
    dependencies[dependency_index][field] = (
        "app/evaluation/substituted.py" if field == "path" else "0" * 64
    )
    manifest["replay_dependencies"] = dependencies
    _write_json(manifest_path, manifest)
    _refresh_checksums(target)

    with pytest.raises(
        ExposurePublicVerificationError,
        match="replay dependencies",
    ):
        verify_exposure_public_package(target)


def test_trusted_verifier_accepts_current_tracked_v2_package() -> None:
    assert verify_exposure_public_package(
        Path("data/v2/public/r2_s3_exposure")
    ).verified is True


def test_public_verifier_reads_each_package_file_once(
    public_exposure_package: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = public_exposure_package.resolve()
    real_read_bytes = Path.read_bytes
    reads = {name: 0 for name in PUBLIC_EXPOSURE_FILES}

    def counted_read(path: Path) -> bytes:
        if path.parent.resolve() == package and path.name in reads:
            reads[path.name] += 1
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", counted_read)

    assert verify_exposure_public_package(package).verified is True
    assert reads == {name: 1 for name in PUBLIC_EXPOSURE_FILES}


def test_public_verifier_rejects_file_mutation_during_snapshot_read(
    public_exposure_package: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary_path = (public_exposure_package / "summary.json").resolve()
    original = summary_path.read_bytes()
    replacement = original.replace(b'  "', b' \t"', 1)
    assert replacement != original
    assert len(replacement) == len(original)
    real_read_bytes = Path.read_bytes
    real_write_bytes = Path.write_bytes
    changed = False

    def read_then_mutate(path: Path) -> bytes:
        nonlocal changed
        payload = real_read_bytes(path)
        if path.resolve() == summary_path and not changed:
            changed = True
            real_write_bytes(path, replacement)
        return payload

    monkeypatch.setattr(Path, "read_bytes", read_then_mutate)

    with pytest.raises(
        ExposurePublicVerificationError,
        match="public artifact changed during verification: summary.json",
    ):
        verify_exposure_public_package(public_exposure_package)


def test_public_verifier_rejects_real_windows_package_junction(
    public_exposure_package: Path,
    tmp_path: Path,
) -> None:
    package_alias = tmp_path / "public-package-junction"

    with directory_redirect(
        package_alias,
        public_exposure_package,
        windows_junction_only=True,
    ):
        with pytest.raises(
            ExposurePublicVerificationError,
            match="redirecting reparse point",
        ):
            verify_exposure_public_package(package_alias)

    assert public_exposure_package.is_dir()


def test_public_verifier_rejects_mocked_package_reparse_root(
    public_exposure_package: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = public_exposure_package.absolute()
    real_lstat = Path.lstat

    def mark_package_root(path: Path):
        observed = real_lstat(path)
        if path == package:
            return with_reparse_point_attribute(observed)
        return observed

    monkeypatch.setattr(Path, "lstat", mark_package_root)

    with pytest.raises(
        ExposurePublicVerificationError,
        match="redirecting reparse point",
    ):
        verify_exposure_public_package(package)


def test_protocol_uses_byte_binding_and_trusted_manifest_language() -> None:
    protocol = Path(
        "docs/security/r2_s3/00_exposure_ablation_protocol.md"
    ).read_text(encoding="utf-8")

    assert "binds the exact bytes" in protocol
    assert "trusted manifest" in protocol
    assert "authenticates the frozen source behavior" not in protocol
    assert "authenticates the evaluator" not in protocol


def test_public_export_is_exact_content_free_and_deterministic(
    tmp_path: Path,
    private_exposure_run: Path,
    formal_exposure_result: ExposureAnalysisResult,
) -> None:
    kwargs = {
        "package_name": "fixture",
        "expected_source_manifest_sha256": _sha256(
            private_exposure_run / "manifest.json"
        ),
        "expected_source_run_id": private_exposure_run.name,
        "forbidden_texts": ("raw question", "raw attack"),
    }
    first = export_exposure_public_evidence(
        private_exposure_run, tmp_path / "first", **kwargs
    )
    second = export_exposure_public_evidence(
        private_exposure_run, tmp_path / "second", **kwargs
    )

    assert {item.name for item in first.iterdir()} == set(PUBLIC_EXPOSURE_FILES)
    assert _artifact_bytes(first) == _artifact_bytes(second)
    public_bytes = b"".join(_artifact_bytes(first).values())
    private_ids = {
        value
        for item in formal_exposure_result.units
        for value in (item.case_id, item.unit_id)
    }
    assert all(value.encode("utf-8") not in public_bytes for value in private_ids)
    assert b"raw question" not in public_bytes
    assert b"raw attack" not in public_bytes
    assert verify_exposure_public_package(first).verified is True


def test_export_reads_each_private_artifact_once_from_verified_bytes(
    private_exposure_run: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_manifest_sha256 = _sha256(
        private_exposure_run / "manifest.json"
    )
    source_reads = {
        name: 0 for name in private_writer.PRIVATE_EXPOSURE_ARTIFACT_FILES
    }
    read_bytes = Path.read_bytes
    read_text = Path.read_text

    def count_source_bytes(path: Path) -> bytes:
        if path.parent == private_exposure_run and path.name in source_reads:
            source_reads[path.name] += 1
        return read_bytes(path)

    def reject_source_text(path: Path, *args, **kwargs) -> str:
        if path.parent == private_exposure_run and path.name in source_reads:
            raise AssertionError(f"source artifact reread as text: {path.name}")
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", count_source_bytes)
    monkeypatch.setattr(Path, "read_text", reject_source_text)

    target = export_exposure_public_evidence(
        private_exposure_run,
        tmp_path / "public",
        package_name="fixture",
        expected_source_manifest_sha256=expected_manifest_sha256,
        expected_source_run_id=private_exposure_run.name,
        forbidden_texts=("raw question", "raw attack"),
    )

    assert target.is_dir()
    assert source_reads == {
        name: 1 for name in private_writer.PRIVATE_EXPOSURE_ARTIFACT_FILES
    }


@pytest.mark.parametrize(
    ("mutation", "mutate_source"),
    (
        ("summary-byte-order", _reorder_summary_bytes),
        ("scenario-tag-order", _reorder_first_scenario_tags),
    ),
)
def test_export_rejects_mutation_after_verified_source_snapshot(
    mutation: str,
    mutate_source,
    formal_exposure_result: ExposureAnalysisResult,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = (
        _with_two_scenario_tags(formal_exposure_result)
        if mutation == "scenario-tag-order"
        else formal_exposure_result
    )
    source_run = _publish(tmp_path / "private", result)
    output = tmp_path / "public"
    expected_manifest_sha256 = _sha256(source_run / "manifest.json")
    mutation_observed = False
    assert_unchanged = getattr(
        public_writer,
        "_assert_snapshot_unchanged",
        lambda _snapshot: None,
    )

    def mutate_then_assert(snapshot) -> None:
        nonlocal mutation_observed
        mutate_source(source_run)
        mutation_observed = True
        assert_unchanged(snapshot)

    monkeypatch.setattr(
        public_writer,
        "_assert_snapshot_unchanged",
        mutate_then_assert,
        raising=False,
    )

    with pytest.raises(ValueError, match="changed after verified snapshot"):
        export_exposure_public_evidence(
            source_run,
            output,
            package_name="fixture",
            expected_source_manifest_sha256=expected_manifest_sha256,
            expected_source_run_id=source_run.name,
            forbidden_texts=("raw question", "raw attack"),
        )

    assert mutation_observed is True
    assert not (output / "fixture").exists()
    if output.exists():
        assert not tuple(output.glob(".*.staging-*"))


@pytest.mark.parametrize(
    "mutation",
    ("omission", "replacement", "duplication", "reordering"),
)
def test_public_verifier_requires_exact_ordered_limitations(
    tmp_path: Path,
    mutation: str,
) -> None:
    public_exposure_package = tmp_path / "package"
    shutil.copytree(
        Path("data/v2/public/r2_s3_exposure"),
        public_exposure_package,
    )
    limitations = list(EXPOSURE_LIMITATIONS)
    if mutation == "omission":
        changed = limitations[:-1]
    elif mutation == "replacement":
        changed = [*limitations[:-1], "Replacement limitation."]
    elif mutation == "duplication":
        changed = [*limitations, limitations[0]]
    else:
        changed = list(reversed(limitations))

    for name in ("manifest.redacted.json", "summary.json"):
        path = public_exposure_package / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["limitations"] = changed
        _write_json(path, payload)
    _refresh_checksums(public_exposure_package)

    with pytest.raises(
        ExposurePublicVerificationError,
        match="public limitations",
    ):
        verify_exposure_public_package(public_exposure_package)


def test_public_rows_use_exact_keys_fingerprints_and_order(
    public_exposure_package: Path,
    private_exposure_run: Path,
    formal_exposure_result: ExposureAnalysisResult,
) -> None:
    rows = _rows(public_exposure_package)
    assert len(rows) == 28
    assert all(set(row) == set(PUBLIC_UNIT_ROW_KEYS) for row in rows)
    assert all("case_id" not in row and "unit_id" not in row for row in rows)
    identities = tuple(
        (row["case_fingerprint"], row["unit_fingerprint"]) for row in rows
    )
    assert identities == tuple(sorted(identities))
    first_private = formal_exposure_result.units[0]
    expected_case = hashlib.sha256(
        (
            "r2-s3-case-v1\0"
            + private_exposure_run.name
            + "\0"
            + first_private.case_id
        ).encode("utf-8")
    ).hexdigest()
    expected_unit = hashlib.sha256(
        (
            "r2-s3-unit-v1\0"
            + private_exposure_run.name
            + "\0"
            + first_private.case_id
            + "\0"
            + first_private.unit_id
        ).encode("utf-8")
    ).hexdigest()
    projected = next(
        row for row in rows if row["unit_fingerprint"] == expected_unit
    )
    assert projected["case_fingerprint"] == expected_case
    assert re.fullmatch(r"[0-9a-f]{64}", projected["unit_fingerprint"])


@pytest.mark.parametrize("mutation", ("row", "summary", "checksum"))
def test_standalone_verifier_rejects_tampering(
    public_exposure_package: Path,
    tmp_path: Path,
    mutation: str,
) -> None:
    target = shutil.copytree(public_exposure_package, tmp_path / mutation)
    if mutation == "row":
        rows = (target / "per_unit.redacted.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        payloads = [json.loads(row) for row in rows]
        index = next(
            index
            for index, row in enumerate(payloads)
            if not row["replay_guard_reached"]
            and sum(
                other["case_fingerprint"] == row["case_fingerprint"]
                for other in payloads
            )
            == 1
        )
        payloads[index]["case_attack_success"] = True
        rows[index] = json.dumps(
            payloads[index],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        (target / "per_unit.redacted.jsonl").write_text(
            "\n".join(rows) + "\n", encoding="utf-8", newline=""
        )
        _refresh_checksums(target)
    elif mutation == "summary":
        payload = json.loads((target / "summary.json").read_text(encoding="utf-8"))
        payload["summary"]["clean_task_success"]["numerator"] = 11
        payload["summary"]["clean_task_success"]["rate"] = 11 / 12
        (target / "summary.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="",
        )
        _refresh_checksums(target)
    else:
        (target / "README.md").write_bytes(b"tampered\n")

    with pytest.raises(ExposurePublicVerificationError):
        verify_exposure_public_package(target)


def test_copied_verifier_runs_without_project_imports(
    public_exposure_package: Path,
    tmp_path: Path,
) -> None:
    isolated = shutil.copytree(public_exposure_package, tmp_path / "isolated")
    source = (isolated / "verify.py").read_text(encoding="utf-8")
    assert "from app" not in source
    assert "pydantic" not in source.lower()
    assert "pytest" not in source.lower()
    completed = subprocess.run(
        [sys.executable, "-I", "verify.py"],
        cwd=isolated,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    output = json.loads(completed.stdout)
    assert output["status"] == "VERIFIED"
    assert output["row_count"] == 28
    result_probe = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import json,runpy;from pathlib import Path;"
                "ns=runpy.run_path('verify.py');"
                "result=ns['verify_exposure_public_package'](Path('.'));"
                "print(json.dumps({'case_count':result.case_count,"
                "'row_count':result.row_count},sort_keys=True))"
            ),
        ],
        cwd=isolated,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result_probe.returncode == 0, result_probe.stderr
    result_output = json.loads(result_probe.stdout)
    assert result_output == {"case_count": 36, "row_count": 28}
    readme = (isolated / "README.md").read_text(encoding="utf-8")
    assert "does not prove that derivation" in readme
    assert "Compare `verify.py` bytes with an independently trusted copy" in readme
    assert "authenticate verifier bytes" not in readme.lower()


def test_verifier_rejects_per_case_live_count_redistribution(
    public_exposure_package: Path,
    tmp_path: Path,
) -> None:
    target = shutil.copytree(public_exposure_package, tmp_path / "redistributed")
    rows = _rows(target)
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row["case_fingerprint"]), []).append(row)
    reached = next(
        values
        for values in grouped.values()
        if values[0]["live_case_guard_reached_count"] == 1
    )
    unreached = next(
        values
        for values in grouped.values()
        if values[0]["live_case_guard_reached_count"] == 0
    )
    for row in reached:
        row["live_case_guard_reached_count"] = 0
        row["live_case_guard_quarantined_count"] = 0
    for row in unreached:
        row["live_case_guard_reached_count"] = 1
        row["live_case_guard_quarantined_count"] = 1
    rows.sort(key=lambda row: (row["case_fingerprint"], row["unit_fingerprint"]))
    (target / "per_unit.redacted.jsonl").write_text(
        "".join(
            json.dumps(
                row,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
        newline="",
    )
    _refresh_checksums(target)

    with pytest.raises(ExposurePublicVerificationError, match="replay/live case"):
        verify_exposure_public_package(target)


@pytest.mark.parametrize("mutation", ("duplicate_manifest_key", "extra_row_key"))
def test_verifier_rejects_schema_and_duplicate_key_tampering(
    public_exposure_package: Path,
    tmp_path: Path,
    mutation: str,
) -> None:
    target = shutil.copytree(public_exposure_package, tmp_path / mutation)
    if mutation == "duplicate_manifest_key":
        raw = (target / "manifest.redacted.json").read_text(encoding="utf-8")
        raw = raw.replace("{", '{"schema_version":"duplicate",', 1)
        (target / "manifest.redacted.json").write_text(
            raw, encoding="utf-8", newline=""
        )
    else:
        lines = (target / "per_unit.redacted.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        payload = json.loads(lines[0])
        payload["private_note"] = "not allowed"
        lines[0] = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        (target / "per_unit.redacted.jsonl").write_text(
            "\n".join(lines) + "\n", encoding="utf-8", newline=""
        )
        _refresh_checksums(target)

    with pytest.raises(ExposurePublicVerificationError):
        verify_exposure_public_package(target)


def test_verifier_rejects_coherent_metric_definition_rewrite(
    public_exposure_package: Path,
    tmp_path: Path,
) -> None:
    target = shutil.copytree(public_exposure_package, tmp_path / "definitions")
    definitions = json.loads(
        (target / "metric_definitions.json").read_text(encoding="utf-8")
    )
    definitions["metrics"]["live_guard_reach"]["interpretation"] = "rewritten"
    (target / "metric_definitions.json").write_text(
        json.dumps(definitions, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="",
    )
    manifest = json.loads(
        (target / "manifest.redacted.json").read_text(encoding="utf-8")
    )
    manifest["metric_definitions_sha256"] = _sha256(
        target / "metric_definitions.json"
    )
    (target / "manifest.redacted.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="",
    )
    _refresh_checksums(target)

    with pytest.raises(ExposurePublicVerificationError, match="not exact"):
        verify_exposure_public_package(target)


def test_repository_verifier_rejects_coherent_packaged_verifier_rewrite(
    public_exposure_package: Path,
    tmp_path: Path,
) -> None:
    target = shutil.copytree(public_exposure_package, tmp_path / "verifier")
    (target / "verify.py").write_text(
        'print("VERIFIED")\n', encoding="utf-8", newline=""
    )
    manifest = json.loads(
        (target / "manifest.redacted.json").read_text(encoding="utf-8")
    )
    manifest["verifier_sha256"] = _sha256(target / "verify.py")
    _write_json(target / "manifest.redacted.json", manifest)
    _refresh_checksums(target)

    completed = subprocess.run(
        [sys.executable, "-I", "verify.py"],
        cwd=target,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    with pytest.raises(ExposurePublicVerificationError, match="trusted verifier"):
        verify_exposure_public_package(target)


@pytest.mark.parametrize(
    ("document_name", "mutate"),
    (
        (
            "manifest.redacted.json",
            lambda value: value.__setitem__(
                "counterfactual_depths", [True, 2, 4]
            ),
        ),
        (
            "summary.json",
            lambda value: value["summary"].__setitem__(
                "attack_unit_count", 28.0
            ),
        ),
        (
            "summary.json",
            lambda value: value["summary"].__setitem__(
                "replay_live_aggregate_match", 1
            ),
        ),
        (
            "summary.json",
            lambda value: value["strata"][0].__setitem__(
                "attack_unit_count",
                float(value["strata"][0]["attack_unit_count"]),
            ),
        ),
    ),
)
def test_verifier_rejects_json_primitive_type_substitution(
    public_exposure_package: Path,
    tmp_path: Path,
    document_name: str,
    mutate,
) -> None:
    target = shutil.copytree(
        public_exposure_package,
        tmp_path / f"types-{document_name}-{len(tuple(tmp_path.iterdir()))}",
    )
    path = target / document_name
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    _write_json(path, value)
    _refresh_checksums(target)

    with pytest.raises(ExposurePublicVerificationError, match="type|depth"):
        verify_exposure_public_package(target)


def test_verifier_rejects_test_only_synthetic_scenario_tag(
    public_exposure_package: Path,
    tmp_path: Path,
) -> None:
    target = shutil.copytree(public_exposure_package, tmp_path / "synthetic-tag")
    rows = _rows(target)
    replaced_tag = FORMAL_SCENARIO_TAGS[0]
    for row in rows:
        row["scenario_tags"] = [
            "synthetic" if tag == replaced_tag else tag
            for tag in row["scenario_tags"]
        ]
    (target / "per_unit.redacted.jsonl").write_text(
        "".join(
            json.dumps(
                row,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
        newline="",
    )
    summary = json.loads((target / "summary.json").read_text(encoding="utf-8"))
    for stratum in summary["strata"]:
        if stratum["dimension"] == "scenario_tag" and stratum["value"] == replaced_tag:
            stratum["value"] = "synthetic"
    dimension_order = {
        "category": 0,
        "source_surface": 1,
        "actual_candidate_rank": 2,
        "scenario_tag": 3,
    }
    summary["strata"].sort(
        key=lambda item: (dimension_order[item["dimension"]], item["value"])
    )
    _write_json(target / "summary.json", summary)
    _refresh_checksums(target)

    with pytest.raises(ExposurePublicVerificationError, match="scenario tags"):
        verify_exposure_public_package(target)


def test_metric_definitions_cover_aggregate_count_status_and_cost_surfaces(
    public_exposure_package: Path,
) -> None:
    metrics = METRIC_DEFINITIONS["metrics"]
    document = json.loads(
        (public_exposure_package / "summary.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (public_exposure_package / "manifest.redacted.json").read_text(
            encoding="utf-8"
        )
    )
    summary = document["summary"]
    emitted_names = {
        name
        for name in manifest
        if name.endswith("_count") or name == "decision"
    }
    emitted_names.update(
        name for name in manifest["source"] if name.endswith("_count")
    )
    emitted_names.update(document["verification_inputs"])
    emitted_names.update(set(summary) - {"depths"})
    for depth in summary["depths"]:
        emitted_names.update(set(depth) - {"depth"})
    for stratum in document["strata"]:
        emitted_names.update(set(stratum) - {"depths", "dimension", "value"})
        for depth in stratum["depths"]:
            emitted_names.update(set(depth) - {"depth"})

    assert emitted_names == PUBLISHED_AGGREGATE_DEFINITION_NAMES
    assert PUBLISHED_AGGREGATE_DEFINITION_NAMES <= set(metrics)
    assert all(
        set(definition)
        == {"applicability", "denominator", "interpretation", "numerator", "unit"}
        for definition in metrics.values()
    )
    assert metrics["counterfactual_search_reach"]["interpretation"] == (
        "attack units with persisted candidate rank less than or equal to the fixed depth"
    )
    assert metrics["clean_task_success"]["applicability"] == (
        "clean_case_count > 0"
    )
    assert metrics["clean_task_success"]["denominator"] == (
        "clean-task benign cases"
    )
    assert metrics["row_count"]["interpretation"] == (
        "fingerprinted attack content-unit rows published in the package"
    )
    assert metrics["decision"] == {
        "applicability": "always",
        "denominator": "not applicable",
        "interpretation": "decision selected by recomputed evidence precedence",
        "numerator": "recomputed public decision status",
        "unit": "decision",
    }


def test_metric_definitions_classify_and_cover_public_unit_row_surface(
    public_exposure_package: Path,
) -> None:
    rows = _rows(public_exposure_package)
    projected_fields = set().union(*(set(row) for row in rows))
    defined_fields = (
        projected_fields - PUBLIC_ROW_IDENTITY_FIELDS - PUBLIC_ROW_METADATA_FIELDS
    )
    expected_classification = {
        "defined": sorted(defined_fields),
        "identity": sorted(PUBLIC_ROW_IDENTITY_FIELDS),
        "metadata": sorted(PUBLIC_ROW_METADATA_FIELDS),
    }

    assert projected_fields == set(PUBLIC_UNIT_ROW_KEYS)
    assert METRIC_DEFINITIONS.get("public_unit_row_fields") == (
        expected_classification
    )
    assert set(METRIC_DEFINITIONS["metrics"]) == (
        PUBLISHED_AGGREGATE_DEFINITION_NAMES | defined_fields
    )
    for field in defined_fields:
        definition = METRIC_DEFINITIONS["metrics"][field]
        assert set(definition) == {
            "applicability",
            "denominator",
            "interpretation",
            "numerator",
            "unit",
        }
        assert all(isinstance(value, str) and value for value in definition.values())


def test_export_rejects_wrong_private_hash_or_run_without_target(
    private_exposure_run: Path,
    tmp_path: Path,
) -> None:
    for expected_hash, expected_run in (
        ("0" * 64, private_exposure_run.name),
        (_sha256(private_exposure_run / "manifest.json"), "wrong-run"),
    ):
        output = tmp_path / expected_hash[:4] / expected_run
        with pytest.raises(ValueError, match="source"):
            export_exposure_public_evidence(
                private_exposure_run,
                output,
                package_name="fixture",
                expected_source_manifest_sha256=expected_hash,
                expected_source_run_id=expected_run,
                forbidden_texts=("raw",),
            )
        assert not (output / "fixture").exists()


def test_export_scans_decoded_structured_values_before_json_escaping(
) -> None:
    forbidden = 'quoted "value"\\path\nline'
    with pytest.raises(ValueError, match="forbidden content"):
        public_writer._assert_structured_content_free(
            {"value": forbidden},
            (forbidden,),
        )


@pytest.mark.parametrize(
    "absolute_path",
    (
        r"C:\Users\secret\file.txt",
        "D:/service/config.json",
        r"\\server\share\file.txt",
        r"\\?\UNC\server\share\file.txt",
        r"local path: \\?\UNC\server\share\file.txt",
        "/tmp/secret/file.txt",
        "//etc/hosts",
        "local path: //etc/hosts",
        "/",
        "/etc/hosts",
        "/opt/service/config",
        "/root/.ssh/config",
        "/usr/local/bin/tool",
        "local path:/etc/hosts",
        "local path://etc/hosts",
        "local path:///etc/hosts",
        "https://:/etc/hosts",
        "https://@/etc/hosts",
        "https://[::1/etc/hosts",
        "https://example.com:notaport/etc/hosts",
        "https://./etc/hosts",
        "https://.example.com/etc/hosts",
        "https://-/etc/hosts",
        "https://%/etc/hosts",
        "https://example..com/etc/hosts",
        "https://example.com../etc/hosts",
        "file:///etc/hosts",
        "file:/etc/hosts",
        "file://server/share/file.txt",
        "file:///C:/Users/secret/file.txt",
        r"file:C:\Users\secret\file.txt",
    ),
)
def test_export_rejects_absolute_local_paths(
    absolute_path: str,
) -> None:
    with pytest.raises(ValueError, match="absolute local path"):
        public_writer._assert_no_absolute_paths(
            json.dumps(
                {"value": absolute_path},
                ensure_ascii=False,
            ).encode("utf-8"),
            "summary.json",
        )


@pytest.mark.parametrize(
    "value",
    (
        "local path://etc/hosts",
        "local path:///etc/hosts",
        "https://:/etc/hosts",
        "https://@/etc/hosts",
        "https://[::1/etc/hosts",
        "https://example.com:notaport/etc/hosts",
        "https://./etc/hosts",
        "https://.example.com/etc/hosts",
        "https://-/etc/hosts",
        "https://%/etc/hosts",
        "https://example..com/etc/hosts",
        "https://example.com../etc/hosts",
    ),
)
def test_final_byte_scanner_rejects_colon_adjacent_posix_absolute_path(
    value: str,
) -> None:
    with pytest.raises(ValueError, match="absolute local path"):
        public_writer._assert_no_absolute_paths(
            json.dumps({"limitation": value}).encode("utf-8"),
            "summary.json",
        )


@pytest.mark.parametrize("scan_boundary", ("structured", "final-bytes"))
@pytest.mark.parametrize(
    "network_url",
    (
        r"https://example.com/?local=C:\Users\alice\secret",
        "ssh://example.com/repo?local=C%3A%5CUsers%5Calice%5Csecret",
        "ssh://example.com/repo#local=/etc/passwd",
        "https://example.com/#local=%2Fetc%2Fpasswd",
        r"https://example.com/?local=\\server\share\secret",
        "ssh://example.com/repo?local=%5C%5Cserver%5Cshare%5Csecret",
        "ssh://example.com/repo?local=file:///etc/passwd",
        "https://example.com/?local=file%3A%2F%2F%2Fetc%2Fpasswd",
        "ssh://user:C%3A%5CUsers%5Calice@example.com/repo",
        "https://user:%2Fetc%2Fpasswd@example.com/evidence",
    ),
)
def test_export_rejects_local_paths_in_decoded_network_uri_components(
    scan_boundary: str,
    network_url: str,
) -> None:
    with pytest.raises(ValueError, match="absolute local path"):
        if scan_boundary == "structured":
            public_writer._assert_structured_paths_are_relative(
                {"value": network_url},
                "public structured data",
            )
        else:
            public_writer._assert_no_absolute_paths(
                json.dumps(
                    {"value": network_url},
                    ensure_ascii=False,
                ).encode("utf-8"),
                "summary.json",
            )


@pytest.mark.parametrize(
    "network_url",
    (
        "https://example.com/evidence",
        "https://example.com:8443/evidence",
        "https://user:password@example.com/evidence",
        "https://192.0.2.1/evidence",
        "https://[2001:db8::1]:8443/evidence",
        "https://intranet/evidence",
        "https://bücher.example/evidence",
        "https://example.com./evidence",
        "https://intranet./evidence",
        "https://192.0.2.1./evidence",
        "https://bücher.example./evidence",
        "https://xn--bcher-kva.example./evidence",
        "ssh://git@example.com/org/repo.git",
        "ssh://user:token@example.com:22/repo",
        "https://example.com/search?q=public-evidence#section",
    ),
)
def test_export_allows_recognized_https_url(
    network_url: str,
) -> None:
    public_writer._assert_structured_paths_are_relative(
        {"value": network_url},
        "public structured data",
    )
    public_writer._assert_no_absolute_paths(
        json.dumps(
            {"value": network_url},
            ensure_ascii=False,
        ).encode("utf-8"),
        "summary.json",
    )


@pytest.mark.parametrize(
    ("hostname", "expected"),
    (
        (MAX_WIRE_DNS_HOSTNAME, True),
        (f"{MAX_WIRE_DNS_HOSTNAME}.", True),
        (OVERLONG_WIRE_DNS_HOSTNAME, False),
        (f"{OVERLONG_WIRE_DNS_HOSTNAME}.", False),
    ),
)
def test_dns_hostname_text_and_wire_length_boundaries(
    hostname: str,
    expected: bool,
) -> None:
    assert public_writer._is_valid_ipv4_or_dns_hostname(hostname) is expected


def test_export_rejects_dangling_final_component_symlink(
    private_exposure_run: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "public"
    output.mkdir()
    target = output / "fixture"
    try:
        target.symlink_to("redirected", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")
    assert target.is_symlink() and not target.exists()

    with pytest.raises(FileExistsError, match="already exists"):
        export_exposure_public_evidence(
            private_exposure_run,
            output,
            package_name="fixture",
            expected_source_manifest_sha256=_sha256(
                private_exposure_run / "manifest.json"
            ),
            expected_source_run_id=private_exposure_run.name,
            forbidden_texts=("raw question", "raw attack"),
        )
    assert target.is_symlink()
    assert not (output / "redirected").exists()


def test_export_rejects_lexical_source_symlink_before_resolve(
    private_exposure_run: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_alias = tmp_path / "source-alias"
    output = tmp_path / "public"
    source_alias.mkdir()
    real_lstat = Path.lstat
    resolve = Path.resolve

    def mark_source_as_redirect(path: Path):
        observed = real_lstat(path)
        if path == source_alias:
            return with_reparse_point_attribute(observed)
        return observed

    def reject_source_resolve(path: Path, *args, **kwargs) -> Path:
        if path == source_alias:
            raise AssertionError("source path resolved before symlink rejection")
        return resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", mark_source_as_redirect)
    monkeypatch.setattr(Path, "resolve", reject_source_resolve)

    with pytest.raises(
        ValueError,
        match="source run cannot be a symlink or redirecting reparse point",
    ):
        export_exposure_public_evidence(
            source_alias,
            output,
            package_name="fixture",
            expected_source_manifest_sha256=_sha256(
                private_exposure_run / "manifest.json"
            ),
            expected_source_run_id=private_exposure_run.name,
            forbidden_texts=("raw question", "raw attack"),
        )

    assert not output.exists()


def test_export_rejects_source_run_symlink_when_supported(
    private_exposure_run: Path,
    tmp_path: Path,
) -> None:
    source_alias = tmp_path / "source-alias"
    output = tmp_path / "public"
    try:
        source_alias.symlink_to(
            private_exposure_run,
            target_is_directory=True,
        )
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(ValueError, match="source run cannot be a symlink"):
        export_exposure_public_evidence(
            source_alias,
            output,
            package_name="fixture",
            expected_source_manifest_sha256=_sha256(
                private_exposure_run / "manifest.json"
            ),
            expected_source_run_id=private_exposure_run.name,
            forbidden_texts=("raw question", "raw attack"),
        )

    assert source_alias.is_symlink()
    assert private_exposure_run.is_dir()
    assert not (output / "fixture").exists()
    if output.exists():
        assert not tuple(output.glob(".*.staging-*"))


def test_export_rejects_real_windows_private_source_junction(
    private_exposure_run: Path,
    tmp_path: Path,
) -> None:
    source_alias = tmp_path / "private-source-junction"
    output = tmp_path / "public"

    with directory_redirect(
        source_alias,
        private_exposure_run,
        windows_junction_only=True,
    ) as primitive:
        assert primitive == "junction"
        with pytest.raises(
            ValueError,
            match="source run cannot be a symlink or redirecting reparse point",
        ):
            export_exposure_public_evidence(
                source_alias,
                output,
                package_name="fixture",
                expected_source_manifest_sha256=_sha256(
                    private_exposure_run / "manifest.json"
                ),
                expected_source_run_id=private_exposure_run.name,
                forbidden_texts=("raw question", "raw attack"),
            )

    assert private_exposure_run.is_dir()
    assert (private_exposure_run / "manifest.json").is_file()
    assert not (output / "fixture").exists()


def test_export_rejects_mocked_private_source_reparse_root_before_resolve(
    private_exposure_run: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = private_exposure_run.absolute()
    real_lstat = Path.lstat

    def mark_source_root(path: Path):
        observed = real_lstat(path)
        if path == source:
            return with_reparse_point_attribute(observed)
        return observed

    monkeypatch.setattr(Path, "lstat", mark_source_root)

    with pytest.raises(
        ValueError,
        match="source run cannot be a symlink or redirecting reparse point",
    ):
        export_exposure_public_evidence(
            source,
            tmp_path / "public",
            package_name="fixture",
            expected_source_manifest_sha256=_sha256(source / "manifest.json"),
            expected_source_run_id=source.name,
            forbidden_texts=("raw question", "raw attack"),
        )


def test_export_empty_target_race_is_no_replace_and_cleans_stage(
    private_exposure_run: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "public"
    target = output / "fixture"
    real_handoff = public_writer._atomic_publish_no_replace

    def race(stage: Path, destination: Path) -> None:
        destination.mkdir()
        real_handoff(stage, destination)

    monkeypatch.setattr(public_writer, "_atomic_publish_no_replace", race)
    with pytest.raises(FileExistsError):
        export_exposure_public_evidence(
            private_exposure_run,
            output,
            package_name="fixture",
            expected_source_manifest_sha256=_sha256(
                private_exposure_run / "manifest.json"
            ),
            expected_source_run_id=private_exposure_run.name,
            forbidden_texts=("raw question", "raw attack"),
        )
    assert target.is_dir() and not tuple(target.iterdir())
    assert not tuple(output.glob(".*.staging-*"))


def test_public_cli_exports_and_verifies(
    source_material: tuple[Path, Path],
    private_exposure_run: Path,
    tmp_path: Path,
    capsys,
) -> None:
    _, security_data_root = source_material
    output = tmp_path / "public"
    argv = [
        "--source-run",
        str(private_exposure_run),
        "--output-root",
        str(output),
        "--package-name",
        "fixture",
        "--expected-source-run-id",
        private_exposure_run.name,
        "--expected-source-manifest-sha256",
        _sha256(private_exposure_run / "manifest.json"),
        "--security-data-root",
        str(security_data_root),
    ]
    assert export_main(argv) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["status"] == "EXPORTED"
    package = output / "fixture"

    assert verify_main([str(package)]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["status"] == "VERIFIED"


def test_public_export_cli_uses_shared_complete_sensitive_value_corpus(
    source_material: tuple[Path, Path],
    private_exposure_run: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    _, security_data_root = source_material
    dev = load_security_bundle(security_data_root, "dev")
    test = load_security_bundle(security_data_root, "test")
    dev_case_id = dev.dataset.cases[0].case_id
    test_case_id = test.dataset.cases[0].case_id
    dev_question = dev.dataset.cases[0].question
    test_question = test.dataset.cases[0].question
    benign_unit_id = next(
        unit_id
        for bundle in (dev, test)
        for case in bundle.dataset.cases
        for unit_id in case.benign_unit_ids
    )
    fixture_index = next(
        index
        for index, fixture in enumerate(dev.fixture_manifest.cases)
        if fixture.open_results
    )
    fixture = dev.fixture_manifest.cases[fixture_index]
    open_section = "OPEN_RESULT_SECTION_ONLY"
    opened = fixture.open_results[0].model_copy(
        update={"section_path": (open_section,)}
    )
    updated_fixture = fixture.model_copy(
        update={"open_results": (opened, *fixture.open_results[1:])}
    )
    fixture_cases = list(dev.fixture_manifest.cases)
    fixture_cases[fixture_index] = updated_fixture
    dev = replace(
        dev,
        fixture_manifest=dev.fixture_manifest.model_copy(
            update={"cases": tuple(fixture_cases)}
        ),
    )
    captured: dict[str, tuple[str, ...]] = {}
    output = tmp_path / "public"

    def capture_export(
        _source_run: Path,
        output_root: Path,
        *,
        package_name: str,
        forbidden_texts: tuple[str, ...],
        **_kwargs,
    ) -> Path:
        captured["forbidden_texts"] = forbidden_texts
        return output_root / package_name

    monkeypatch.setattr(
        export_cli,
        "export_exposure_public_evidence",
        capture_export,
    )
    real_load_bundle = export_cli.load_security_bundle

    def load_bundle(_root: Path, split: str):
        if split == "dev":
            return dev
        if split == "test":
            return test
        return real_load_bundle(_root, split)

    monkeypatch.setattr(export_cli, "load_security_bundle", load_bundle)
    argv = [
        "--source-run",
        str(private_exposure_run),
        "--output-root",
        str(output),
        "--package-name",
        "fixture",
        "--expected-source-run-id",
        private_exposure_run.name,
        "--expected-source-manifest-sha256",
        _sha256(private_exposure_run / "manifest.json"),
        "--security-data-root",
        str(security_data_root),
    ]

    assert export_cli.main(argv) == 0
    capsys.readouterr()
    assert {
        dev_case_id,
        test_case_id,
        dev_question,
        test_question,
        benign_unit_id,
        open_section,
    } <= set(captured["forbidden_texts"])
