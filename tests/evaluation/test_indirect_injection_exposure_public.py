from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.evaluation import indirect_injection_exposure_public as public_writer
from app.evaluation.indirect_injection_exposure import ExposureAnalysisResult
from app.evaluation.indirect_injection_exposure_public import (
    export_exposure_public_evidence,
)
from app.evaluation.indirect_injection_exposure_public_verifier import (
    PUBLIC_EXPOSURE_FILES,
    PUBLIC_UNIT_ROW_KEYS,
    ExposurePublicVerificationError,
    verify_exposure_public_package,
)
from scripts.export_indirect_injection_exposure_public import main as export_main
from scripts.verify_indirect_injection_exposure_public import main as verify_main
from tests.evaluation.test_indirect_injection_exposure import source_material
from tests.evaluation.test_indirect_injection_exposure_writer import (
    _publish,
    exposure_result,
    verification_inputs,
)


CHECKSUM_NAMES = tuple(sorted(PUBLIC_EXPOSURE_FILES - {"checksums.sha256"}))


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


@pytest.fixture
def private_exposure_run(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
) -> Path:
    return _publish(tmp_path / "private", exposure_result)


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


def test_public_export_is_exact_content_free_and_deterministic(
    tmp_path: Path,
    private_exposure_run: Path,
    exposure_result: ExposureAnalysisResult,
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
        for item in exposure_result.units
        for value in (item.case_id, item.unit_id)
    }
    assert all(value.encode("utf-8") not in public_bytes for value in private_ids)
    assert b"raw question" not in public_bytes
    assert b"raw attack" not in public_bytes
    assert verify_exposure_public_package(first).verified is True


def test_public_rows_use_exact_keys_fingerprints_and_order(
    public_exposure_package: Path,
    private_exposure_run: Path,
    exposure_result: ExposureAnalysisResult,
) -> None:
    rows = _rows(public_exposure_package)
    assert len(rows) == 28
    assert all(set(row) == set(PUBLIC_UNIT_ROW_KEYS) for row in rows)
    assert all("case_id" not in row and "unit_id" not in row for row in rows)
    identities = tuple(
        (row["case_fingerprint"], row["unit_fingerprint"]) for row in rows
    )
    assert identities == tuple(sorted(identities))
    first_private = exposure_result.units[0]
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
    assert "VERIFIED" in completed.stdout
    readme = (isolated / "README.md").read_text(encoding="utf-8")
    assert "does not prove that derivation" in readme


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
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
) -> None:
    forbidden = 'quoted "value"\\path\nline'
    payload = exposure_result.model_dump(mode="python")
    payload["limitations"] = (*exposure_result.limitations, forbidden)
    changed = ExposureAnalysisResult.model_validate(payload)
    private_run = _publish(tmp_path / "private", changed)

    with pytest.raises(ValueError, match="forbidden content"):
        export_exposure_public_evidence(
            private_run,
            tmp_path / "public",
            package_name="fixture",
            expected_source_manifest_sha256=_sha256(
                private_run / "manifest.json"
            ),
            expected_source_run_id=private_run.name,
            forbidden_texts=(forbidden,),
        )
    assert not (tmp_path / "public" / "fixture").exists()


@pytest.mark.parametrize("absolute_path", (r"C:\\Users\\secret\\file.txt", "/tmp/secret/file.txt"))
def test_export_rejects_absolute_local_paths(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
    absolute_path: str,
) -> None:
    payload = exposure_result.model_dump(mode="python")
    payload["limitations"] = (*exposure_result.limitations, absolute_path)
    changed = ExposureAnalysisResult.model_validate(payload)
    private_run = _publish(tmp_path / "private", changed)

    with pytest.raises(ValueError, match="absolute local path"):
        export_exposure_public_evidence(
            private_run,
            tmp_path / "public",
            package_name="fixture",
            expected_source_manifest_sha256=_sha256(
                private_run / "manifest.json"
            ),
            expected_source_run_id=private_run.name,
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
