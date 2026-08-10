from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from subprocess import CompletedProcess
from time import perf_counter
from typing import Callable, Sequence


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "portfolio_release_verification_v2"
DEFAULT_EXPECTED_BRANCH = "codex/rag-eval-system"
CommandRunner = Callable[[tuple[str, ...], Path], CompletedProcess[str]]


@dataclass(frozen=True)
class Gate:
    gate_id: str
    description: str
    argv: tuple[str, ...]


GATES = (
    Gate(
        gate_id="dependency_consistency",
        description="Installed dependencies have no resolver conflicts.",
        argv=(sys.executable, "-m", "pip", "check"),
    ),
    Gate(
        gate_id="python_compile",
        description="Tracked Python application, scripts, UI, and tests compile.",
        argv=(
            sys.executable,
            "-m",
            "compileall",
            "-q",
            "app",
            "scripts",
            "streamlit_app",
            "tests",
        ),
    ),
    Gate(
        gate_id="final_evidence_consistency",
        description="Resume and closeout claims derive from public evidence.",
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_final_closeout_evidence.py",
            "tests/test_final_evidence_closure.py",
            "tests/evaluation/test_wixqa_multidoc_candidate_evidence.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ),
    ),
    Gate(
        gate_id="agent_acl_guard_regression",
        description="Offline Agent, ACL, and retrieved-content Guard contracts pass.",
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/agent_v2",
            "tests/retrieval/test_pipeline_acl.py",
            "tests/security/test_retrieved_content_guard.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ),
    ),
    Gate(
        gate_id="public_repository_audit",
        description="Tracked and untracked public candidates pass the leak audit.",
        argv=(sys.executable, "-m", "scripts.audit_public_repo"),
    ),
)


def _run_command(argv: tuple[str, ...], cwd: Path) -> CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _text(result: CompletedProcess[str], stream: str) -> str:
    value = getattr(result, stream, "")
    return value if isinstance(value, str) else ""


def _tail(value: str, *, line_count: int = 40) -> str:
    lines = value.strip().splitlines()
    return "\n".join(lines[-line_count:])


def _public_command(argv: Sequence[str]) -> list[str]:
    command = list(argv)
    if command and Path(command[0]).name.lower() in {
        "python",
        "python.exe",
        "python3",
        "python3.exe",
    }:
        command[0] = "python"
    return command


def _git_value(
    root: Path,
    runner: CommandRunner,
    argv: tuple[str, ...],
) -> tuple[str, int, str]:
    result = runner(argv, root)
    return (
        _text(result, "stdout").strip(),
        result.returncode,
        _tail(_text(result, "stderr")),
    )


def verify_portfolio_release(
    *,
    root: Path = ROOT,
    runner: CommandRunner = _run_command,
    allow_dirty: bool = False,
    expected_branch: str = DEFAULT_EXPECTED_BRANCH,
    expected_sha: str | None = None,
) -> dict[str, object]:
    root = root.resolve()
    head_sha, head_code, head_error = _git_value(
        root,
        runner,
        ("git", "rev-parse", "HEAD"),
    )
    branch, branch_code, branch_error = _git_value(
        root,
        runner,
        ("git", "branch", "--show-current"),
    )
    status_text, status_code, status_error = _git_value(
        root,
        runner,
        ("git", "status", "--short"),
    )
    git_errors = [
        error
        for code, error in (
            (head_code, head_error),
            (branch_code, branch_error),
            (status_code, status_error),
        )
        if code != 0
    ]
    dirty = bool(status_text)

    gate_results: list[dict[str, object]] = []
    for gate in GATES:
        started = perf_counter()
        result = runner(gate.argv, root)
        elapsed_ms = round((perf_counter() - started) * 1000, 3)
        passed = result.returncode == 0
        gate_results.append(
            {
                "command": _public_command(gate.argv),
                "description": gate.description,
                "duration_ms": elapsed_ms,
                "exit_code": result.returncode,
                "gate_id": gate.gate_id,
                "status": "PASSED" if passed else "FAILED",
                "stderr_tail": (
                    "" if passed else _tail(_text(result, "stderr"))
                ),
                "stdout_tail": (
                    "" if passed else _tail(_text(result, "stdout"))
                ),
            }
        )

    identity_errors: list[str] = []
    if branch != expected_branch:
        identity_errors.append(
            f"expected branch {expected_branch!r}, observed {branch!r}"
        )
    if expected_sha is not None and head_sha != expected_sha:
        identity_errors.append(
            f"expected SHA {expected_sha!r}, observed {head_sha!r}"
        )

    if git_errors:
        repository_gate = "FAILED_GIT_STATE"
    elif identity_errors:
        repository_gate = "FAILED_TARGET_IDENTITY"
    elif dirty and not allow_dirty:
        repository_gate = "FAILED_DIRTY_WORKTREE"
    elif dirty:
        repository_gate = "DIRTY_ALLOWED_DEVELOPMENT_ONLY"
    else:
        repository_gate = "PASSED_CLEAN_WORKTREE"

    subgates_passed = all(
        result["status"] == "PASSED" for result in gate_results
    )
    passed_gate_count = sum(
        result["status"] == "PASSED" for result in gate_results
    )
    if not subgates_passed or repository_gate.startswith("FAILED"):
        overall_status = "FAILED"
    elif dirty:
        overall_status = "DEVELOPMENT_VERIFIED"
    else:
        overall_status = "VERIFIED"

    return {
        "claim_boundary": (
            "Offline portfolio evidence and deterministic regression gate; "
            "not production readiness, model quality, or third-party validation."
        ),
        "gates": gate_results,
        "git_errors": git_errors,
        "identity_errors": identity_errors,
        "release_authority": False,
        "repository": {
            "branch": branch,
            "dirty": dirty,
            "head_sha": head_sha,
            "expected_branch": expected_branch,
            "expected_sha": expected_sha,
        },
        "repository_gate": repository_gate,
        "schema_version": SCHEMA_VERSION,
        "status": overall_status,
        "summary": {
            "failed_gate_count": len(gate_results) - passed_gate_count,
            "gate_count": len(gate_results),
            "passed_gate_count": passed_gate_count,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the offline, fail-closed portfolio evidence verification gate."
        )
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help=(
            "Allow a dirty worktree for development diagnostics. The report is "
            "labeled DEVELOPMENT_VERIFIED and has no release authority."
        ),
    )
    parser.add_argument(
        "--expected-branch",
        default=DEFAULT_EXPECTED_BRANCH,
        help="Require this exact non-detached branch name.",
    )
    parser.add_argument(
        "--expected-sha",
        help="Optionally require this exact 40-character commit SHA.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = verify_portfolio_release(
        allow_dirty=args.allow_dirty,
        expected_branch=args.expected_branch,
        expected_sha=args.expected_sha,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] != "FAILED" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CommandRunner",
    "DEFAULT_EXPECTED_BRANCH",
    "GATES",
    "Gate",
    "build_parser",
    "main",
    "verify_portfolio_release",
]
