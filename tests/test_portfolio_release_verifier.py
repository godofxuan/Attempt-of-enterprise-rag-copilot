from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from scripts.verify_portfolio_release import (
    GATES,
    CommandRunner,
    verify_portfolio_release,
)


def _runner(
    *,
    dirty: bool = False,
    failing_gate: str | None = None,
    branch: str = "main",
    head_sha: str = "a" * 40,
) -> CommandRunner:
    def run(argv: tuple[str, ...], cwd: Path) -> CompletedProcess[str]:
        assert cwd.is_absolute()
        if argv[:3] == ("git", "rev-parse", "HEAD"):
            return CompletedProcess(argv, 0, stdout=head_sha + "\n", stderr="")
        if argv[:3] == ("git", "branch", "--show-current"):
            return CompletedProcess(
                argv,
                0,
                stdout=branch + ("\n" if branch else ""),
                stderr="",
            )
        if argv[:3] == ("git", "status", "--short"):
            output = " M README.md\n" if dirty else ""
            return CompletedProcess(argv, 0, stdout=output, stderr="")

        gate = next(item for item in GATES if item.argv == argv)
        if gate.gate_id == failing_gate:
            return CompletedProcess(
                argv,
                7,
                stdout="partial output\n",
                stderr="deterministic failure\n",
            )
        return CompletedProcess(argv, 0, stdout=f"{gate.gate_id} passed\n", stderr="")

    return run


def test_verified_report_has_stable_gate_contract() -> None:
    report = verify_portfolio_release(
        root=Path.cwd(),
        runner=_runner(),
        allow_dirty=False,
    )

    assert report["schema_version"] == "portfolio_release_verification_v3"
    assert report["status"] == "VERIFIED"
    assert report["release_authority"] is False
    assert report["repository"] == {
        "branch": "main",
        "dirty": False,
        "head_sha": "a" * 40,
        "expected_branch": "main",
        "expected_sha": None,
        "event_branch": None,
        "identity_event": "push",
    }
    assert [gate["gate_id"] for gate in report["gates"]] == [
        "dependency_consistency",
        "python_compile",
        "final_evidence_consistency",
        "agent_acl_guard_regression",
        "public_repository_audit",
    ]
    assert all(gate["status"] == "PASSED" for gate in report["gates"])
    assert report["summary"] == {
        "failed_gate_count": 0,
        "gate_count": 5,
        "passed_gate_count": 5,
    }


def test_failed_subgate_fails_closed_and_keeps_diagnostics() -> None:
    report = verify_portfolio_release(
        root=Path.cwd(),
        runner=_runner(failing_gate="final_evidence_consistency"),
        allow_dirty=False,
    )

    assert report["status"] == "FAILED"
    failed = next(
        gate
        for gate in report["gates"]
        if gate["gate_id"] == "final_evidence_consistency"
    )
    assert failed["exit_code"] == 7
    assert failed["status"] == "FAILED"
    assert failed["stdout_tail"] == "partial output"
    assert failed["stderr_tail"] == "deterministic failure"
    assert len(report["gates"]) == len(GATES)
    assert report["summary"]["failed_gate_count"] == 1


def test_dirty_repository_fails_unless_explicitly_allowed() -> None:
    strict = verify_portfolio_release(
        root=Path.cwd(),
        runner=_runner(dirty=True),
        allow_dirty=False,
    )
    development = verify_portfolio_release(
        root=Path.cwd(),
        runner=_runner(dirty=True),
        allow_dirty=True,
    )

    assert strict["status"] == "FAILED"
    assert strict["repository_gate"] == "FAILED_DIRTY_WORKTREE"
    assert development["status"] == "DEVELOPMENT_VERIFIED"
    assert development["repository_gate"] == "DIRTY_ALLOWED_DEVELOPMENT_ONLY"
    assert development["release_authority"] is False


@pytest.mark.parametrize(
    ("branch", "head_sha", "expected_sha"),
    [
        ("", "a" * 40, None),
        ("codex/rag-eval-system", "a" * 40, None),
        ("main", "b" * 40, "a" * 40),
    ],
)
def test_unexpected_target_identity_fails_closed(
    branch: str,
    head_sha: str,
    expected_sha: str | None,
) -> None:
    report = verify_portfolio_release(
        root=Path.cwd(),
        runner=_runner(branch=branch, head_sha=head_sha),
        expected_sha=expected_sha,
    )

    assert report["status"] == "FAILED"
    assert report["repository_gate"] == "FAILED_TARGET_IDENTITY"
    assert report["identity_errors"]


def test_push_identity_accepts_matching_branch_and_sha() -> None:
    report = verify_portfolio_release(
        root=Path.cwd(),
        runner=_runner(branch="codex/agent-runtime-vnext", head_sha="b" * 40),
        identity_event="push",
        expected_branch="codex/agent-runtime-vnext",
        expected_sha="b" * 40,
    )

    assert report["status"] == "VERIFIED"


@pytest.mark.parametrize(
    ("branch", "head_sha"),
    [
        ("wrong-branch", "b" * 40),
        ("codex/agent-runtime-vnext", "c" * 40),
    ],
)
def test_push_identity_rejects_wrong_branch_or_sha(
    branch: str,
    head_sha: str,
) -> None:
    report = verify_portfolio_release(
        root=Path.cwd(),
        runner=_runner(branch=branch, head_sha=head_sha),
        identity_event="push",
        expected_branch="codex/agent-runtime-vnext",
        expected_sha="b" * 40,
    )

    assert report["status"] == "FAILED"
    assert report["repository_gate"] == "FAILED_TARGET_IDENTITY"


def test_pull_request_identity_accepts_detached_head_bound_to_event() -> None:
    report = verify_portfolio_release(
        root=Path.cwd(),
        runner=_runner(branch="", head_sha="b" * 40),
        identity_event="pull_request",
        expected_branch="feature/pr-head",
        expected_sha="b" * 40,
        event_branch="feature/pr-head",
    )

    assert report["status"] == "VERIFIED"
    assert report["repository"]["branch"] == ""


@pytest.mark.parametrize(
    ("head_sha", "event_branch"),
    [
        ("c" * 40, "feature/pr-head"),
        ("b" * 40, "feature/wrong-head"),
    ],
)
def test_pull_request_identity_rejects_wrong_sha_or_event_branch(
    head_sha: str,
    event_branch: str,
) -> None:
    report = verify_portfolio_release(
        root=Path.cwd(),
        runner=_runner(branch="", head_sha=head_sha),
        identity_event="pull_request",
        expected_branch="feature/pr-head",
        expected_sha="b" * 40,
        event_branch=event_branch,
    )

    assert report["status"] == "FAILED"
    assert report["repository_gate"] == "FAILED_TARGET_IDENTITY"


def test_report_is_json_serializable_without_absolute_commands() -> None:
    report = verify_portfolio_release(
        root=Path.cwd(),
        runner=_runner(),
        allow_dirty=False,
    )

    encoded = json.dumps(report, sort_keys=True)
    assert "portfolio_release_verification_v3" in encoded
    for gate in report["gates"]:
        assert gate["command"][0] == "python"
        assert not Path(gate["command"][0]).is_absolute()
