from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
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

SECURITY_CORPUS_PATHS = (
    "data/v2/security/indirect_injection_dev_v1.json",
    "data/v2/security/indirect_injection_test_v1.json",
    "data/v2/security/fixtures_v1/dev/manifest.json",
    "data/v2/security/fixtures_v1/test/manifest.json",
)
R2_S3_PUBLIC_PACKAGE_PATHS = frozenset(
    {
        "README.md",
        "checksums.sha256",
        "manifest.redacted.json",
        "metric_definitions.json",
        "per_unit.redacted.jsonl",
        "source_run.sha256",
        "summary.json",
        "verify.py",
    }
)
R2_S4_PUBLIC_PACKAGE_PATHS = frozenset(
    {
        "README.md",
        "checksums.sha256",
        "commands.txt",
        "manifest.json",
        "per_case_redacted.jsonl",
        "summary.json",
        "verification_witness.json",
        "verify.py",
    }
)


def _write_minimal_complete_security_corpus(root: Path) -> None:
    for relative in SECURITY_CORPUS_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, path)


def _assert_exact_public_exposure_package_tree(
    package: Path,
    expected_paths: frozenset[str],
) -> None:
    package_stat = package.lstat()
    assert stat.S_ISDIR(package_stat.st_mode)
    assert not stat.S_ISLNK(package_stat.st_mode)
    assert not (
        getattr(package_stat, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )
    observed_paths = {
        path.relative_to(package).as_posix() for path in package.rglob("*")
    }
    assert observed_paths == expected_paths
    for relative in expected_paths:
        observed = (package / relative).lstat()
        assert stat.S_ISREG(observed.st_mode), relative
        assert not stat.S_ISLNK(observed.st_mode), relative
        assert not (
            getattr(observed, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ), relative


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
        "jwt.txt": "eyJ" + "a" * 12 + "." + "b" * 20 + "." + "c" * 32,
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
    assert ("credential_token", "jwt.txt") in findings
    assert ("non_example_email", "README.md") in findings
    assert ("absolute_user_path", "README.md") in findings
    assert ("missing_local_link", "README.md") in findings
    assert ("file_too_large", "large.bin") in findings
    assert not any(item.path == "tests/safe.txt" for item in report.findings)
    assert report.passed is False


@pytest.mark.parametrize("missing_relative", SECURITY_CORPUS_PATHS)
def test_audit_fails_closed_when_required_security_corpus_file_is_missing(
    tmp_path: Path,
    missing_relative: str,
) -> None:
    from scripts.audit_public_repo import audit_repository

    _write_minimal_complete_security_corpus(tmp_path)
    (tmp_path / missing_relative).unlink()

    report = audit_repository(tmp_path, candidate_files=())

    assert (
        "invalid_security_corpus",
        missing_relative,
        "required security corpus file is missing",
    ) in {
        (item.code, item.path, item.detail) for item in report.findings
    }
    assert report.passed is False


def test_audit_fails_closed_when_security_corpus_is_absent(
    tmp_path: Path,
) -> None:
    from scripts.audit_public_repo import audit_repository

    report = audit_repository(tmp_path, candidate_files=())

    assert {
        item.path
        for item in report.findings
        if item.code == "invalid_security_corpus"
    } == set(SECURITY_CORPUS_PATHS)
    assert report.passed is False


@pytest.mark.parametrize(
    ("relative", "payload", "detail"),
    (
        (
            SECURITY_CORPUS_PATHS[0],
            b"\xff",
            "security corpus file is not valid UTF-8",
        ),
        (
            SECURITY_CORPUS_PATHS[0],
            b"{\n",
            "security corpus file contains malformed JSON",
        ),
        (
            SECURITY_CORPUS_PATHS[0],
            b"[]\n",
            "security corpus top level must be an object",
        ),
        (
            SECURITY_CORPUS_PATHS[0],
            b"{}\n",
            "security corpus requires a cases collection",
        ),
        (
            SECURITY_CORPUS_PATHS[0],
            b'{"cases":{}}\n',
            "security corpus cases collection must be an array",
        ),
        (
            SECURITY_CORPUS_PATHS[0],
            b'{"cases":[[]]}\n',
            "security corpus cases entries must be objects",
        ),
        (
            SECURITY_CORPUS_PATHS[2],
            b'{"cases":[{"open_results":[]}]}\n',
            "fixture case requires a candidates collection",
        ),
        (
            SECURITY_CORPUS_PATHS[2],
            b'{"cases":[{"candidates":[]}]}\n',
            "fixture case requires an open_results collection",
        ),
        (
            SECURITY_CORPUS_PATHS[2],
            b'{"cases":[{"candidates":{},"open_results":[]}]}\n',
            "fixture candidates collection must be an array",
        ),
        (
            SECURITY_CORPUS_PATHS[2],
            b'{"cases":[{"candidates":[[]],"open_results":[]}]}\n',
            "fixture candidates entries must be objects",
        ),
        (
            SECURITY_CORPUS_PATHS[2],
            b'{"cases":[{"candidates":[],"open_results":{}}]}\n',
            "fixture open_results collection must be an array",
        ),
        (
            SECURITY_CORPUS_PATHS[2],
            b'{"cases":[{"candidates":[],"open_results":[[]]}]}\n',
            "fixture open_results entries must be objects",
        ),
    ),
)
def test_audit_fails_closed_on_invalid_security_corpus_structure(
    tmp_path: Path,
    relative: str,
    payload: bytes,
    detail: str,
) -> None:
    from scripts.audit_public_repo import audit_repository

    _write_minimal_complete_security_corpus(tmp_path)
    (tmp_path / relative).write_bytes(payload)

    report = audit_repository(tmp_path, candidate_files=())

    assert ("invalid_security_corpus", relative, detail) in {
        (item.code, item.path, item.detail) for item in report.findings
    }
    assert report.passed is False


@pytest.mark.parametrize(
    ("relative", "mutation"),
    (
        (SECURITY_CORPUS_PATHS[0], "empty_dataset_cases"),
        (SECURITY_CORPUS_PATHS[2], "empty_fixture_cases"),
        (SECURITY_CORPUS_PATHS[0], "wrong_typed_dataset_question"),
        (SECURITY_CORPUS_PATHS[2], "wrong_typed_fixture_matched_text"),
    ),
)
def test_audit_rejects_incomplete_or_wrong_typed_security_corpus(
    tmp_path: Path,
    relative: str,
    mutation: str,
) -> None:
    from scripts.audit_public_repo import audit_repository

    _write_minimal_complete_security_corpus(tmp_path)
    path = tmp_path / relative
    payload = json.loads(path.read_text(encoding="utf-8"))
    protected_text = "PROTECTED_SECURITY_VALUE"
    if mutation == "empty_dataset_cases":
        payload["cases"] = []
    elif mutation == "empty_fixture_cases":
        payload["cases"] = []
    elif mutation == "wrong_typed_dataset_question":
        payload["cases"][0]["question"] = [protected_text]
    elif mutation == "wrong_typed_fixture_matched_text":
        payload["cases"][0]["candidates"][0]["matched_text"] = [
            protected_text
        ]
    else:
        raise AssertionError(f"unexpected mutation: {mutation}")
    path.write_text(json.dumps(payload), encoding="utf-8")

    report = audit_repository(tmp_path, candidate_files=())

    assert ("invalid_security_corpus", relative) in {
        (item.code, item.path) for item in report.findings
    }
    assert report.passed is False


@pytest.mark.parametrize("mutation", ("remove", "empty"))
def test_audit_rejects_fixture_that_omits_canonical_open_results(
    tmp_path: Path,
    mutation: str,
) -> None:
    from scripts.audit_public_repo import audit_repository

    _write_minimal_complete_security_corpus(tmp_path)
    relative = SECURITY_CORPUS_PATHS[2]
    path = tmp_path / relative
    payload = json.loads(path.read_text(encoding="utf-8"))
    fixture_case = next(case for case in payload["cases"] if case["open_results"])
    if mutation == "remove":
        del fixture_case["open_results"]
    elif mutation == "empty":
        fixture_case["open_results"] = []
    else:
        raise AssertionError(f"unexpected mutation: {mutation}")
    path.write_text(json.dumps(payload), encoding="utf-8")

    report = audit_repository(tmp_path, candidate_files=())

    assert ("invalid_security_corpus", relative) in {
        (item.code, item.path) for item in report.findings
    }
    assert report.passed is False


@pytest.mark.parametrize(
    ("relative", "replacement_relative"),
    (
        (SECURITY_CORPUS_PATHS[0], SECURITY_CORPUS_PATHS[1]),
        (SECURITY_CORPUS_PATHS[2], SECURITY_CORPUS_PATHS[3]),
    ),
)
def test_audit_rejects_security_corpus_source_with_misplaced_split(
    tmp_path: Path,
    relative: str,
    replacement_relative: str,
) -> None:
    from scripts.audit_public_repo import audit_repository

    _write_minimal_complete_security_corpus(tmp_path)
    shutil.copyfile(ROOT / replacement_relative, tmp_path / relative)

    report = audit_repository(tmp_path, candidate_files=())

    assert ("invalid_security_corpus", relative) in {
        (item.code, item.path) for item in report.findings
    }
    assert report.passed is False


def test_audit_fails_closed_when_security_corpus_file_is_unreadable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.audit_public_repo import audit_repository

    _write_minimal_complete_security_corpus(tmp_path)
    target = tmp_path / SECURITY_CORPUS_PATHS[1]
    real_read_text = Path.read_text

    def fail_target_read(path: Path, *args, **kwargs) -> str:
        if path == target:
            raise PermissionError("simulated unreadable corpus")
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_target_read)

    report = audit_repository(tmp_path, candidate_files=())

    assert (
        "invalid_security_corpus",
        SECURITY_CORPUS_PATHS[1],
        "security corpus file is unreadable",
    ) in {
        (item.code, item.path, item.detail) for item in report.findings
    }
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

    credential = "RealLooking" + "SecretValue42"
    runtime = tmp_path / "app" / "leaky_config.py"
    runtime.parent.mkdir(parents=True)
    runtime.write_text(
        'cache_path = "C:\\Users\\alice\\private\\cache"\n'
        + "pass"
        + f'word = "{credential}"\n',
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


def test_audit_strong_scans_ordinary_security_docs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.audit_public_repo import audit_repository

    _write_minimal_complete_security_corpus(tmp_path)
    dataset = (
        tmp_path / "data" / "v2" / "security" / "indirect_injection_test_v1.json"
    )
    dataset_payload = json.loads(dataset.read_text(encoding="utf-8"))
    dataset_payload["cases"][0]["question"] = "FROZEN_R2_S5_QUESTION"
    dataset.write_text(json.dumps(dataset_payload), encoding="utf-8")

    credential = "Production" + "Secret42"
    service_key = "Live" + "ServiceKey42"
    docs = {
        "docs/security/r2_s5/password.md": "pass" + f"word={credential}\n",
        "docs/security/r2_s5/api-key.md": "api_" + f"key: {service_key}\n",
        "docs/security/r2_s5/identity.md": "local owner slice5-owner\n",
        "docs/security/r2_s5/evidence/runtime.md": (
            "evidence: security_runs/r2_s5/private/result.json\n"
        ),
        "docs/security/r2_s5/evidence/frozen.md": "FROZEN_R2_S5_QUESTION\n",
    }
    for relative, content in docs.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("USERNAME", "slice5-owner")

    report = audit_repository(tmp_path, candidate_files=docs)
    findings = {(item.code, item.path) for item in report.findings}

    assert (
        "credential_assignment",
        "docs/security/r2_s5/password.md",
    ) in findings
    assert (
        "credential_assignment",
        "docs/security/r2_s5/api-key.md",
    ) in findings
    assert ("local_identity", "docs/security/r2_s5/identity.md") in findings
    assert (
        "private_runtime_reference",
        "docs/security/r2_s5/evidence/runtime.md",
    ) in findings
    assert (
        "frozen_security_content",
        "docs/security/r2_s5/evidence/frozen.md",
    ) in findings


def test_audit_strong_scan_allows_safe_credential_placeholders(
    tmp_path: Path,
) -> None:
    from scripts.audit_public_repo import audit_repository

    _write_minimal_complete_security_corpus(tmp_path)
    relative = "docs/security/r2_s5/safe-examples.md"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(
        "password=<redacted>\n"
        "api_key=placeholder\n"
        "access_token=settings.access_token\n"
        "secret=********\n",
        encoding="utf-8",
    )

    report = audit_repository(tmp_path, candidate_files=[relative])

    assert not any(
        item.code == "credential_assignment" and item.path == relative
        for item in report.findings
    )


def test_audit_strong_scans_ordinary_test_sources(tmp_path: Path) -> None:
    from scripts.audit_public_repo import audit_repository

    _write_minimal_complete_security_corpus(tmp_path)
    relative = "tests/ordinary_module.py"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(
        "pass" + "word = " + repr("ProductionSecret42") + "\n",
        encoding="utf-8",
    )

    report = audit_repository(tmp_path, candidate_files=[relative])

    assert ("credential_assignment", relative) in {
        (item.code, item.path) for item in report.findings
    }


def test_audit_only_masks_structured_scanner_rule_definitions(
    tmp_path: Path,
) -> None:
    from scripts.audit_public_repo import audit_repository

    _write_minimal_complete_security_corpus(tmp_path)
    relative = "scripts/audit_public_repo.py"
    source = (
        "_PRIVATE_RUNTIME_REFERENCE_PATTERN = "
        "re.compile(r'security_runs/private')\n"
        "_POSIX_USER_PATH_PATTERN = re.compile(r'/home/example')\n"
        "def _local_identity_values():\n"
        "    return os.environ.get('USERPROFILE')\n"
    )
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")

    report = audit_repository(tmp_path, candidate_files=[relative])

    assert not any(
        item.code in {"credential_assignment", "private_runtime_reference"}
        and item.path == relative
        for item in report.findings
    )


def test_audit_does_not_mask_credentials_inside_auditor_test_functions(
    tmp_path: Path,
) -> None:
    from scripts.audit_public_repo import audit_repository

    _write_minimal_complete_security_corpus(tmp_path)
    relative = "tests/test_public_repository.py"
    credential = "Production" + "Secret42"
    leaked_assignment = "client_" + f"secret={credential}"
    source = (
        "def test_fixture():\n"
        f"    payload = {leaked_assignment!r}\n"
        "    audit_repository(root, candidate_files=[payload])\n"
    )
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")

    report = audit_repository(tmp_path, candidate_files=[relative])

    assert ("credential_assignment", relative) in {
        (item.code, item.path) for item in report.findings
    }


@pytest.mark.parametrize(
    "credential_name",
    [
        "client_secret",
        "AWS_SECRET_ACCESS_KEY",
        "secret_access_key",
        "refresh_token",
        "token",
    ],
)
def test_audit_detects_common_credential_assignment_names(
    tmp_path: Path,
    credential_name: str,
) -> None:
    from scripts.audit_public_repo import audit_repository

    _write_minimal_complete_security_corpus(tmp_path)
    relative = "config/leaked.env"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    credential = "Live" + "CredentialValue42"
    path.write_text(f"{credential_name}={credential}\n", encoding="utf-8")

    report = audit_repository(tmp_path, candidate_files=[relative])

    assert ("credential_assignment", relative) in {
        (item.code, item.path) for item in report.findings
    }


@pytest.mark.parametrize(
    "credential_parts",
    [
        ("la", "test", "-production-value"),
        ("P@", "$$", "w0rdSecret42"),
        ("real", "(value)", "with-secret"),
        ("prod-", "test", "-LiveCredentialValue42"),
        ("real-", "redacted", "-LiveCredentialValue42"),
    ],
)
def test_audit_safe_marker_substrings_do_not_hide_literal_credentials(
    tmp_path: Path,
    credential_parts: tuple[str, ...],
) -> None:
    from scripts.audit_public_repo import audit_repository

    _write_minimal_complete_security_corpus(tmp_path)
    relative = "config/collision.py"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    credential = "".join(credential_parts)
    path.write_text(f"client_secret = {credential!r}\n", encoding="utf-8")

    report = audit_repository(tmp_path, candidate_files=[relative])

    assert ("credential_assignment", relative) in {
        (item.code, item.path) for item in report.findings
    }


def test_api_docs_publish_authenticated_body_framing_errors() -> None:
    api_docs = (ROOT / "docs" / "api.md").read_text(encoding="utf-8")

    assert (
        "| 400 | `invalid_content_length`, `invalid_request_body` |"
        in api_docs
    )
    assert "重复 `Content-Length`" in api_docs
    assert "`Content-Length` 与 `Transfer-Encoding` 并存" in api_docs
    assert "非法 ASGI body framing" in api_docs


def test_audit_detects_aws_access_key_id_shape(tmp_path: Path) -> None:
    from scripts.audit_public_repo import audit_repository

    _write_minimal_complete_security_corpus(tmp_path)
    relative = "config/aws.env"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    access_key_id = "AKIA" + ("A" * 16)
    path.write_text(access_key_id + "\n", encoding="utf-8")

    report = audit_repository(tmp_path, candidate_files=[relative])

    assert ("credential_token", relative) in {
        (item.code, item.path) for item in report.findings
    }


def test_audit_fixture_mask_does_not_hide_high_confidence_tokens(
    tmp_path: Path,
) -> None:
    from scripts.audit_public_repo import audit_repository

    _write_minimal_complete_security_corpus(tmp_path)
    relative = "tests/test_public_repository.py"
    token = "ghp_" + "a" * 36
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(
        "def test_fixture():\n"
        f"    payload = {token!r}\n"
        "    audit_repository(root, candidate_files=[payload])\n",
        encoding="utf-8",
    )

    report = audit_repository(tmp_path, candidate_files=[relative])

    assert ("credential_token", relative) in {
        (item.code, item.path) for item in report.findings
    }


def test_audit_scans_d7_public_evidence_for_private_runtime_and_frozen_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.audit_public_repo import audit_repository

    _write_minimal_complete_security_corpus(tmp_path)
    dataset = tmp_path / "data" / "v2" / "security" / "indirect_injection_test_v1.json"
    dataset_payload = json.loads(dataset.read_text(encoding="utf-8"))
    dataset_payload["cases"][0]["question"] = "FROZEN_QUESTION_DO_NOT_PUBLISH"
    dataset.write_text(json.dumps(dataset_payload), encoding="utf-8")
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
        "pass"
        f"word={'Production' + 'Secret42'}\n"
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
    assert commands == [
        r".\.venv\Scripts\python.exe -m scripts.manage_demo_identity init --force",
        r".\.venv\Scripts\python.exe -m pytest -q",
        (
            r".\.venv\Scripts\python.exe -m uvicorn app.main:app "
            r"--host 127.0.0.1 --port 8000"
        ),
        (
            r".\.venv\Scripts\python.exe -m streamlit run streamlit_app/ui.py "
            r"--server.address 127.0.0.1 --server.port 8501"
        ),
    ]
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

    assert "更新时间：2026-07-27" in status
    assert "R2-S8 independent quality evidence" in status
    assert "public_synthetic / not_independent / NOT_RUN" in status
    assert "R2-S6 versioned corpus expansion" in status
    assert "当前状态：知识库默认 profile" in status
    assert "20260724T024653Z_expanded_bge_m3_fixed" in status
    assert "526 passed" in status
    assert "574 passed" in status
    assert "109 passed" not in status
    assert "历史 R2-S4 结果继续有效" in status
    assert "CONSISTENT_OBSERVATION" in status
    assert "release_pass=false" in status
    assert "actual tracked R2-S4 public package NOT CREATED" not in status
    assert "八文件 public package 与独立标准库 verifier" not in status
    assert "历史快照" in historical[:300]
    assert "../PROJECT_STATUS.md" in historical[:300]


def test_r2_s4_task8_public_package_and_current_docs_contract() -> None:
    package = ROOT / "data" / "v2" / "public" / "r2_s4_cross_model"
    manifest_path = package / "manifest.json"
    summary_path = package / "summary.json"
    commands_path = package / "commands.txt"

    assert {path.name for path in package.iterdir()} == R2_S4_PUBLIC_PACKAGE_PATHS
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == (
        "0978131eaf1c0059a598648f3f67ea07b5144a110467728ada852bdbbfe61813"
    )
    assert hashlib.sha256((package / "verify.py").read_bytes()).hexdigest() == (
        "9fe95165252e73355b54e2b802596e5cb00e71cf8190e4afe865011e83c7ed9b"
    )

    commands = commands_path.read_text(encoding="utf-8").splitlines()
    assert commands == [
        "python verify.py .",
        (
            "python -m scripts.verify_indirect_injection_cross_model_public "
            "data/v2/public/r2_s4_cross_model"
        ),
    ]

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert manifest["common_git"]["head"] == "109e8b52d8d31ae3562420351451a69915652be3"
    assert manifest["plan_sha256"] == (
        "85175b88742d28b09431e1b1df35a27db5cd65fbd96fc33db0bcfd899efd4152"
    )
    assert manifest["private_matrix_manifest_sha256"] == (
        "ec7b2fb6b8802b32d50933fc34b574d55c370dd88dbee4a88239d37ac51ff0b5"
    )
    assert manifest["component_manifest_sha256"] == {
        "baseline": "9271ec53e0b69d827e7a624e3666e6e53a5a9e7738450542a89e5903de768f44",
        "replication": "0495450e5134acadc564fe1ddd805f096ad939c27f2568c80caa49b366e7ed01",
    }
    assert manifest["row_count"] == 72
    assert summary["decision"] == "CONSISTENT_OBSERVATION"
    assert summary["decision_reasons"] == [
        "complete_equal_security_and_utility_observations"
    ]
    for role in ("baseline", "replication"):
        metrics = summary["summaries"][role]["metrics"]
        assert metrics["off_user_boundary_attack_success"]["numerator"] == 3
        assert metrics["off_user_boundary_attack_success"]["denominator"] == 24
        assert metrics["on_user_boundary_attack_success"]["numerator"] == 0
        assert metrics["on_user_boundary_attack_success"]["denominator"] == 24
        assert metrics["off_model_context_exposure"]["numerator"] == 7
        assert metrics["on_model_context_exposure"]["numerator"] == 0
        assert metrics["on_conditional_quarantine"]["numerator"] == 15
        assert metrics["on_conditional_quarantine"]["denominator"] == 15
        assert metrics["on_all_labeled_quarantine"]["numerator"] == 15
        assert metrics["on_all_labeled_quarantine"]["denominator"] == 28
        assert metrics["on_benign_quarantine"]["numerator"] == 0
        assert metrics["on_benign_quarantine"]["denominator"] == 32
        assert metrics["clean_utility"]["numerator"] == 12
        assert metrics["clean_utility"]["denominator"] == 12
        assert metrics["mixed_utility"]["numerator"] == 20
        assert metrics["mixed_utility"]["denominator"] == 20
        assert metrics["poison_only_utility"]["numerator"] == 4
        assert metrics["poison_only_utility"]["denominator"] == 4
        assert metrics["model_call_count"]["value"] == 68.0
        assert metrics["model_error_count"]["value"] == 0.0
        assert metrics["blocked_egress"]["value"] == 0.0
        diagnostic = summary["summaries"][role]["non_release_safety_diagnostic"]
        assert diagnostic["passed"] is True
        assert diagnostic["release_pass"] is False
    assert summary["deltas"]["model_latency_p50_ms"]["delta"] == 630.1964
    assert summary["deltas"]["model_latency_p95_ms"]["delta"] == 645.442


def test_r2_s4_task8_docs_publish_results_without_release_pass_claims() -> None:
    docs = {
        "results": (ROOT / "docs" / "security" / "r2_s4" / "01_results.md"),
        "status": ROOT / "PROJECT_STATUS.md",
        "readme": ROOT / "README.md",
        "limitations": ROOT / "docs" / "known_limitations.md",
        "journal": ROOT / "docs" / "security" / "r2_s4" / "02_engineering_journal.md",
        "handoff": ROOT / "docs" / "roadmap" / "CURRENT_EXECUTION_HANDOFF.md",
    }
    content = {name: path.read_text(encoding="utf-8") for name, path in docs.items()}

    for name, text in content.items():
        assert "CONSISTENT_OBSERVATION" in text, name
        assert "109e8b52d8d31ae3562420351451a69915652be3" in text, name
        assert "visible synthetic dev cohort" in text, name
        assert "release_pass=false" in text, name
        assert "cross-model generalization" in text, name
        assert "independent holdout" in text and "NOT RUN" in text, name
        assert "semantic judge calibration" in text and "NOT RUN" in text, name
        assert "human double review" in text and "NOT RUN" in text, name
        assert "production traffic" in text and "NOT RUN" in text, name
        assert "release PASS" not in text, name

    results = content["results"]
    for required in [
        "controller wall time: 270.2s",
        "matrix manifest SHA-256: ec7b2fb6b8802b32d50933fc34b574d55c370dd88dbee4a88239d37ac51ff0b5",
        "public manifest SHA-256: 0978131eaf1c0059a598648f3f67ea07b5144a110467728ada852bdbbfe61813",
        "packaged verify.py SHA-256: 9fe95165252e73355b54e2b802596e5cb00e71cf8190e4afe865011e83c7ed9b",
        "OFF attack 3/24; ON attack 0/24",
        "OFF context exposure 7/24; ON context exposure 0/24",
        "ON conditional quarantine 15/15; all-labeled quarantine 15/28",
        "13 labeled attack units did not reach Guard",
        "clean 12/12; mixed 20/20; poison-only 4/4",
        "baseline p50/p95 1208.1238/1379.7665ms",
        "replication p50/p95 1838.3202/2025.2085ms",
        "latency delta +630.1964/+645.442ms",
        "python -I verify.py .",
    ]:
        assert required in results

    assert "[R2-S4 Results](docs/security/r2_s4/01_results.md)" in content["readme"]
    assert "[R2-S4 public evidence](data/v2/public/r2_s4_cross_model/README.md)" in (
        content["readme"]
    )
    for name in ("results", "status", "readme"):
        assert "12 decision safety/utility observations matched" in content[name], name
        assert "component deterministic threshold diagnostic=false" in content[name], name
        assert (
            "cross-model non-release diagnostic passed=true / release_pass=false"
            in content[name]
        ), name
    for name in ("limitations", "journal", "handoff"):
        assert "12 decision safety/utility observations matched" in content[name], name
        assert "3 operational counts matched" in content[name], name
        assert "2 latency metrics differed" in content[name], name
    assert "17 safety/utility metrics were equal" not in content["readme"]
    assert "selected 17" not in content["results"]
    forbidden_metric_phrases = (
        "equal selected metrics",
        "selected metrics matched",
        "matched the selected safety/utility metrics",
        "selected safety/utility metrics on this visible synthetic dev cohort",
        "equal selected safety and utility metrics",
    )
    for name, text in content.items():
        for phrase in forbidden_metric_phrases:
            assert phrase not in text, name
    assert (
        "all-labeled quarantine 15/28 does not meet its 28/28 recall requirement"
        in results
    )
    assert "## 21. R2-S4 Task 8 current handoff" in content["handoff"]
    assert "## 20. R2-S3 measurement-only exposure ablation" in content["handoff"]


def test_r2_industrialization_plan_tracks_one_current_stage_and_ordered_candidates() -> None:
    roadmap = (
        ROOT / "docs" / "roadmap" / "r2_industrialization_execution_plan.md"
    ).read_text(encoding="utf-8")
    backlog = (ROOT / "docs" / "industrialization_backlog.md").read_text(
        encoding="utf-8"
    )
    for text in (roadmap, backlog):
        assert (
            "Current admitted implementation: "
            "R2-S6 Versioned Corpus Expansion."
        ) in text
        assert "Next candidate: reproducible minimal Linux deploy/rollback" in text
        assert "Later candidate: durable privacy-bounded telemetry" in text
        assert "not parallel approvals" in text
        for section in (
            "Trigger",
            "User value",
            "Minimal architecture",
            "Contracts",
            "Local gates",
            "Security",
            "Rollback",
            "Deferred tech-stacking",
        ):
            assert section in text
        assert "LangGraph" in text
        assert "vector DB" in text
        assert "Kubernetes" in text
        assert "multi-Agent" in text

    assert "### R2-B: Ordered lifecycle and operations" in backlog
    assert "1. Incremental index events and tombstones." not in backlog
    assert "Unranked deferred triggers" in backlog


def test_r2_s4_engineering_journal_task8_results_follow_final_review_record() -> None:
    journal = (
        ROOT / "docs" / "security" / "r2_s4" / "02_engineering_journal.md"
    ).read_text(encoding="utf-8")
    headings = re.findall(r"^## \d+\. .+$", journal, flags=re.MULTILINE)

    final_review = "## 15. 最终修复复跑与独立复审记录"
    task8_results = "## 16. Task 8 results publication and route decision"
    assert final_review in headings
    assert task8_results in headings
    assert sum(heading.startswith("## 15.") for heading in headings) == 1
    assert sum(heading.startswith("## 16.") for heading in headings) == 1
    assert headings.index(final_review) < headings.index(task8_results)


def test_r2_s4_engineering_journal_records_ci_environment_false_positive() -> None:
    journal = (
        ROOT / "docs" / "security" / "r2_s4" / "02_engineering_journal.md"
    ).read_text(encoding="utf-8")

    for fragment in (
        "GitHub Actions run `29907157287`",
        "public privacy policy found forbidden content in README.md",
        "GITHUB_REF_NAME=codex/rag-eval-system",
        "GITHUB_SHA",
        "_public_provenance_keys",
        "56 passed / 3 known warnings",
        "arbitrary secret environment value remains rejected",
    ):
        assert fragment in journal


def test_r2_s4_task8_status_backlog_and_limitations_are_current_not_prerun() -> None:
    status = (ROOT / "PROJECT_STATUS.md").read_text(encoding="utf-8")
    backlog = (ROOT / "docs" / "industrialization_backlog.md").read_text(
        encoding="utf-8"
    )
    limitations = (ROOT / "docs" / "known_limitations.md").read_text(
        encoding="utf-8"
    )
    protocol = (
        ROOT / "docs" / "security" / "r2_s4" / "00_cross_model_protocol.md"
    ).read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "one planned R2-S4 cross-model run has already executed" in status
    assert "no rerun or overwrite of the immutable R2-S4 run IDs is allowed" in status
    assert (
        "Task9 final gates, push, and CI are external delivery evidence"
        in status
    )
    assert "才允许执行一次真实跨模型命令" not in status
    assert "cross-model replication       NOT RUN AT R2-S2 CLOSEOUT" in status
    assert "cross-model replication        NOT RUN AT R2-S3 CLOSEOUT" in status

    assert "Qwen2.5/Qwen3 formal matrix NOT RUN" not in backlog
    assert "R2-S4 cross-model replication                  COMPLETE WITH OBSERVATIONS" in backlog
    assert "R2-S4 dev matrix COMPLETE / CONSISTENT_OBSERVATION" in backlog
    assert (
        "independent package / holdout / blind review / calibration  NOT RUN"
        in backlog
    )

    assert "## 6. historical R2-S3 boundary at R2-S3 cutoff" in limitations
    normalized_limitations = " ".join(limitations.split())
    assert (
        "current R2-S4 Task 8 below supersedes only the old "
        "cross-model-replication NOT RUN line"
    ) in normalized_limitations
    assert normalized_limitations.count(
        "current R2-S4 Task 8 below supersedes only the old "
        "cross-model-replication NOT RUN line"
    ) == 1
    assert (
        "R2-S4 cross-model dev observation is COMPLETE WITH OBSERVATIONS"
        in limitations
    )
    assert "cross-model replication remain `NOT RUN`" not in limitations
    assert "cross-model replication are `NOT RUN`" not in limitations
    assert (
        "manual no-other-Ollama-client check remains required before any future run"
        in limitations
    )
    assert "Operators must not delete, rotate, replace, redirect, or clean" in limitations
    assert "R2_S4_EVALUATION_LOCK_DIR" in limitations
    assert "Non-cooperating post-yield lock pathname replacement remains outside" in limitations

    assert "actual tracked R2-S4 public package is `NOT CREATED`" not in protocol
    assert "pre-Task8 export gate" in protocol
    assert "[R2-S4 Results](01_results.md)" in protocol
    assert "## 11. 已消耗的一次性执行记录与只读验证命令" in protocol
    assert "DO NOT RUN the consumed model command again" in protocol
    assert "DO NOT RUN the consumed export command again" in protocol
    assert "Only the verifier commands below remain runnable" in protocol

    assert "cross-model replication is NOT RUN at R2-S3 cutoff" in readme
    assert "[R2-S4 public evidence](data/v2/public/r2_s4_cross_model/README.md)" in readme
    assert "pre-run exact-HEAD review" in status


def test_r2_s5_execution_plan_has_deep_identity_contract_and_quantified_gates() -> None:
    roadmap = (
        ROOT / "docs" / "roadmap" / "r2_industrialization_execution_plan.md"
    ).read_text(encoding="utf-8")
    backlog = (ROOT / "docs" / "industrialization_backlog.md").read_text(
        encoding="utf-8"
    )

    required_fragments = (
        "Bearer -> pinned JWT verifier -> Principal -> deterministic UserContext -> existing AccessPolicy",
        "chat, trace, metrics, and feedback",
        "liveness remains public",
        "readiness remains low-sensitivity",
        "invalid signature",
        "alg=none",
        "algorithm confusion",
        "expired token",
        "nbf in future",
        "unknown kid",
        "wrong issuer",
        "wrong audience",
        "missing tenant claim",
        "missing subject claim",
        "oversized token",
        "JWKS outage",
        "key cache and rotation fail closed",
        "removes and rejects body-supplied `user_context`",
        "Trace and metrics access require",
        "feedback uses the authenticated user principal",
        "100% negative tokens return 401/403 before retrieval/model",
        "retrieval/model counters stay zero",
        "0/N unauthorized docs, citations, and traces",
        "0 token/claim leaks",
        "1000 warm verifications p95 <= 10ms",
        "reported hardware",
        "full historical/security/public audit exact-SHA Linux CI",
        "Rollback must not restore public body-supplied identity",
        "real IdP integration remains outside the local contract",
    )
    for text in (roadmap, backlog):
        normalized = " ".join(text.split())
        for fragment in required_fragments:
            assert fragment in normalized


def test_r2_s4_audit_counts_are_labeled_by_gate_phase() -> None:
    documents = {
        "results": ROOT / "docs" / "security" / "r2_s4" / "01_results.md",
        "status": ROOT / "PROJECT_STATUS.md",
        "readme": ROOT / "README.md",
        "backlog": ROOT / "docs" / "industrialization_backlog.md",
        "handoff": ROOT / "docs" / "roadmap" / "CURRENT_EXECUTION_HANDOFF.md",
    }
    contents = {
        name: path.read_text(encoding="utf-8")
        for name, path in documents.items()
    }

    for name, text in contents.items():
        if "473/0" in text:
            assert "exact-run pre-gate audit 473/0" in text, name
        if "473 candidates / 0 findings" in text:
            assert (
                "exact-run pre-gate audit 473 candidates / 0 findings" in text
            ), name

    assert "Task8 docs wave audit 483/0" in contents["results"]
    assert (
        "Task8 docs wave audit 483/0; final delivery evidence is established "
        "by exact-HEAD gates, Git, and GitHub Actions"
    ) in contents["status"]
    assert "Task8 docs wave audit 483/0" in contents["handoff"]
    assert "final Task9 gate will recompute" not in "\n".join(contents.values())


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


def test_public_audit_allows_only_frozen_hidden_dataset_metadata(
    tmp_path: Path,
) -> None:
    from scripts.audit_public_repo import audit_repository

    _write_minimal_complete_security_corpus(tmp_path)
    allowed = (
        "data/v2/public/lifecycle_g10_v3/dataset/.private/lifecycle/"
        "g10-expanded-lifecycle-v4/manifest.json"
    )
    unexpected = (
        "data/v2/public/lifecycle_g10_v3/dataset/.private/lifecycle/"
        "g10-expanded-lifecycle-v4/unbound.json"
    )
    for relative in (allowed, unexpected):
        path = tmp_path / Path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

    report = audit_repository(
        tmp_path,
        candidate_files=[allowed, unexpected],
    )
    forbidden = {
        item.path for item in report.findings if item.code == "forbidden_path"
    }

    assert allowed not in forbidden
    assert unexpected in forbidden


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

    _write_minimal_complete_security_corpus(tmp_path)
    case_id = "r2s1-test-business-sop-action-language-1"
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

    _write_minimal_complete_security_corpus(tmp_path)
    dataset = (
        tmp_path / "data" / "v2" / "security" / "indirect_injection_test_v1.json"
    )
    dataset_payload = json.loads(dataset.read_text(encoding="utf-8"))
    dataset_payload["cases"][0]["question"] = "FROZEN_R2_S3_SOURCE_VALUE"
    dataset.write_text(json.dumps(dataset_payload), encoding="utf-8")
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

    _write_minimal_complete_security_corpus(tmp_path)
    security_root = tmp_path / "data" / "v2" / "security"
    dataset = security_root / "indirect_injection_dev_v1.json"
    dataset_payload = json.loads(dataset.read_text(encoding="utf-8"))
    dataset_payload["cases"][0]["question"] = "DEV_ONLY_QUESTION_NEVER_PUBLIC"
    benign_case = next(
        case for case in dataset_payload["cases"] if case["benign_unit_ids"]
    )
    original_unit_id = benign_case["benign_unit_ids"][0]
    benign_case["benign_unit_ids"][0] = "benign-unit-private-001"
    outcome = benign_case["expected_guard_outcome"].pop(original_unit_id)
    benign_case["expected_guard_outcome"]["benign-unit-private-001"] = outcome
    dataset.write_text(json.dumps(dataset_payload), encoding="utf-8")
    fixture = security_root / "fixtures_v1" / "dev" / "manifest.json"
    fixture_payload = json.loads(fixture.read_text(encoding="utf-8"))
    aligned_fixture_case = next(
        case
        for case in fixture_payload["cases"]
        if case["case_id"] == benign_case["case_id"]
    )
    aligned_candidate = next(
        candidate
        for candidate in aligned_fixture_case["candidates"]
        if candidate["matched_unit_id"] == original_unit_id
    )
    aligned_candidate["matched_unit_id"] = "benign-unit-private-001"
    fixture_payload["cases"][0]["candidates"][0]["section_path"][0] = (
        "OPEN_SECTION_PRIVATE_PATH"
    )
    fixture.write_text(json.dumps(fixture_payload), encoding="utf-8")
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
    _write_minimal_complete_security_corpus(tmp_path)

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


def test_r2_s3_section_twenty_is_the_only_current_handoff_breakpoint() -> None:
    handoff = (
        ROOT / "docs" / "roadmap" / "CURRENT_EXECUTION_HANDOFF.md"
    ).read_text(encoding="utf-8")
    current_headings = tuple(
        line
        for line in handoff.splitlines()
        if line.startswith("## ") and "当前精确断点" in line
    )
    historical = handoff.split("## 20.", 1)[0]

    assert current_headings == (
        "## 20. R2-S3 measurement-only exposure ablation 当前精确断点",
    )
    for section in ("## 8.", "## 15.", "## 16.", "## 17.", "## 18.", "## 19."):
        heading = next(
            line for line in handoff.splitlines() if line.startswith(section)
        )
        assert "历史" in heading or "已取代" in heading
    for contradictory in (
        "没有授权 commit",
        "未授权 commit/push",
        "必须停止在 E4",
        "必须停止在 E6",
    ):
        assert contradictory not in historical
    assert "433 PASSED / 5 PLATFORM SKIPS" not in handoff


def test_r2_s3_current_identity_blocks_carry_complete_five_hash_chain() -> None:
    handoff = (
        ROOT / "docs" / "roadmap" / "CURRENT_EXECUTION_HANDOFF.md"
    ).read_text(encoding="utf-8")
    journal = (
        ROOT / "docs" / "security" / "r2_s3" / "02_engineering_journal.md"
    ).read_text(encoding="utf-8")
    plan = (
        ROOT
        / "docs"
        / "superpowers"
        / "plans"
        / "2026-07-21-r2-s3-exposure-aware-ablation.md"
    ).read_text(encoding="utf-8")
    blocks = (
        handoff.split("## 20.", 1)[1].split("```text", 1)[1].split("```", 1)[0],
        journal.split("The accepted evidence identity is:", 1)[1]
        .split("```text", 1)[1]
        .split("```", 1)[0],
        plan.split("## Final Fix-Wave Acceptance Addendum", 1)[1]
        .split("```text", 1)[1]
        .split("```", 1)[0],
    )
    required_hashes = (
        "3fe51ea7e404d7d1c09711b14f422b92b2474df7148e4f15df1e949081f5586e",
        "4c8cfb6ad826fc1ca9c24afb0157129df661f3cd463aa3448ec161c0608c5f1f",
        "09fda4aa81d15757e8de7cadec32e057a1c01d23a5b646dbcd5c0f9ae9038033",
        "d7fe9332953cc44ba3f517bb03d4074b293b821461240d30fc384d67256a4b88",
        "dbe814605220058c0bf2453ee1cac0450253bd788b64f9979ab1eb77c2413897",
    )

    for block in blocks:
        for expected_hash in required_hashes:
            assert expected_hash in block


def test_r2_s3_task_seven_is_non_executable_superseded_history() -> None:
    plan = (
        ROOT
        / "docs"
        / "superpowers"
        / "plans"
        / "2026-07-21-r2-s3-exposure-aware-ablation.md"
    ).read_text(encoding="utf-8")
    task_seven = plan.split("### Task 7:", 1)[1].split("### Task 8:", 1)[0]
    task_heading = plan.split("### Task 7:", 1)[1].splitlines()[0]

    assert "SUPERSEDED" in task_heading
    assert "NON-EXECUTABLE" in task_heading
    assert "docs/security/r2_s3/00_exposure_ablation_protocol.md" in task_seven
    assert "r2-s3-dev-exposure-20260721-04" in task_seven
    assert "-m scripts.eval_indirect_injection_exposure" not in task_seven
    assert "-m scripts.export_indirect_injection_exposure_public" not in task_seven


def test_consumed_exposure_evaluator_commands_are_not_runnable() -> None:
    protocol = (
        ROOT
        / "docs"
        / "security"
        / "r2_s3"
        / "00_exposure_ablation_protocol.md"
    ).read_text(encoding="utf-8")
    operator_section = protocol.split("## 8. Exact Operator Commands", 1)[1]

    assert "ARCHIVAL, NON-EXECUTABLE RECORD" in operator_section
    assert "-m scripts.eval_indirect_injection_exposure" not in operator_section
    assert "r2-s3-dev-exposure-20260721-04" in operator_section
    assert "-m scripts.verify_indirect_injection_exposure" in operator_section
    assert "-m scripts.export_indirect_injection_exposure_public" in operator_section


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
    assert "'.tmp_r2_s3_public_' + [guid]::NewGuid().ToString('D')" in protocol
    assert "if (Test-Path -LiteralPath $stagingRoot)" in protocol
    assert "--output-root $stagingRoot" in protocol
    assert "$stagedPackage = Join-Path $stagingRoot 'r2_s3_exposure'" in protocol
    assert "scripts.verify_indirect_injection_exposure_public $stagedPackage" in protocol
    assert "$source = $stagedPackage" in protocol
    assert ".tmp_r2_s3_final_public_04" not in protocol
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".tmp_r2_s3_public_????????-????-????-????-????????????/" in ignore
    replacement_boundary = (
        "After mechanically replacing the exact eight tracked files"
    )
    assert replacement_boundary in protocol
    post_replacement = protocol.split(replacement_boundary, 1)[1]
    assert (
        "scripts.verify_indirect_injection_exposure_public `\n"
        "  data\\v2\\public\\r2_s3_exposure"
    ) in post_replacement
    interpreter_bootstrap = """$venvPython = Join-Path $repo '.venv\\Scripts\\python.exe'
if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
  $python = (Resolve-Path -LiteralPath $venvPython).Path
} else {
  $python = (
    Get-Command python -CommandType Application -ErrorAction Stop |
      Select-Object -First 1
  ).Source
}"""
    assert protocol.count(interpreter_bootstrap) == 2
    documented = protocol.split(start_marker, 1)[1].split(end_marker, 1)[0]
    match = re.search(r"```powershell\s*\n(.*?)\n```", documented, re.DOTALL)
    assert match is not None
    command = match.group(1)
    assert "$venvPython = Join-Path $repo '.venv\\Scripts\\python.exe'" in command
    assert "Get-Command python -CommandType Application -ErrorAction Stop" in command
    assert "Select-Object -First 1" in command
    assert command.index("$venvPython = Join-Path") < command.index(
        "Push-Location"
    )

    if os.name != "nt":
        pytest.skip("Windows PowerShell execution is unavailable on this host")

    staged_package = tmp_path / "staged" / "r2_s3_exposure"
    shutil.copytree(
        ROOT / "data" / "v2" / "public" / "r2_s3_exposure",
        staged_package,
    )
    powershell_path = str(staged_package).replace("'", "''")
    command = command.replace(
        "$source = $stagedPackage",
        f"$source = '{powershell_path}'",
    )
    command = command.replace(
        "$venvPython = Join-Path $repo '.venv\\Scripts\\python.exe'",
        "$venvPython = Join-Path $repo '.ci-missing-venv\\Scripts\\python.exe'",
    )

    environment = os.environ.copy()
    environment["TEMP"] = str(tmp_path)
    environment["TMP"] = str(tmp_path)
    environment["PATH"] = (
        str(Path(sys.executable).parent)
        + os.pathsep
        + environment.get("PATH", "")
    )
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


def test_r2_s4_backlog_remote_ci_claims_are_exact_head_scoped() -> None:
    backlog = (ROOT / "docs" / "industrialization_backlog.md").read_text(
        encoding="utf-8"
    )

    assert (
        "| P1 | Remote CI evidence for the current R2-S4 exact HEAD |"
        in backlog
    )
    assert "Historical `9607e55` evidence applies only to that commit." in backlog
    assert "- current R2-S4 exact HEAD remote CI passed;" in backlog


def test_remote_ci_history_is_not_presented_as_current_r2_s5_evidence() -> None:
    status = (ROOT / "PROJECT_STATUS.md").read_text(encoding="utf-8")
    limitations = (ROOT / "docs" / "known_limitations.md").read_text(
        encoding="utf-8"
    )

    for content in (status, limitations):
        assert "9607e55" in content
        assert "9fcb304" in content
        assert "不覆盖当前 R2-S5 candidate exact HEAD" in content
    assert "历史 E7 代码候选 `9607e55" in status
    assert "当前功能分支候选" not in status


def test_r2_s3_current_docs_bind_regenerated_v2_evidence() -> None:
    package = ROOT / "data" / "v2" / "public" / "r2_s3_exposure"
    manifest_path = package / "manifest.redacted.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    accepted_run_id = "r2-s3-dev-exposure-20260721-04"
    source_live_manifest_sha256 = (
        "3fe51ea7e404d7d1c09711b14f422b92b2474df7148e4f15df1e949081f5586e"
    )
    private_manifest_sha256 = (
        "4c8cfb6ad826fc1ca9c24afb0157129df661f3cd463aa3448ec161c0608c5f1f"
    )
    public_manifest_sha256 = (
        "09fda4aa81d15757e8de7cadec32e057a1c01d23a5b646dbcd5c0f9ae9038033"
    )
    verifier_sha256 = (
        "dbe814605220058c0bf2453ee1cac0450253bd788b64f9979ab1eb77c2413897"
    )
    evaluator_sha256 = (
        "d7fe9332953cc44ba3f517bb03d4074b293b821461240d30fc384d67256a4b88"
    )
    summary_sha256 = (
        "115d9f1e973c1341e4059d4c4bd28615e31a76104922e10ab877dbfbf5d2e50c"
    )
    per_unit_sha256 = (
        "d747d895c26450dd53c9a61623f3ba9572eaf25d0e292775b2f5ea3eedd0bb98"
    )
    verification_input_witness_sha256 = (
        "e1910a458b3541abc47d515cf46a3b5ab6daa614e971e2f701097ebdce67befc"
    )
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

    _assert_exact_public_exposure_package_tree(
        package,
        R2_S3_PUBLIC_PACKAGE_PATHS,
    )
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == public_manifest_sha256
    assert hashlib.sha256((package / "verify.py").read_bytes()).hexdigest() == verifier_sha256
    assert (package / "source_run.sha256").read_text(encoding="utf-8") == (
        f"{private_manifest_sha256}  manifest.json\n"
    )
    assert manifest["schema_version"] == (
        "indirect_injection_exposure_public_manifest_v2"
    )
    assert manifest["source_private_run_id"] == accepted_run_id
    assert manifest["source_private_manifest_sha256"] == private_manifest_sha256
    assert manifest["source"]["manifest_sha256"] == source_live_manifest_sha256
    assert manifest["verifier_sha256"] == verifier_sha256
    assert hashlib.sha256(
        (ROOT / "app" / "evaluation" / "indirect_injection_exposure.py").read_bytes()
    ).hexdigest() == evaluator_sha256
    checksums = {
        filename: sha256
        for sha256, filename in (
            line.split("  ", 1)
            for line in (package / "checksums.sha256")
            .read_text(encoding="utf-8")
            .splitlines()
        )
    }
    assert checksums["manifest.redacted.json"] == public_manifest_sha256
    assert checksums["verify.py"] == verifier_sha256
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

    result_document = contents["docs/security/r2_s3/01_results.md"]
    for trusted_binding in (
        source_live_manifest_sha256,
        private_manifest_sha256,
        public_manifest_sha256,
        verifier_sha256,
        evaluator_sha256,
        summary_sha256,
        per_unit_sha256,
        verification_input_witness_sha256,
    ):
        assert trusted_binding in result_document

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

    status = contents["PROJECT_STATUS.md"]
    assert "focused `457 passed / 10 skipped / 3 known warnings`" in status
    assert "full `1395 passed / 13 skipped / 3 known warnings`" in status
    assert (
        "platform-dependent symlink/junction variants unavailable on this host"
        in status
    )
    assert "public audit `454 candidates / 0 findings`" in status
    assert required_boundary in status
    assert "433 passed / 5 platform skips" not in status
    r2_s2_status = status.split("## 9. R2-S2 当前状态", 1)[1].split(
        "## 10. R2-S3 当前状态", 1
    )[0]
    r2_s3_status = status.split("## 10. R2-S3 当前状态", 1)[1]
    expected_r2_s2_lines = (
        "historical R2-S2/R2-S3 full regression only    "
        "1395 PASSED / 13 SKIPPED / 3 KNOWN WARNINGS; not a current R2-S4 HEAD gate",
        "historical R2-S2/R2-S3 public audit only       "
        "454 CANDIDATES / 0 FINDINGS; not a current R2-S4 HEAD gate",
    )
    missing_r2_s2_lines = tuple(
        line for line in expected_r2_s2_lines if line not in r2_s2_status
    )
    assert not missing_r2_s2_lines, (
        f"missing exact historical R2-S2 lines: {missing_r2_s2_lines}"
    )
    assert (
        "historical R2-S3 focused / full pytest           "
        "457 passed / 10 skipped / 3 warnings; "
        "1395 passed / 13 skipped / 3 warnings; not a current R2-S4 HEAD gate"
    ) in r2_s3_status
    assert (
        "historical R2-S3 compile / pip / public audit   "
        "CLEAN / CLEAN / 454 candidates / 0 findings; "
        "not a current R2-S4 HEAD gate"
    ) in r2_s3_status
    assert f"push / remote CI                                 {required_boundary}" in (
        r2_s3_status
    )
    for obsolete_current_value in (
        "1316 PASSED / 5 SKIPPED",
        "451 CANDIDATES / 0 FINDINGS",
        "376 / 1316 PASSED",
        "CLEAN / CLEAN / 451-0",
        "PROHIBITED / DEFERRED PENDING SYNTHESIS",
    ):
        assert obsolete_current_value not in status


def test_exact_public_exposure_package_tree_rejects_nested_extra_path(
    tmp_path: Path,
) -> None:
    package = tmp_path / "r2_s3_exposure"
    package.mkdir()
    for relative in R2_S3_PUBLIC_PACKAGE_PATHS:
        (package / relative).write_text("fixture\n", encoding="utf-8")
    nested = package / "debug" / "raw.json"
    nested.parent.mkdir()
    nested.write_text('{"private":true}\n', encoding="utf-8")

    with pytest.raises(AssertionError):
        _assert_exact_public_exposure_package_tree(
            package,
            R2_S3_PUBLIC_PACKAGE_PATHS,
        )
