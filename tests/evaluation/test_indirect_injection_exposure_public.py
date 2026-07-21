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
from app.evaluation.indirect_injection_exposure import (
    ExposureAnalysisResult,
    ExposureUnitObservation,
    _build_exposure_strata,
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
from scripts.export_indirect_injection_exposure_public import main as export_main
from scripts.verify_indirect_injection_exposure_public import main as verify_main
from tests.evaluation.test_indirect_injection_exposure import source_material
from tests.evaluation.test_indirect_injection_exposure_writer import (
    _publish,
    exposure_result,
    verification_inputs,
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
    assert "VERIFIED" in completed.stdout
    readme = (isolated / "README.md").read_text(encoding="utf-8")
    assert "does not prove that derivation" in readme
    assert "Authenticate `verify.py` against a trusted copy" in readme


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
    tmp_path: Path,
    formal_exposure_result: ExposureAnalysisResult,
) -> None:
    forbidden = 'quoted "value"\\path\nline'
    payload = formal_exposure_result.model_dump(mode="python")
    payload["limitations"] = (*formal_exposure_result.limitations, forbidden)
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
        "file:///etc/hosts",
        "file:/etc/hosts",
        "file://server/share/file.txt",
        "file:///C:/Users/secret/file.txt",
        r"file:C:\Users\secret\file.txt",
    ),
)
def test_export_rejects_absolute_local_paths(
    tmp_path: Path,
    formal_exposure_result: ExposureAnalysisResult,
    absolute_path: str,
) -> None:
    payload = formal_exposure_result.model_dump(mode="python")
    payload["limitations"] = (*formal_exposure_result.limitations, absolute_path)
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


@pytest.mark.parametrize(
    "value",
    (
        "local path://etc/hosts",
        "local path:///etc/hosts",
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


def test_export_allows_recognized_https_url(
    tmp_path: Path,
    formal_exposure_result: ExposureAnalysisResult,
) -> None:
    network_url = "https://example.com/evidence"
    payload = formal_exposure_result.model_dump(mode="python")
    payload["limitations"] = (*formal_exposure_result.limitations, network_url)
    changed = ExposureAnalysisResult.model_validate(payload)
    private_run = _publish(tmp_path / "private", changed)

    package = export_exposure_public_evidence(
        private_run,
        tmp_path / "public",
        package_name="fixture",
        expected_source_manifest_sha256=_sha256(private_run / "manifest.json"),
        expected_source_run_id=private_run.name,
        forbidden_texts=("raw question", "raw attack"),
    )

    assert network_url.encode("utf-8") in (package / "summary.json").read_bytes()
    assert verify_exposure_public_package(package).verified is True


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
