from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DOCS = [
    "docs/architecture.md",
    "docs/known_limitations.md",
    "docs/demo_runbook.md",
    "docs/industrialization_backlog.md",
    "docs/assets/README.md",
]


def test_audit_rejects_private_paths_credentials_large_files_and_bad_links(
    tmp_path: Path,
) -> None:
    from scripts.audit_public_repo import audit_repository

    files = {
        ".env": "CHAT_MODEL=local\n",
        ".private/notes.md": "private interview notes\n",
        "key.pem": (
            "-----BEGIN " + "PRIVATE KEY-----\nnot-a-real-key\n"
            "-----END " + "PRIVATE KEY-----\n"
        ),
        "openai.txt": "sk-" + "a" * 32,
        "github.txt": "ghp_" + "b" * 36,
        "tests/safe.txt": (
            "password=never-show\nsecurity@example.invalid\n"
        ),
        "README.md": (
            "Contact "
            + "person"
            + "@real-company.com\n"
            + "Local path C:\\Users\\alice\\project\n"
            + "[missing](docs/missing.md)\n"
        ),
    }
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    large = tmp_path / "large.bin"
    large.write_bytes(b"x" * (2 * 1024 * 1024 + 1))

    report = audit_repository(
        tmp_path,
        candidate_files=[*files, "large.bin"],
    )
    findings = {(item.code, item.path) for item in report.findings}

    assert ("forbidden_path", ".env") in findings
    assert ("forbidden_path", ".private/notes.md") in findings
    assert ("private_key", "key.pem") in findings
    assert ("credential_token", "openai.txt") in findings
    assert ("credential_token", "github.txt") in findings
    assert ("non_example_email", "README.md") in findings
    assert ("absolute_user_path", "README.md") in findings
    assert ("missing_local_link", "README.md") in findings
    assert ("file_too_large", "large.bin") in findings
    assert not any(item.path == "tests/safe.txt" for item in report.findings)
    assert report.passed is False


def test_audit_enumerates_tracked_and_untracked_nonignored_files(
    tmp_path: Path,
) -> None:
    from scripts.audit_public_repo import audit_repository

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("ignored/\n.env\n", encoding="utf-8")
    (tmp_path / "tracked.md").write_text("tracked\n", encoding="utf-8")
    (tmp_path / "untracked.md").write_text("untracked\n", encoding="utf-8")
    (tmp_path / ".env").write_text("ignored\n", encoding="utf-8")
    ignored = tmp_path / "ignored" / "artifact.txt"
    ignored.parent.mkdir()
    ignored.write_text("ignored\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "tracked.md"],
        check=True,
    )

    report = audit_repository(tmp_path)

    assert "tracked.md" in report.candidate_files
    assert "untracked.md" in report.candidate_files
    assert ".env" not in report.candidate_files
    assert "ignored/artifact.txt" not in report.candidate_files


def test_audit_rejects_absolute_paths_in_any_markdown(tmp_path: Path) -> None:
    from scripts.audit_public_repo import audit_repository

    nested_doc = tmp_path / "docs" / "roadmap" / "handoff.md"
    nested_doc.parent.mkdir(parents=True)
    nested_doc.write_text(
        "workspace: " + "D:\\private-workspace\\rag\n",
        encoding="utf-8",
    )
    source = tmp_path / "tests" / "path_fixture.py"
    source.parent.mkdir()
    source.write_text(
        'WINDOWS_PATH_FIXTURE = "D:\\\\example"\n',
        encoding="utf-8",
    )

    report = audit_repository(
        tmp_path,
        candidate_files=[
            "docs/roadmap/handoff.md",
            "tests/path_fixture.py",
        ],
    )

    assert ("absolute_user_path", "docs/roadmap/handoff.md") in {
        (item.code, item.path) for item in report.findings
    }
    assert not any(item.path == "tests/path_fixture.py" for item in report.findings)


def test_audit_scans_runtime_text_for_paths_and_literal_credentials(
    tmp_path: Path,
) -> None:
    from scripts.audit_public_repo import audit_repository

    runtime = tmp_path / "app" / "leaky_config.py"
    runtime.parent.mkdir(parents=True)
    runtime.write_text(
        'cache_path = "C:\\Users\\alice\\private\\cache"\n'
        'password = "RealLookingSecretValue42"\n',
        encoding="utf-8",
    )
    safe = tmp_path / "app" / "safe_config.py"
    safe.write_text(
        'api_key = settings.llm_api_key\nlocal_api_key = "ollama"\n',
        encoding="utf-8",
    )

    report = audit_repository(
        tmp_path,
        candidate_files=["app/leaky_config.py", "app/safe_config.py"],
    )
    findings = {(item.code, item.path) for item in report.findings}

    assert ("absolute_user_path", "app/leaky_config.py") in findings
    assert ("credential_assignment", "app/leaky_config.py") in findings
    assert not any(path == "app/safe_config.py" for _, path in findings)


def test_audit_scans_d7_public_evidence_for_private_runtime_and_frozen_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.audit_public_repo import audit_repository

    dataset = tmp_path / "data" / "v2" / "security" / "indirect_injection_test_v1.json"
    dataset.parent.mkdir(parents=True)
    dataset.write_text(
        '{"cases":[{"question":"FROZEN_QUESTION_DO_NOT_PUBLISH",'
        '"trace_canary":"TRACE_CANARY_DO_NOT_PUBLISH",'
        '"document_canary":"DOC_CANARY_DO_NOT_PUBLISH"}]}',
        encoding="utf-8",
    )
    fixture = (
        tmp_path
        / "data"
        / "v2"
        / "security"
        / "fixtures_v1"
        / "test"
        / "manifest.json"
    )
    fixture.parent.mkdir(parents=True)
    fixture.write_text(
        '{"cases":[{"fact_texts":{"fact":"PRIVATE_FIXTURE_PAYLOAD"},'
        '"candidates":[],"open_results":[]}]}',
        encoding="utf-8",
    )
    public = (
        tmp_path
        / "data"
        / "v2"
        / "public"
        / "r2_s1_d7"
        / "per_case.redacted.jsonl"
    )
    public.parent.mkdir(parents=True)
    public.write_text(
        "FROZEN_QUESTION_DO_NOT_PUBLISH\n"
        "C:\\Users\\alice\\private\\run\n"
        "HTTP_PROXY=http://proxy.invalid\n"
        "security_runs/private-live-run\n"
        "password=should-not-be-public\n"
        "你是企业知识库助手。\n"
        "local owner alice\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("USERNAME", "alice")

    report = audit_repository(
        tmp_path,
        candidate_files=["data/v2/public/r2_s1_d7/per_case.redacted.jsonl"],
    )
    findings = {(item.code, item.path) for item in report.findings}
    relative = "data/v2/public/r2_s1_d7/per_case.redacted.jsonl"

    for code in {
        "absolute_user_path",
        "credential_assignment",
        "environment_reference",
        "frozen_security_content",
        "local_identity",
        "private_runtime_reference",
        "system_prompt_fragment",
    }:
        assert (code, relative) in findings


def test_audit_rejects_internal_symlink_and_binary_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.audit_public_repo import audit_repository

    target = tmp_path / "target.txt"
    target.write_text("public target\n", encoding="utf-8")
    link = tmp_path / "linked.txt"
    link.write_text("simulated link placeholder\n", encoding="utf-8")
    original_resolve = Path.resolve
    original_is_symlink = Path.is_symlink

    def simulated_resolve(self: Path, *args, **kwargs) -> Path:
        if self == link:
            return target
        return original_resolve(self, *args, **kwargs)

    def simulated_is_symlink(self: Path) -> bool:
        if self == link:
            return True
        return original_is_symlink(self)

    monkeypatch.setattr(Path, "resolve", simulated_resolve)
    monkeypatch.setattr(Path, "is_symlink", simulated_is_symlink)

    (tmp_path / "binary.bin").write_bytes(
        b"\x00\xffprefix sk-" + b"a" * 32 + b" suffix"
    )
    (tmp_path / "utf16.txt").write_text(
        "prefix ghp_" + "b" * 36,
        encoding="utf-16",
    )

    report = audit_repository(
        tmp_path,
        candidate_files=["linked.txt", "binary.bin", "utf16.txt"],
    )
    findings = {(item.code, item.path) for item in report.findings}

    assert ("symlink_candidate", "linked.txt") in findings
    assert ("credential_token", "binary.bin") in findings
    assert ("credential_token", "utf16.txt") in findings


def test_audit_rejects_runtime_paths_invalid_snapshot_png_and_any_bad_doc_link(
    tmp_path: Path,
) -> None:
    from scripts.audit_public_repo import audit_repository

    files = {
        "data/indexes/legacy.index": b"index",
        "data/eval_outputs/run.json": b"{}",
        "logs/service.log": b"safe-looking log",
        "data/v2/public/demo_snapshot.json": b"{}",
        "docs/assets/ask.png": b"not-a-png",
        "docs/other.md": b"[missing](never-created.md)\n",
        "docs/code.md": (
            b"```python\nreturn renderers[document.format](document)\n```\n"
        ),
    }
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    report = audit_repository(tmp_path, candidate_files=files)
    findings = {(item.code, item.path) for item in report.findings}

    for path in [
        "data/indexes/legacy.index",
        "data/eval_outputs/run.json",
        "logs/service.log",
    ]:
        assert ("forbidden_path", path) in findings
    assert (
        "invalid_public_snapshot",
        "data/v2/public/demo_snapshot.json",
    ) in findings
    assert ("invalid_png", "docs/assets/ask.png") in findings
    assert ("missing_local_link", "docs/other.md") in findings
    assert not any(item.path == "docs/code.md" for item in report.findings)


def test_readme_is_a_current_evidence_first_entrypoint() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    headings = [
        "## Business Problem",
        "## Architecture",
        "## Demo",
        "## Why Agentic RAG",
        "## Features",
        "## Evidence",
        "## Quick Start",
        "## Synthetic Data",
        "## Limitations",
        "## Documentation",
    ]

    positions = [readme.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "```mermaid" in readme
    for screenshot in ["ask.png", "trace.png", "evaluation.png"]:
        assert f"docs/assets/{screenshot}" in readme
    quick_start = readme.split("## Quick Start", 1)[1].split(
        "## Synthetic Data",
        1,
    )[0]
    commands = re.findall(r"```powershell\n([^\n]+)\n```", quick_start)
    assert len(commands) == 3
    assert "synthetic" in readme.casefold()
    assert "526 passed" in readme
    assert "574 passed" in readme
    for result in ["28/28", "23/24", "31/31"]:
        assert result in readme


def test_root_status_is_the_only_current_status_entrypoint() -> None:
    status = (ROOT / "PROJECT_STATUS.md").read_text(encoding="utf-8")
    historical = (ROOT / "docs" / "PROJECT_STATUS.md").read_text(
        encoding="utf-8"
    )

    assert "更新时间：2026-07-19" in status
    assert "状态：E7" in status
    assert "526 passed" in status
    assert "574 passed" in status
    assert "109 passed" not in status
    assert "历史快照" in historical[:300]
    assert "../PROJECT_STATUS.md" in historical[:300]


def test_r2_s1_current_docs_use_canonical_metric_and_stage_names() -> None:
    status = (ROOT / "PROJECT_STATUS.md").read_text(encoding="utf-8")
    status_header = status.split("## 1.", 1)[0]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    protocol = (
        ROOT / "docs" / "security" / "r2_s1" / "04_evaluation_protocol.md"
    ).read_text(encoding="utf-8")
    results = (
        ROOT / "docs" / "security" / "r2_s1" / "05_results.md"
    ).read_text(encoding="utf-8")
    d7_journal = (
        ROOT / "docs" / "security" / "r2_s1" / "09_d7_engineering_journal.md"
    ).read_text(encoding="utf-8")

    assert "V0-V5" in status_header
    assert "V1-V5" in status_header
    assert "V0-V4" not in status_header
    assert "V1-V4" not in status_header
    assert "15_v5_counterbalanced_arm_order_engineering_journal.md" in readme
    for content in (readme, protocol, results, d7_journal):
        lowered = content.casefold()
        assert "raw model follow" not in lowered
        assert "raw model attack follow" not in lowered
        assert "raw model followed an attack" not in lowered
        assert "raw canary" in lowered


def test_industrialization_backlog_tracks_remaining_indirect_injection_work() -> None:
    backlog = (ROOT / "docs" / "industrialization_backlog.md").read_text(
        encoding="utf-8"
    )

    assert "Independent indirect-injection validation" in backlog
    assert "counterbalanced real-model" in backlog
    assert "semantic judge calibration" in backlog
    assert (
        "| P0 | Indirect document-injection defense |" not in backlog
    )


def test_public_docs_history_banner_and_ignore_contract() -> None:
    for relative in PUBLIC_DOCS:
        assert (ROOT / relative).is_file(), relative
    evolution = (
        ROOT / "docs" / "AGENTIC_RAG_EVOLUTION_LOG.md"
    ).read_text(encoding="utf-8")
    top = "\n".join(evolution.splitlines()[:10])
    assert "历史工程日志" in top
    assert "../PROJECT_STATUS.md" in top

    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignore
    assert ".private/" in ignore
    assert ".superpowers/" in ignore
    assert "holdout_submissions/" in ignore


def test_public_audit_rejects_raw_holdout_submission_candidate(
    tmp_path: Path,
) -> None:
    from scripts.audit_public_repo import audit_repository

    payload = tmp_path / "holdout_submissions" / "reviewer-a" / "payload.json"
    payload.parent.mkdir(parents=True)
    payload.write_text('{"private":"holdout"}\n', encoding="utf-8")

    report = audit_repository(
        tmp_path,
        candidate_files=["holdout_submissions/reviewer-a/payload.json"],
    )

    assert (
        "forbidden_path",
        "holdout_submissions/reviewer-a/payload.json",
    ) in {(item.code, item.path) for item in report.findings}


def test_exposure_private_runs_are_ignored_and_forbidden_public_candidates(
    tmp_path: Path,
) -> None:
    from scripts.audit_public_repo import audit_repository

    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "exposure_runs/" in ignore
    payload = tmp_path / "exposure_runs" / "private" / "per_unit.jsonl"
    payload.parent.mkdir(parents=True)
    payload.write_text('{"unit_id":"private"}\n', encoding="utf-8")

    report = audit_repository(
        tmp_path,
        candidate_files=["exposure_runs/private/per_unit.jsonl"],
    )

    assert ("forbidden_path", "exposure_runs/private/per_unit.jsonl") in {
        (item.code, item.path) for item in report.findings
    }


def test_security_private_runs_are_forbidden_even_when_force_added(
    tmp_path: Path,
) -> None:
    from scripts.audit_public_repo import audit_repository

    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "security_runs/" in ignore
    payload = tmp_path / "security_runs" / "private" / "per_case.jsonl"
    payload.parent.mkdir(parents=True)
    payload.write_text('{"case_id":"private"}\n', encoding="utf-8")

    report = audit_repository(
        tmp_path,
        candidate_files=["security_runs/private/per_case.jsonl"],
    )

    assert ("forbidden_path", "security_runs/private/per_case.jsonl") in {
        (item.code, item.path) for item in report.findings
    }


def test_audit_rejects_exposure_private_runtime_reference(
    tmp_path: Path,
) -> None:
    from scripts.audit_public_repo import audit_repository

    payload = (
        tmp_path
        / "data"
        / "v2"
        / "public"
        / "r2_s1_d7"
        / "per_case.redacted.jsonl"
    )
    payload.parent.mkdir(parents=True)
    payload.write_text(
        "source: exposure_runs/private/manifest.json\n",
        encoding="utf-8",
    )

    report = audit_repository(
        tmp_path,
        candidate_files=["data/v2/public/r2_s1_d7/per_case.redacted.jsonl"],
    )

    assert (
        "private_runtime_reference",
        "data/v2/public/r2_s1_d7/per_case.redacted.jsonl",
    ) in {(item.code, item.path) for item in report.findings}


def test_audit_allows_d7_case_ids_but_rejects_same_id_in_r2_s3(
    tmp_path: Path,
) -> None:
    from scripts.audit_public_repo import audit_repository

    case_id = "r2s1-test-business-sop-action-language-1"
    dataset = (
        tmp_path / "data" / "v2" / "security" / "indirect_injection_test_v1.json"
    )
    dataset.parent.mkdir(parents=True)
    dataset.write_text(
        json.dumps({"cases": [{"case_id": case_id}]}),
        encoding="utf-8",
    )
    d7_relative = "data/v2/public/r2_s1_d7/per_case.redacted.jsonl"
    r2_s3_relative = "data/v2/public/r2_s3_exposure/per_unit.redacted.jsonl"
    for relative in (d7_relative, r2_s3_relative):
        public_file = tmp_path / Path(relative)
        public_file.parent.mkdir(parents=True, exist_ok=True)
        public_file.write_text(case_id + "\n", encoding="utf-8")

    report = audit_repository(
        tmp_path,
        candidate_files=[d7_relative, r2_s3_relative],
    )
    frozen_paths = {
        item.path
        for item in report.findings
        if item.code == "frozen_security_content"
    }

    assert d7_relative not in frozen_paths
    assert r2_s3_relative in frozen_paths


def test_audit_scans_r2_s3_for_private_runtime_reference(
    tmp_path: Path,
) -> None:
    from scripts.audit_public_repo import audit_repository

    relative = "data/v2/public/r2_s3_exposure/summary.json"
    payload = tmp_path / Path(relative)
    payload.parent.mkdir(parents=True)
    payload.write_text(
        "source: exposure_runs/private/manifest.json\n",
        encoding="utf-8",
    )

    report = audit_repository(tmp_path, candidate_files=[relative])

    assert ("private_runtime_reference", relative) in {
        (item.code, item.path) for item in report.findings
    }


def test_audit_scans_r2_s3_for_frozen_source_value(tmp_path: Path) -> None:
    from scripts.audit_public_repo import audit_repository

    dataset = (
        tmp_path / "data" / "v2" / "security" / "indirect_injection_test_v1.json"
    )
    dataset.parent.mkdir(parents=True)
    dataset.write_text(
        '{"cases":[{"question":"FROZEN_R2_S3_SOURCE_VALUE"}]}',
        encoding="utf-8",
    )
    relative = "data/v2/public/r2_s3_exposure/summary.json"
    payload = tmp_path / Path(relative)
    payload.parent.mkdir(parents=True)
    payload.write_text("FROZEN_R2_S3_SOURCE_VALUE\n", encoding="utf-8")

    report = audit_repository(tmp_path, candidate_files=[relative])

    assert ("frozen_security_content", relative) in {
        (item.code, item.path) for item in report.findings
    }


@pytest.mark.parametrize(
    "leaked_value",
    (
        "DEV_ONLY_QUESTION_NEVER_PUBLIC",
        "benign-unit-private-001",
        "OPEN_SECTION_PRIVATE_PATH",
    ),
)
def test_audit_scans_shared_dev_sensitive_identifiers_and_open_sections(
    tmp_path: Path,
    leaked_value: str,
) -> None:
    from scripts.audit_public_repo import audit_repository

    security_root = tmp_path / "data" / "v2" / "security"
    security_root.mkdir(parents=True)
    (security_root / "indirect_injection_dev_v1.json").write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "question": "DEV_ONLY_QUESTION_NEVER_PUBLIC",
                        "benign_unit_ids": ["benign-unit-private-001"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    fixture = security_root / "fixtures_v1" / "dev" / "manifest.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "open_results": [
                            {
                                "section_path": ["OPEN_SECTION_PRIVATE_PATH"]
                            }
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    relative = "data/v2/public/r2_s3_exposure/summary.json"
    public_file = tmp_path / Path(relative)
    public_file.parent.mkdir(parents=True)
    public_file.write_text(leaked_value + "\n", encoding="utf-8")

    report = audit_repository(tmp_path, candidate_files=[relative])

    assert ("frozen_security_content", relative) in {
        (item.code, item.path) for item in report.findings
    }


def test_audit_scans_r2_s3_for_system_prompt_fragment(tmp_path: Path) -> None:
    from scripts.audit_public_repo import audit_repository

    relative = "data/v2/public/r2_s3_exposure/README.md"
    payload = tmp_path / Path(relative)
    payload.parent.mkdir(parents=True)
    payload.write_text(
        "You are a grounded enterprise knowledge-base answer generator operating "
        "under public evidence.\n",
        encoding="utf-8",
    )

    report = audit_repository(tmp_path, candidate_files=[relative])

    assert ("system_prompt_fragment", relative) in {
        (item.code, item.path) for item in report.findings
    }


def test_audit_scans_r2_s3_for_environment_and_local_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.audit_public_repo import audit_repository

    relative = "data/v2/public/r2_s3_exposure/README.md"
    payload = tmp_path / Path(relative)
    payload.parent.mkdir(parents=True)
    payload.write_text(
        "HTTP_PROXY=http://proxy.invalid\nlocal owner slice4b-owner\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("USERNAME", "slice4b-owner")

    report = audit_repository(tmp_path, candidate_files=[relative])
    findings = {(item.code, item.path) for item in report.findings}

    assert ("environment_reference", relative) in findings
    assert ("local_identity", relative) in findings


def test_audit_allows_public_exposure_package_path(tmp_path: Path) -> None:
    from scripts.audit_public_repo import audit_repository

    payload = (
        tmp_path
        / "data"
        / "v2"
        / "public"
        / "r2_s3_exposure"
        / "summary.json"
    )
    payload.parent.mkdir(parents=True)
    payload.write_text('{"content_free":true}\n', encoding="utf-8")

    report = audit_repository(
        tmp_path,
        candidate_files=["data/v2/public/r2_s3_exposure/summary.json"],
    )

    assert report.passed is True


def test_private_e6_materials_are_ignored_and_candidate_free() -> None:
    private_root = ROOT / ".private" / "e6"
    names = [
        "interview_script_30s.md",
        "interview_script_1min.md",
        "interview_script_3min.md",
        "interview_qa.md",
        "claims_evidence_matrix.md",
        "learning_cards.md",
    ]
    for name in names:
        path = private_root / name
        ignored = subprocess.run(
            ["git", "-C", str(ROOT), "check-ignore", "-q", str(path)],
            check=False,
        )
        assert ignored.returncode == 0, name

    candidates = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        check=True,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
    ).stdout.splitlines()
    assert not any(path.startswith(".private/") for path in candidates)

    if not private_root.is_dir():
        return

    for name in names:
        assert (private_root / name).is_file(), name

    qa = (private_root / "interview_qa.md").read_text(encoding="utf-8")
    assert len(re.findall(r"^### Q\d+:", qa, flags=re.MULTILINE)) >= 25

    matrix = (private_root / "claims_evidence_matrix.md").read_text(
        encoding="utf-8"
    )
    assert (
        "claim_id | candidate_wording | evidence_file | metric_path | "
        "source_hash | boundary | status"
    ) in matrix
    claim_rows = [line for line in matrix.splitlines() if line.startswith("| E6-")]
    assert len(claim_rows) >= 8
    statuses = {row.rsplit("|", 2)[1].strip() for row in claim_rows}
    assert statuses <= {"approved", "narrowed", "rejected"}
    assert "pending_e7" not in "\n".join(claim_rows)


def test_r2_s3_delivery_boundary_requires_fixed_head_synthesis() -> None:
    handoff = (
        ROOT / "docs" / "roadmap" / "CURRENT_EXECUTION_HANDOFF.md"
    ).read_text(encoding="utf-8")
    plan = (
        ROOT
        / "docs"
        / "superpowers"
        / "plans"
        / "2026-07-21-r2-s3-exposure-aware-ablation.md"
    ).read_text(encoding="utf-8")
    top_boundary = handoff.split("## 3.", 1)[1].split("## 4.", 1)[0]
    current_breakpoint = handoff.split("## 20.", 1)[1]
    step_six = plan.split("**Step 6:", 1)[1]
    required_boundary = (
        "Push is allowed only after fixed-HEAD reviews and local gates pass; "
        "actual delivery and CI state are established by Git and GitHub Actions."
    )

    assert "current R2-S3 local commit state: COMPLETE" in top_boundary
    assert required_boundary in top_boundary
    assert "Historical E7 authorization only:" in top_boundary
    assert "does not establish delivery state for the current R2-S3 exact HEAD" in top_boundary
    assert "commit + push current feature branch: AUTHORIZED" not in top_boundary
    assert required_boundary in current_breakpoint
    assert required_boundary in step_six


def test_r2_s3_documented_isolated_verifier_sequence_executes(
    tmp_path: Path,
) -> None:
    protocol = (
        ROOT
        / "docs"
        / "security"
        / "r2_s3"
        / "00_exposure_ablation_protocol.md"
    ).read_text(encoding="utf-8")
    start_marker = "<!-- isolated-verifier-powershell:start -->"
    end_marker = "<!-- isolated-verifier-powershell:end -->"
    assert start_marker in protocol
    assert end_marker in protocol
    staging_package = ".tmp_r2_s3_final_public_04\\r2_s3_exposure"
    assert (
        "scripts.verify_indirect_injection_exposure_public `\n"
        f"  {staging_package}"
    ) in protocol
    assert f"$source = Join-Path $repo '{staging_package}'" in protocol
    replacement_boundary = (
        "After mechanically replacing the exact eight tracked files"
    )
    assert replacement_boundary in protocol
    post_replacement = protocol.split(replacement_boundary, 1)[1]
    assert (
        "scripts.verify_indirect_injection_exposure_public `\n"
        "  data\\v2\\public\\r2_s3_exposure"
    ) in post_replacement
    documented = protocol.split(start_marker, 1)[1].split(end_marker, 1)[0]
    match = re.search(r"```powershell\s*\n(.*?)\n```", documented, re.DOTALL)
    assert match is not None
    command = match.group(1)
    assert command.index("$python = (Resolve-Path") < command.index(
        "Push-Location"
    )

    staged_package = tmp_path / "staged" / "r2_s3_exposure"
    shutil.copytree(
        ROOT / "data" / "v2" / "public" / "r2_s3_exposure",
        staged_package,
    )
    powershell_path = str(staged_package).replace("'", "''")
    command = command.replace(
        f"$source = Join-Path $repo '{staging_package}'",
        f"$source = '{powershell_path}'",
    )

    environment = os.environ.copy()
    environment["TEMP"] = str(tmp_path)
    environment["TMP"] = str(tmp_path)
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.strip())
    assert result["status"] == "VERIFIED"
    assert result["row_count"] == 28
    isolated_roots = list(tmp_path.glob("r2_s3_exposure_verify_*"))
    assert len(isolated_roots) == 1
    assert {item.name for item in isolated_roots[0].iterdir()} == {
        "README.md",
        "checksums.sha256",
        "manifest.redacted.json",
        "metric_definitions.json",
        "per_unit.redacted.jsonl",
        "source_run.sha256",
        "summary.json",
        "verify.py",
    }


def test_r2_s3_docs_state_frozen_local_trust_boundary() -> None:
    documents = (
        ROOT / "docs" / "security" / "r2_s3" / "00_exposure_ablation_protocol.md",
        ROOT / "docs" / "known_limitations.md",
        ROOT / "docs" / "security" / "r2_s3" / "02_engineering_journal.md",
    )
    required_phrases = (
        "trusted local operator",
        "clean reviewed checkout",
        "stable filesystem during one verification/publication call",
        "trusted Python interpreter, import cache, dependencies, and runtime memory",
        "selected canonical source files on disk",
        "not loaded bytecode",
        "complete transitive implementation closure",
        "producer identity",
        "concurrent ABA replacement",
        "external immutable execution/attestation boundary",
    )

    for document in documents:
        text = " ".join(document.read_text(encoding="utf-8").split()).casefold()
        for phrase in required_phrases:
            assert phrase.casefold() in text, f"{document} is missing: {phrase}"


def test_r2_s3_backlog_remote_ci_claims_are_exact_head_scoped() -> None:
    backlog = (ROOT / "docs" / "industrialization_backlog.md").read_text(
        encoding="utf-8"
    )

    assert (
        "| P1 | Remote CI evidence for the current R2-S3 exact HEAD |"
        in backlog
    )
    assert "Historical `9607e55` evidence applies only to that commit." in backlog
    assert "- current R2-S3 exact HEAD remote CI passed;" in backlog


def test_remote_ci_history_is_not_presented_as_current_r2_s3_evidence() -> None:
    status = (ROOT / "PROJECT_STATUS.md").read_text(encoding="utf-8")
    limitations = (ROOT / "docs" / "known_limitations.md").read_text(
        encoding="utf-8"
    )

    for content in (status, limitations):
        assert "9607e55" in content
        assert "9fcb304" in content
        assert "不覆盖当前 R2-S3 exact HEAD" in content
    assert "历史 E7 代码候选 `9607e55" in status
    assert "当前功能分支候选" not in status


def test_r2_s3_current_docs_bind_regenerated_v2_evidence() -> None:
    package = ROOT / "data" / "v2" / "public" / "r2_s3_exposure"
    manifest_path = package / "manifest.redacted.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    public_manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    current_paths = (
        "README.md",
        "PROJECT_STATUS.md",
        "docs/known_limitations.md",
        "docs/industrialization_backlog.md",
        "docs/roadmap/CURRENT_EXECUTION_HANDOFF.md",
        "docs/security/r2_s3/00_exposure_ablation_protocol.md",
        "docs/security/r2_s3/01_results.md",
        "docs/security/r2_s3/02_engineering_journal.md",
        "docs/superpowers/plans/2026-07-21-r2-s3-exposure-aware-ablation.md",
    )
    contents = {
        relative: (ROOT / relative).read_text(encoding="utf-8")
        for relative in current_paths
    }
    identity_paths = current_paths[4:]
    accepted_run_id = "r2-s3-dev-exposure-20260721-04"
    private_manifest_sha256 = manifest["source_private_manifest_sha256"]
    evaluator_sha256 = (
        "d7fe9332953cc44ba3f517bb03d4074b293b821461240d30fc384d67256a4b88"
    )

    assert manifest["schema_version"] == (
        "indirect_injection_exposure_public_manifest_v2"
    )
    assert manifest["source_private_run_id"] == accepted_run_id
    for relative, content in contents.items():
        assert accepted_run_id in content, relative
    for relative in identity_paths:
        content = contents[relative]
        assert private_manifest_sha256 in content, relative
        assert public_manifest_sha256 in content, relative
        assert evaluator_sha256 in content, relative
        assert "indirect_injection_exposure_run_manifest_v2" in content, relative
        assert (
            "indirect_injection_exposure_public_manifest_v2" in content
        ), relative
        assert "r2-s3-dev-exposure-20260721-01" in content, relative
        assert "superseded local history" in content.casefold(), relative
        for dependency in manifest["replay_dependencies"]:
            assert dependency["path"] in content, relative
            assert dependency["sha256"] in content, relative

    required_boundary = (
        "Push is allowed only after fixed-HEAD reviews and local gates pass; "
        "actual delivery and CI state are established by Git and GitHub Actions."
    )
    assert required_boundary in contents[
        "docs/roadmap/CURRENT_EXECUTION_HANDOFF.md"
    ]
    assert required_boundary in contents[
        "docs/superpowers/plans/2026-07-21-r2-s3-exposure-aware-ablation.md"
    ]
