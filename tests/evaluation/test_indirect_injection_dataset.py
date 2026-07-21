from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.evaluation.indirect_injection_contracts import (
    ATTACK_CATEGORIES,
    BENIGN_CATEGORIES,
)
from app.evaluation.indirect_injection_dataset import (
    build_v1_bundle,
    load_security_bundle,
    load_security_dataset_pair,
    sha256_file,
)


FROZEN_AT = "2026-07-18T00:00:00Z"
FREEZE_HEAD = "a" * 40
REPOSITORY_FREEZE_HEAD = "0946ad90a7d9b54e219006b271c7c7bdc440863c"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_builder_creates_reproducible_valid_72_case_bundle(tmp_path: Path) -> None:
    first = tmp_path / "first" / "security"
    second = tmp_path / "second" / "security"

    first_paths = build_v1_bundle(
        first,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    second_paths = build_v1_bundle(
        second,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )

    assert set(first_paths) == {
        "dev_dataset",
        "test_dataset",
        "test_freeze_manifest",
        "dev_fixtures",
        "test_fixtures",
    }
    assert {
        key: first_paths[key].relative_to(first).as_posix() for key in first_paths
    } == {
        "dev_dataset": "indirect_injection_dev_v1.json",
        "test_dataset": "indirect_injection_test_v1.json",
        "test_freeze_manifest": "indirect_injection_test_v1.manifest.json",
        "dev_fixtures": "fixtures_v1/dev/manifest.json",
        "test_fixtures": "fixtures_v1/test/manifest.json",
    }
    for key in first_paths:
        assert first_paths[key].read_bytes() == second_paths[key].read_bytes()

    dev, test = load_security_dataset_pair(first)
    assert len(dev.dataset.cases) + len(test.dataset.cases) == 72
    assert len(dev.fixture_manifest.cases) + len(test.fixture_manifest.cases) == 72
    assert {item.category for item in dev.dataset.cases if item.label == "attack"} == set(
        ATTACK_CATEGORIES
    )
    assert {item.category for item in test.dataset.cases if item.label == "benign"} == set(
        BENIGN_CATEGORIES
    )


def test_builder_refuses_to_overwrite_an_existing_bundle(tmp_path: Path) -> None:
    output = tmp_path / "security"
    build_v1_bundle(
        output,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )

    with pytest.raises(FileExistsError, match="already exists"):
        build_v1_bundle(
            output,
            frozen_at_utc=FROZEN_AT,
            freeze_git_head=FREEZE_HEAD,
        )


def test_test_loader_checks_dataset_hash_before_parsing_json(tmp_path: Path) -> None:
    output = tmp_path / "security"
    paths = build_v1_bundle(
        output,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    paths["test_dataset"].write_text("not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="dataset SHA-256 mismatch"):
        load_security_bundle(output, "test")


def test_test_loader_rejects_fixture_hash_or_declared_byte_mismatch(
    tmp_path: Path,
) -> None:
    output = tmp_path / "security"
    paths = build_v1_bundle(
        output,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    paths["test_fixtures"].write_bytes(
        paths["test_fixtures"].read_bytes() + b"\n"
    )
    with pytest.raises(ValueError, match="fixture manifest SHA-256 mismatch"):
        load_security_bundle(output, "test")

    second = tmp_path / "second" / "security"
    second_paths = build_v1_bundle(
        second,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    manifest = json.loads(
        second_paths["test_freeze_manifest"].read_text(encoding="utf-8")
    )
    manifest["dataset_bytes"] += 1
    second_paths["test_freeze_manifest"].write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="dataset byte count mismatch"):
        load_security_bundle(second, "test")


def test_loader_rejects_freeze_manifest_path_substitution(tmp_path: Path) -> None:
    output = tmp_path / "security"
    paths = build_v1_bundle(
        output,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    manifest = json.loads(
        paths["test_freeze_manifest"].read_text(encoding="utf-8")
    )
    manifest["dataset_path"] = "data/v2/security/../eval/test.json"
    paths["test_freeze_manifest"].write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="safe relative path"):
        load_security_bundle(output, "test")


@pytest.mark.parametrize(
    "artifact_name",
    ("test_dataset", "test_fixtures", "test_freeze_manifest"),
)
def test_loader_rejects_source_mutation_during_snapshot_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_name: str,
) -> None:
    output = tmp_path / "security"
    paths = build_v1_bundle(
        output,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    target = paths[artifact_name]
    original = target.read_bytes()
    mutated = original.replace(b'  "', b' \t"', 1)
    assert mutated != original
    assert len(mutated) == len(original)
    real_read_bytes = Path.read_bytes
    real_write_bytes = Path.write_bytes
    changed = False

    def read_then_mutate(path: Path) -> bytes:
        nonlocal changed
        payload = real_read_bytes(path)
        if path == target and not changed:
            changed = True
            real_write_bytes(path, mutated)
        return payload

    monkeypatch.setattr(Path, "read_bytes", read_then_mutate)

    with pytest.raises(ValueError, match="changed during snapshot read"):
        load_security_bundle(output, "test")


@pytest.mark.parametrize(
    "artifact_name",
    ("test_dataset", "test_fixtures", "test_freeze_manifest"),
)
def test_loader_rejects_symlinked_bundle_sources(
    tmp_path: Path,
    artifact_name: str,
) -> None:
    output = tmp_path / "security"
    paths = build_v1_bundle(
        output,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    source = paths[artifact_name]
    target = tmp_path / f"{artifact_name}.target"
    source.replace(target)
    try:
        source.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"file symlinks are unavailable: {exc}")

    with pytest.raises(ValueError, match="regular non-symlink file"):
        load_security_bundle(output, "test")


@pytest.mark.parametrize(
    "artifact_name",
    ("test_dataset", "test_fixtures", "test_freeze_manifest"),
)
def test_loader_checks_each_bundle_source_path_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_name: str,
) -> None:
    output = tmp_path / "security"
    paths = build_v1_bundle(
        output,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    target = paths[artifact_name]
    real_is_symlink = Path.is_symlink

    def report_substituted_path(path: Path) -> bool:
        return path == target or real_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", report_substituted_path)

    with pytest.raises(ValueError, match="regular non-symlink file"):
        load_security_bundle(output, "test")


def test_dev_and_test_have_distinct_payloads_canaries_and_source_placement(
    tmp_path: Path,
) -> None:
    output = tmp_path / "security"
    build_v1_bundle(
        output,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    dev, test = load_security_dataset_pair(output)

    dev_text = "\n".join(
        candidate.matched_text + "\n" + candidate.context_text
        for fixture in dev.fixture_manifest.cases
        for candidate in fixture.candidates
    )
    test_text = "\n".join(
        candidate.matched_text + "\n" + candidate.context_text
        for fixture in test.fixture_manifest.cases
        for candidate in fixture.candidates
    )
    assert dev_text != test_text
    assert {
        item.document_canary
        for item in dev.dataset.cases
        if item.document_canary is not None
    }.isdisjoint(
        {
            item.document_canary
            for item in test.dataset.cases
            if item.document_canary is not None
        }
    )
    dev_surfaces = [item.source_surfaces for item in dev.dataset.cases]
    test_surfaces = [item.source_surfaces for item in test.dataset.cases]
    assert dev_surfaces != test_surfaces


def test_freeze_manifest_matches_exact_test_and_fixture_bytes(tmp_path: Path) -> None:
    output = tmp_path / "security"
    paths = build_v1_bundle(
        output,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    manifest = json.loads(
        paths["test_freeze_manifest"].read_text(encoding="utf-8")
    )

    assert manifest["dataset_sha256"] == sha256_file(paths["test_dataset"])
    assert manifest["dataset_bytes"] == paths["test_dataset"].stat().st_size
    assert manifest["fixture_manifest_sha256"] == sha256_file(
        paths["test_fixtures"]
    )
    assert manifest["freeze_git_head"] == FREEZE_HEAD
    assert manifest["dataset_sha256"] == hashlib.sha256(
        paths["test_dataset"].read_bytes()
    ).hexdigest()


def test_mixed_top_up_fallback_is_not_an_adjacent_chunk_of_the_poison_document(
    tmp_path: Path,
) -> None:
    output = tmp_path / "security"
    build_v1_bundle(
        output,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    dev = load_security_bundle(output, "dev")
    fixture_by_id = {item.case_id: item for item in dev.fixture_manifest.cases}

    for case in dev.dataset.cases:
        if case.label != "attack" or not case.benign_unit_ids:
            continue
        if set(case.source_surfaces) & {"parent", "open_context"}:
            continue
        fixture = fixture_by_id[case.case_id]
        attack_docs = {
            candidate.document_id
            for candidate in fixture.candidates
            if set(candidate.unit_bindings()) & set(case.attack_unit_ids)
        }
        clean_docs = {
            candidate.document_id
            for candidate in fixture.candidates
            if set(candidate.unit_bindings()) & set(case.benign_unit_ids)
        }
        assert attack_docs.isdisjoint(clean_docs)


def test_same_chunk_scenarios_contain_the_declared_clean_fact_text(
    tmp_path: Path,
) -> None:
    output = tmp_path / "security"
    build_v1_bundle(
        output,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    for bundle in load_security_dataset_pair(output):
        fixtures = {item.case_id: item for item in bundle.fixture_manifest.cases}
        for case in bundle.dataset.cases:
            if "same_chunk_fact_attack" not in case.scenario_tags:
                continue
            fixture = fixtures[case.case_id]
            attack_candidate = next(
                candidate
                for candidate in fixture.candidates
                if candidate.matched_unit_id in case.attack_unit_ids
            )
            for fact_id in case.required_clean_fact_ids:
                assert fixture.fact_texts[fact_id] in attack_candidate.matched_text


def test_checked_in_v1_bundle_reproduces_byte_for_byte(tmp_path: Path) -> None:
    regenerated = build_v1_bundle(
        tmp_path / "security",
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=REPOSITORY_FREEZE_HEAD,
    )
    checked_in_root = REPOSITORY_ROOT / "data" / "v2" / "security"
    checked_in = {
        "dev_dataset": checked_in_root / "indirect_injection_dev_v1.json",
        "test_dataset": checked_in_root / "indirect_injection_test_v1.json",
        "test_freeze_manifest": (
            checked_in_root / "indirect_injection_test_v1.manifest.json"
        ),
        "dev_fixtures": checked_in_root / "fixtures_v1" / "dev" / "manifest.json",
        "test_fixtures": checked_in_root / "fixtures_v1" / "test" / "manifest.json",
    }

    for name, checked_in_path in checked_in.items():
        assert regenerated[name].read_bytes() == checked_in_path.read_bytes()
