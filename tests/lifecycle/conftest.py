from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from app.lifecycle.evidence import create_prefix_anchor, hash_evidence_artifacts


APPEND_ONLY_PATHS = [
    "docs/lifecycle/01_ENGINEERING_JOURNAL.md",
    "docs/lifecycle/02_DECISIONS.md",
    "docs/lifecycle/03_RESULTS.md",
    "docs/lifecycle/EXPERIMENTS.jsonl",
    "docs/lifecycle/FAILURES.jsonl",
    "docs/lifecycle/RESEARCH_REQUESTS.jsonl",
]

HASHED_EVIDENCE_PATHS = [
    "docs/lifecycle/00_STAGE_CONTRACT.md",
    "docs/lifecycle/01_ENGINEERING_JOURNAL.md",
    "docs/lifecycle/02_DECISIONS.md",
    "docs/lifecycle/03_RESULTS.md",
    "docs/lifecycle/04_LEARNING_GUIDE.md",
    "docs/lifecycle/TRACEABILITY.csv",
    "docs/lifecycle/EXPERIMENTS.jsonl",
    "docs/lifecycle/FAILURES.jsonl",
    "docs/lifecycle/RESEARCH_REQUESTS.jsonl",
]


@pytest.fixture
def lifecycle_repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    lifecycle = root / "docs" / "lifecycle"
    lifecycle.mkdir(parents=True)
    implementation = root / "app" / "lifecycle" / "validation.py"
    implementation.parent.mkdir(parents=True)
    implementation.write_text("# fixture implementation\n", encoding="utf-8")

    (lifecycle / "00_STAGE_CONTRACT.md").write_text(
        "# Contract\n\n"
        "## REQ-LC-010 - Reproducible evidence\n\n"
        "Tests: `T-LC-019`, `T-LC-021`.\n",
        encoding="utf-8",
    )
    (lifecycle / "01_ENGINEERING_JOURNAL.md").write_text(
        "# Journal\n\n## G1 / EVID-LC-001\n\nObserved fixture.\n",
        encoding="utf-8",
    )
    (lifecycle / "02_DECISIONS.md").write_text(
        "# Decisions\n\n## ADR-LC-003 - Evidence boundary\n\nStatus: Accepted.\n",
        encoding="utf-8",
    )
    (lifecycle / "03_RESULTS.md").write_text(
        "# Results\n\n## G1\n\nDeterministic fixture only.\n",
        encoding="utf-8",
    )
    (lifecycle / "04_LEARNING_GUIDE.md").write_text(
        "# Learning Guide\n\nThe fixture contains no source content.\n",
        encoding="utf-8",
    )
    (lifecycle / "EXPERIMENTS.jsonl").write_bytes(b"")
    (lifecycle / "FAILURES.jsonl").write_text(
        json.dumps(
            {
                "failure_id": "FAIL-LC-001",
                "first_seen_at": "2026-07-26T08:00:00Z",
                "gate": "G1",
                "related_requirements": ["REQ-LC-010"],
                "input_fixture_ids": [],
                "expected_behavior": "The fixture validates.",
                "actual_behavior": "The first fixture did not validate.",
                "error_taxonomy": "fixture_setup",
                "security_impact": "None.",
                "reproduction_commands": [
                    "python -m pytest tests/lifecycle -q"
                ],
                "root_cause": "The fixture was incomplete.",
                "attempted_fixes": ["Completed the fixture."],
                "fix_commit": "",
                "regression_test_ids": ["T-LC-019"],
                "status": "RESOLVED",
                "resolved_at": "2026-07-26T08:05:00Z",
                "superseded_by": "",
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (lifecycle / "RESEARCH_REQUESTS.jsonl").write_bytes(b"")

    with (lifecycle / "TRACEABILITY.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "requirement_id",
                "description",
                "design_id",
                "implementation_paths",
                "test_ids",
                "experiment_ids",
                "evidence_ids",
                "status",
                "notes",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "requirement_id": "REQ-LC-010",
                "description": "Produce reproducible evidence",
                "design_id": "ADR-LC-003",
                "implementation_paths": "app/lifecycle/validation.py",
                "test_ids": "T-LC-019;T-LC-021",
                "experiment_ids": "",
                "evidence_ids": "EVID-LC-001",
                "status": "G1_IN_PROGRESS",
                "notes": "Synthetic validation fixture.",
            }
        )

    anchors = [
        create_prefix_anchor(root, path, accepted_at_gate="G0")
        for path in APPEND_ONLY_PATHS
    ]
    hashes = hash_evidence_artifacts(root, HASHED_EVIDENCE_PATHS)
    handoff = {
        "schema_version": 1,
        "baseline_sha": "a" * 40,
        "current_sha": "a" * 40,
        "dirty": True,
        "current_gate": "G1_IN_PROGRESS",
        "completed_gates": ["G0"],
        "completed_requirements": [],
        "accepted_decisions": ["ADR-LC-003"],
        "open_failures": [],
        "blocking_research_requests": [],
        "last_test_runs": [
            {
                "command_id": "CMD-LC-G1-001",
                "kind": "pytest",
                "artifact_path": "artifacts/lifecycle/g1-fixture",
                "scope": "Synthetic lifecycle validation fixture",
                "exit_code": 0,
                "duration_seconds": 0.1,
                "passed": 1,
                "failed": 0,
                "skipped": 0,
                "warnings": 0,
            }
        ],
        "append_only_anchors": [
            item.model_dump(mode="json") for item in anchors
        ],
        "evidence_artifacts": [
            item.model_dump(mode="json") for item in hashes
        ],
        "next_actions": ["Complete G1."],
        "files_to_read_next": [
            "docs/lifecycle/00_STAGE_CONTRACT.md",
            "docs/lifecycle/CODEX_HANDOFF.json",
        ],
    }
    (lifecycle / "CODEX_HANDOFF.json").write_text(
        json.dumps(handoff, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return root
