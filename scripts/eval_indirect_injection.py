from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.domain.retrieved_security import (
    DETECTOR_VERSION,
    MAX_DECODED_VIEWS,
    MAX_NORMALIZED_CHARS,
    MAX_SCAN_CHARS,
)
from app.evaluation.indirect_injection_dataset import load_security_bundle
from app.evaluation.indirect_injection_runner import (
    DeterministicSecurityConfig,
    PairedSecurityResult,
    evaluate_paired,
)
from app.evaluation.indirect_injection_writer import (
    R1_FROZEN_EXPECTED_HASHES,
    R1HashPair,
    SecurityRunManifest,
    build_release_gate,
    publish_security_run,
    redact_security_artifact_text,
    validate_security_run_id,
)


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_ROOT = BASE_DIR / "data" / "v2" / "security"
DEFAULT_OUT_DIR = BASE_DIR / "security_runs"
R1_EXPECTED_HASHES = R1_FROZEN_EXPECTED_HASHES
_ABSOLUTE_OUTPUT_PATTERNS = (
    re.compile(
        r"(?i)(?:\\\\[?.]\\[^\r\n\t]*|\\\\[^\\\s]+\\[^\\\s]+[^\r\n\t]*)"
    ),
    re.compile(r"(?i)(?<![A-Z0-9+.-])[A-Z]:[\\/][^\r\n\t]+"),
    re.compile(r"(?i)/(?:Users|home|root|tmp)/[^\r\n\t]+"),
)


@dataclass(frozen=True)
class RegressionRun:
    command: tuple[str, ...]
    exit_code: int
    output: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run deterministic paired Guard OFF/ON retrieved-content "
            "indirect-injection evaluation."
        )
    )
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser


def verify_r1_frozen_hashes(repository_root: Path) -> dict[str, R1HashPair]:
    root = Path(repository_root).resolve()
    evidence: dict[str, R1HashPair] = {}
    for relative_path, expected in R1_EXPECTED_HASHES.items():
        path = root / relative_path
        if not path.is_file():
            raise ValueError(f"R1 frozen file is missing: {relative_path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"R1 frozen hash mismatch: {relative_path}")
        evidence[relative_path] = R1HashPair(expected=expected, actual=actual)

    manifest_line = (root / "data/v2/eval/test_manifest.sha256").read_text(
        encoding="utf-8"
    ).strip()
    parts = manifest_line.split()
    if (
        len(parts) != 2
        or parts[0].casefold() != R1_EXPECTED_HASHES["data/v2/eval/test.json"]
        or parts[1] != "test.json"
    ):
        raise ValueError("R1 frozen test manifest token mismatch")
    return evidence


def run_r1_regression_suite(repository_root: Path) -> RegressionRun:
    root = Path(repository_root).resolve()
    execution_command = (sys.executable, "-m", "pytest", "-q")
    completed = subprocess.run(
        execution_command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    combined = completed.stdout
    if completed.stderr:
        combined += ("\n" if combined else "") + completed.stderr
    return RegressionRun(
        command=("python", "-m", "pytest", "-q"),
        exit_code=completed.returncode,
        output=_sanitize_output(combined, root),
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _validate_args(args)
    out_root = args.out_dir.resolve()
    target = (out_root / args.run_id).resolve()
    if target.parent != out_root:
        raise ValueError("run ID resolves outside output root")
    if target.exists():
        raise FileExistsError(f"security output run already exists: {target}")

    started_at = datetime.now(timezone.utc)
    git_provenance = _git_provenance(BASE_DIR)
    installed_dependency_snapshot = _installed_dependency_snapshot()
    r1_hashes = verify_r1_frozen_hashes(BASE_DIR)
    bundle = load_security_bundle(args.data_root, args.split)
    config = DeterministicSecurityConfig()
    result = evaluate_paired(bundle.dataset, bundle.fixture_manifest, config)
    regression = run_r1_regression_suite(BASE_DIR)
    _assert_git_provenance_stable(
        git_provenance,
        _git_provenance(BASE_DIR),
    )
    forbidden_texts = _forbidden_fixture_texts(bundle)
    release = build_release_gate(
        result,
        r1_hash_mismatch_count=0,
        r1_regression_failure_count=int(regression.exit_code != 0),
    )
    completed_at = datetime.now(timezone.utc)
    canonical_argv = _canonical_argv(args)
    manifest = _build_manifest(
        args=args,
        bundle=bundle,
        result=result,
        config=config,
        release=release,
        r1_hashes=r1_hashes,
        canonical_argv=canonical_argv,
        started_at=started_at,
        completed_at=completed_at,
        git_provenance=git_provenance,
        installed_dependency_snapshot=installed_dependency_snapshot,
    )
    output = publish_security_run(
        out_root,
        manifest,
        result,
        red_green_evidence=_red_green_evidence(result, release.status),
        commands=(
            " ".join(canonical_argv)
            + "\n"
            + " ".join(regression.command)
            + "\n"
        ),
        test_output=redact_security_artifact_text(
            _sanitize_output(
                regression.output or "pytest produced no output",
                BASE_DIR,
            ),
            forbidden_texts,
        ),
        forbidden_texts=forbidden_texts,
    )
    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "split": args.split,
                "status": release.status,
                "output_dir": str(output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if release.passed else 1


def _build_manifest(
    *,
    args: argparse.Namespace,
    bundle,
    result: PairedSecurityResult,
    config: DeterministicSecurityConfig,
    release,
    r1_hashes: dict[str, R1HashPair],
    canonical_argv: tuple[str, ...],
    started_at: datetime,
    completed_at: datetime,
    git_provenance: dict[str, object],
    installed_dependency_snapshot: dict[str, object],
) -> SecurityRunManifest:
    requirements = BASE_DIR / "requirements.txt"
    ruleset = BASE_DIR / "app" / "security" / "retrieved_content.py"
    evaluator = BASE_DIR / "app" / "evaluation" / "indirect_injection_runner.py"
    return SecurityRunManifest.model_validate(
        {
            "schema_version": "indirect_injection_security_run_manifest_v1",
            "producer": "enterprise_agentic_rag_v2",
            "run_id": args.run_id,
            "suite": "retrieved_content_indirect_injection",
            "split": args.split,
            "mode": "deterministic_paired",
            "started_at_utc": started_at,
            "completed_at_utc": completed_at,
            "status": release.status,
            "git": git_provenance,
            "environment": {
                "python_version": platform.python_version(),
                "platform": platform.platform(),
                "dependency_snapshot_path": "requirements.txt",
                "dependency_snapshot_sha256": _sha256(requirements),
                "dependency_snapshot_kind": "pinned-direct-requirements",
                **installed_dependency_snapshot,
                "ollama_version": "NOT_QUERIED_D6_DETERMINISTIC",
            },
            "models": {
                "embedding_model": "NOT_USED_D6_DETERMINISTIC",
                "chat_model": "d6-deterministic-fake-chat",
                "evidence_model": "NOT_USED_D6_DETERMINISTIC",
                "temperature": 0.0,
                "structured_output_variant": "generation-v2-json-schema",
            },
            "guard": {
                "detector_version": DETECTOR_VERSION,
                "ruleset_path": "app/security/retrieved_content.py",
                "ruleset_sha256": _sha256(ruleset),
                "max_scan_chars": MAX_SCAN_CHARS,
                "max_normalized_chars": MAX_NORMALIZED_CHARS,
                "max_decoded_views": MAX_DECODED_VIEWS,
            },
            "data": {
                "dataset_path": _safe_display_path(bundle.dataset_path, BASE_DIR),
                "dataset_sha256": bundle.dataset_sha256,
                "dataset_case_count": bundle.dataset.case_count,
                "fixture_manifest_path": _safe_display_path(
                    bundle.fixture_manifest_path,
                    BASE_DIR,
                ),
                "fixture_manifest_sha256": bundle.fixture_manifest_sha256,
                "attack_case_count": bundle.dataset.attack_case_count,
                "benign_case_count": bundle.dataset.benign_case_count,
                "r1_frozen_hashes": {
                    path: pair.model_dump(mode="json")
                    for path, pair in r1_hashes.items()
                },
            },
            "evaluator": {
                "path": "app/evaluation/indirect_injection_runner.py",
                "sha256": _sha256(evaluator),
                "argv": canonical_argv,
                "exit_code": 0 if release.passed else 1,
            },
            "retrieval": {
                "index": "synthetic-ranked-fixtures-v1",
                "index_sha256": "NOT_APPLICABLE_DETERMINISTIC_FIXTURE",
                "corpus": "checked-in-post-parser-synthetic-fixtures-v1",
                "corpus_sha256": bundle.fixture_manifest_sha256,
                "chunking": "post-parser-synthetic-content-units-v1",
                "top_k": config.top_k,
                "candidate_k": config.candidate_k,
                "max_search_calls": config.max_search_calls,
                "max_open_calls": config.max_open_calls,
                "max_steps": config.max_steps,
                "max_context_chars": config.max_context_chars,
            },
            "release_gate": release,
            "artifacts": {},
            "limitations": (
                "Deterministic fake generation proves propagation, not live-model resistance.",
                "The frozen test set is visible regression data, not an unseen benchmark.",
                "D7 live Qwen and BGE-M3 evaluation was not run by this command.",
            ),
        }
    )


def _git_provenance(root: Path) -> dict[str, object]:
    status = _git_bytes(root, "status", "--porcelain=v1", "--untracked-files=all")
    diff = _git_bytes(root, "diff", "--binary", "HEAD")
    untracked = _untracked_state_evidence(root)
    head = _git_text(root, "rev-parse", "HEAD")
    if re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise RuntimeError("Git provenance HEAD is unavailable or invalid")
    branch = _git_text(root, "branch", "--show-current") or None
    dirty_payload = status + b"\0" + diff + b"\0" + untracked
    return {
        "head": head,
        "branch": branch,
        "dirty": bool(status or diff),
        "status_entry_count": len(status.decode("utf-8", errors="replace").splitlines()),
        "dirty_state_sha256": hashlib.sha256(dirty_payload).hexdigest(),
    }


def _assert_git_provenance_stable(
    before: dict[str, object],
    after: dict[str, object],
) -> None:
    if before != after:
        raise RuntimeError("Git state changed during evaluation")


def _installed_dependency_snapshot() -> dict[str, object]:
    execution_command = (sys.executable, "-m", "pip", "freeze", "--all")
    completed = subprocess.run(
        execution_command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError("installed dependency snapshot command failed")
    lines = sorted(
        line.strip()
        for line in completed.stdout.splitlines()
        if line.strip()
    )
    if not lines:
        raise RuntimeError("installed dependency snapshot command returned no packages")
    normalized = ("\n".join(lines) + "\n").encode("utf-8")
    return {
        "installed_snapshot_command": (
            "python",
            "-m",
            "pip",
            "freeze",
            "--all",
        ),
        "installed_snapshot_sha256": hashlib.sha256(normalized).hexdigest(),
        "installed_package_count": len(lines),
    }


def _git_bytes(root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        command = " ".join(("git", *args[:2]))
        raise RuntimeError(f"Git provenance command failed: {command}")
    return completed.stdout


def _git_text(root: Path, *args: str) -> str:
    return _git_bytes(root, *args).decode("utf-8", errors="replace").strip()


def _untracked_state_evidence(root: Path) -> bytes:
    repository_root = Path(root).resolve()
    names = _git_bytes(
        repository_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
    ).split(b"\0")
    records: list[bytes] = []
    for encoded_name in sorted(name for name in names if name):
        relative_name = encoded_name.decode("utf-8", errors="replace")
        candidate = repository_root / relative_name
        try:
            resolved = candidate.resolve()
            resolved.relative_to(repository_root)
        except (OSError, ValueError):
            digest = "outside-or-unreadable"
        else:
            if candidate.is_symlink() or not resolved.is_file():
                digest = "non-regular-file"
            else:
                digest = _sha256(resolved)
        records.append(encoded_name + b"\0" + digest.encode("ascii"))
    return b"\0".join(records)


def _canonical_argv(args: argparse.Namespace) -> tuple[str, ...]:
    return (
        "python",
        "-m",
        "scripts.eval_indirect_injection",
        "--split",
        args.split,
        "--run-id",
        args.run_id,
        "--data-root",
        _safe_display_path(args.data_root.resolve(), BASE_DIR),
        "--out-dir",
        _safe_display_path(args.out_dir.resolve(), BASE_DIR),
    )


def _safe_display_path(path: Path, repository_root: Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(repository_root.resolve()).as_posix()
    except ValueError:
        return f"external/{resolved.name}"


def _forbidden_fixture_texts(bundle) -> tuple[str, ...]:
    values: set[str] = set()
    for case in bundle.dataset.cases:
        values.add(case.question)
        if case.document_canary:
            values.add(case.document_canary)
        values.add(case.trace_canary)
    for fixture in bundle.fixture_manifest.cases:
        values.update(fixture.fact_texts.values())
        for candidate in fixture.candidates:
            values.update((candidate.matched_text, candidate.context_text))
            if candidate.document_title:
                values.add(candidate.document_title)
            values.add(candidate.source_path)
            values.update(candidate.section_path)
            values.add(candidate.version)
        for item in fixture.open_results:
            values.update((item.content, item.source_path))
    return tuple(sorted(values))


def _red_green_evidence(result: PairedSecurityResult, status: str) -> str:
    off = result.guard_off.summary
    on = result.guard_on.summary
    return (
        "# R2-S1 D6 Deterministic RED/GREEN Evidence\n\n"
        f"Status: {status}\n\n"
        "The fake generator is a propagation witness only; it is not a live-model "
        "safety judgment.\n\n"
        f"- Guard OFF model-context exposure: "
        f"{off.model_context_exposure.numerator}/{off.model_context_exposure.denominator}\n"
        f"- Guard OFF document-canary exposure: "
        f"{off.document_canary_exposure.numerator}/{off.document_canary_exposure.denominator}\n"
        f"- Guard ON attack success: "
        f"{on.attack_success.numerator}/{on.attack_success.denominator}\n"
        f"- Guard ON quarantine recall: "
        f"{on.quarantine_recall.numerator}/{on.quarantine_recall.denominator}\n"
        f"- Guard ON benign quarantine: "
        f"{on.benign_quarantine.numerator}/{on.benign_quarantine.denominator}\n"
        f"- Guard ON clean task success: "
        f"{on.clean_task_success.numerator}/{on.clean_task_success.denominator}\n"
    )


def _sanitize_output(value: str, repository_root: Path) -> str:
    result = value.replace(str(repository_root), "<repository>")
    result = result.replace(str(repository_root).replace("\\", "/"), "<repository>")
    for pattern in _ABSOLUTE_OUTPUT_PATTERNS:
        result = pattern.sub("<absolute-path>", result)
    return result.strip() + "\n"


def _validate_args(args: argparse.Namespace) -> None:
    validate_security_run_id(args.run_id)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
