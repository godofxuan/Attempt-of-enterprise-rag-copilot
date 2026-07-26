from __future__ import annotations

from pathlib import Path

import pytest

from scripts import benchmark_full_rebuild


def test_protocol_minimum_repetitions_are_not_silently_weakened() -> None:
    assert benchmark_full_rebuild.minimum_repetitions("deterministic") == 10
    assert benchmark_full_rebuild.minimum_repetitions("ollama") == 5

    with pytest.raises(ValueError, match="at least 10"):
        benchmark_full_rebuild.validate_repetitions("deterministic", 9)
    with pytest.raises(ValueError, match="at least 5"):
        benchmark_full_rebuild.validate_repetitions("ollama", 4)


@pytest.mark.parametrize(
    "run_id",
    ["../escape", "nested/run", "nested\\run", "CON", "trailing.", ""],
)
def test_benchmark_rejects_unsafe_run_ids(run_id: str) -> None:
    with pytest.raises(ValueError, match="run ID"):
        benchmark_full_rebuild.validate_run_id(run_id)


def test_benchmark_roots_are_confined_and_refuse_existing_output(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "artifacts" / "lifecycle"
    work_root = tmp_path / ".private" / "lifecycle"

    artifact_dir, work_dir = benchmark_full_rebuild.resolve_run_directories(
        repository_root=tmp_path,
        artifact_root=artifact_root,
        work_root=work_root,
        run_id="g0-test-001",
    )

    assert artifact_dir == (artifact_root / "g0-test-001").resolve()
    assert work_dir == (work_root / "g0-test-001").resolve()

    artifact_dir.mkdir(parents=True)
    with pytest.raises(FileExistsError, match="already exists"):
        benchmark_full_rebuild.resolve_run_directories(
            repository_root=tmp_path,
            artifact_root=artifact_root,
            work_root=work_root,
            run_id="g0-test-001",
        )
