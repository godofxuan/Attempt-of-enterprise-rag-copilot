from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import unicodedata
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence
from urllib.parse import unquote

from pydantic import ValidationError

from app.evaluation.indirect_injection_sensitive_values import (
    SecuritySensitiveValueCorpus,
    collect_security_sensitive_values,
)
from app.evaluation.indirect_injection_contracts import (
    FixtureManifest,
    IndirectInjectionDataset,
    validate_dataset_fixture_alignment,
)
from app.evaluation.public_snapshot import PublicDemoSnapshot


MAX_PUBLIC_FILE_BYTES = 2 * 1024 * 1024
_PUBLIC_SNAPSHOT_PATH = "data/v2/public/demo_snapshot.json"
_REQUIRED_SECURITY_CORPUS_SOURCES = (
    ("data/v2/security/indirect_injection_dev_v1.json", False, "dev"),
    ("data/v2/security/indirect_injection_test_v1.json", False, "test"),
    ("data/v2/security/fixtures_v1/dev/manifest.json", True, "dev"),
    ("data/v2/security/fixtures_v1/test/manifest.json", True, "test"),
)
_SENSITIVE_PUBLIC_EVIDENCE_PREFIXES = (
    "data/v2/public/r2_s1_d7/",
    "data/v2/public/r2_s3_exposure/",
)
_PUBLIC_CASE_ID_ALLOWED_PREFIXES = ("data/v2/public/r2_s1_d7/",)
_PUBLIC_PNG_DIMENSIONS = {
    "docs/assets/ask.png": (1440, 1000),
    "docs/assets/trace.png": (1440, 1000),
    "docs/assets/evaluation.png": (1440, 1000),
}
_PUBLIC_TEXT_SURFACES = frozenset(
    {
        "README.md",
        "PROJECT_STATUS.md",
        "data/v2/public/demo_snapshot.json",
        "docs/architecture.md",
        "docs/known_limitations.md",
        "docs/demo_runbook.md",
        "docs/industrialization_backlog.md",
        "docs/assets/README.md",
    }
)
_FORBIDDEN_PREFIXES = (
    "data/generated/",
    "data/v2/generated/",
    "data/indexes/",
    "data/indexes_v2/",
    "data/parsed_docs/",
    "data/eval_outputs/",
    "data/eval_runs/",
    "data/load_runs/",
    "data/logs/",
    "eval_runs/",
    "exposure_runs/",
    "holdout_submissions/",
    "load_runs/",
    "logs/",
    "security_runs/",
)
_ALLOWED_RUNTIME_MARKERS = {
    "data/indexes/.gitkeep",
    "data/parsed_docs/.gitkeep",
}
_FORBIDDEN_RUNTIME_SUFFIXES = {".db", ".log", ".sqlite", ".sqlite3"}
_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----"
)
_TOKEN_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
)
_PRIVATE_KEY_BYTES_PATTERN = re.compile(
    rb"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----"
)
_TOKEN_BYTES_PATTERNS = (
    re.compile(rb"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(rb"\bghp_[A-Za-z0-9]{30,}\b"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
)
_EMAIL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9._%+-])"
    r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})"
)
_WINDOWS_PATH_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9])[A-Z]:\\[^\s`\"')>]+"
)
_POSIX_USER_PATH_PATTERN = re.compile(r"/(?:Users|home)/[^/\s`\"')>]+")
_MARKDOWN_LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
_ENVIRONMENT_REFERENCE_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?:HOME|USERPROFILE|HTTP_PROXY|HTTPS_PROXY)"
    r"(?![A-Za-z0-9_])"
)
_PRIVATE_RUNTIME_REFERENCE_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9_.-])(?:security_runs|exposure_runs|"
    r"holdout_submissions|data[\\/]"
    r"(?:indexes(?:_v2)?|parsed_docs|eval_outputs|eval_runs|load_runs|logs))"
    r"(?:[\\/]|$)"
)
_CREDENTIAL_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?P<key>api[_-]?key|access[_-]?token|secret|password|authorization)"
    r"\b\s*[:=]\s*[\"']?(?P<value>[^\s\"',;]{4,})"
)
_SAFE_CREDENTIAL_VALUE_MARKERS = (
    "dummy",
    "example",
    "fake",
    "never-show",
    "not-real",
    "placeholder",
    "redacted",
    "should-not-be-public",
    "test",
)
_SYSTEM_PROMPT_FRAGMENTS = (
    "You are a grounded enterprise knowledge-base answer generator operating ",
    "你是企业知识库 RAG 的证据充分性判定器。",
    "你是企业知识库助手。",
)


@dataclass(frozen=True, order=True)
class AuditFinding:
    code: str
    path: str
    detail: str


@dataclass(frozen=True)
class AuditReport:
    candidate_files: tuple[str, ...]
    findings: tuple[AuditFinding, ...]

    @property
    def passed(self) -> bool:
        return not self.findings


def audit_repository(
    root: Path,
    *,
    candidate_files: Iterable[str | Path] | None = None,
) -> AuditReport:
    root = Path(root).resolve()
    candidates = (
        _git_candidate_files(root)
        if candidate_files is None
        else tuple(str(path) for path in candidate_files)
    )
    normalized: list[str] = []
    findings: list[AuditFinding] = []
    frozen_security_values, corpus_findings = _load_frozen_security_values(root)
    findings.extend(corpus_findings)
    local_identity_values = _local_identity_values()
    for candidate in candidates:
        try:
            relative = _normalize_candidate(candidate)
        except ValueError:
            findings.append(
                AuditFinding(
                    code="unsafe_candidate_path",
                    path=str(candidate),
                    detail="candidate path escapes the repository root",
                )
            )
            continue
        normalized.append(relative)

    for relative in sorted(set(normalized)):
        findings.extend(
            _audit_one(
                root,
                relative,
                frozen_security_values=frozen_security_values,
                local_identity_values=local_identity_values,
            )
        )
    return AuditReport(
        candidate_files=tuple(sorted(set(normalized))),
        findings=tuple(sorted(set(findings))),
    )


def _git_candidate_files(root: Path) -> tuple[str, ...]:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise RuntimeError("unable to enumerate Git candidate files")
    try:
        output = completed.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("Git candidate paths are not valid UTF-8") from exc
    return tuple(item for item in output.split("\0") if item)


def _normalize_candidate(candidate: str) -> str:
    value = candidate.replace("\\", "/")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError("unsafe candidate path")
    return path.as_posix()


def _audit_one(
    root: Path,
    relative: str,
    *,
    frozen_security_values: SecuritySensitiveValueCorpus,
    local_identity_values: tuple[str, ...],
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    if _is_forbidden_path(relative):
        findings.append(
            AuditFinding(
                code="forbidden_path",
                path=relative,
                detail="local or private artifact is a public candidate",
            )
        )

    unresolved = root / Path(*PurePosixPath(relative).parts)
    if unresolved.is_symlink():
        findings.append(
            AuditFinding(
                code="symlink_candidate",
                path=relative,
                detail="symbolic links require manual public review",
            )
        )
        return findings
    path = unresolved.resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return [
            AuditFinding(
                code="unsafe_candidate_path",
                path=relative,
                detail="candidate resolves outside the repository root",
            )
        ]
    if not path.exists():
        findings.append(
            AuditFinding(
                code="missing_candidate",
                path=relative,
                detail="Git candidate is missing from the working tree",
            )
        )
        return findings
    if not path.is_file():
        return findings

    size = path.stat().st_size
    if size > MAX_PUBLIC_FILE_BYTES:
        findings.append(
            AuditFinding(
                code="file_too_large",
                path=relative,
                detail=f"candidate exceeds {MAX_PUBLIC_FILE_BYTES} bytes",
            )
        )
        return findings
    content = path.read_bytes()
    if _PRIVATE_KEY_BYTES_PATTERN.search(content):
        findings.append(
            AuditFinding(
                code="private_key",
                path=relative,
                detail="private key marker detected",
            )
        )
    if any(pattern.search(content) for pattern in _TOKEN_BYTES_PATTERNS):
        findings.append(
            AuditFinding(
                code="credential_token",
                path=relative,
                detail="high-confidence credential token shape detected",
            )
        )

    text = _decode_text(content)

    if text is not None and _PRIVATE_KEY_PATTERN.search(text):
        findings.append(
            AuditFinding(
                code="private_key",
                path=relative,
                detail="private key marker detected",
            )
        )
    if text is not None and any(
        pattern.search(text) for pattern in _TOKEN_PATTERNS
    ):
        findings.append(
            AuditFinding(
                code="credential_token",
                path=relative,
                detail="high-confidence credential token shape detected",
            )
        )
    if text is not None and _contains_non_example_email(text):
        findings.append(
            AuditFinding(
                code="non_example_email",
                path=relative,
                detail="non-example email address detected",
            )
        )

    if relative == _PUBLIC_SNAPSHOT_PATH:
        if text is None:
            valid_snapshot = False
        else:
            try:
                PublicDemoSnapshot.model_validate_json(text)
                valid_snapshot = True
            except ValidationError:
                valid_snapshot = False
        if not valid_snapshot:
            findings.append(
                AuditFinding(
                    code="invalid_public_snapshot",
                    path=relative,
                    detail="public snapshot does not satisfy its strict schema",
                )
            )

    expected_dimensions = _PUBLIC_PNG_DIMENSIONS.get(relative)
    if expected_dimensions is not None:
        dimensions = _png_dimensions(content)
        if dimensions != expected_dimensions:
            findings.append(
                AuditFinding(
                    code="invalid_png",
                    path=relative,
                    detail=(
                        "public screenshot is not a valid PNG with the "
                        "required dimensions"
                    ),
                )
            )

    is_sensitive_public_evidence = relative.startswith(
        _SENSITIVE_PUBLIC_EVIDENCE_PREFIXES
    )
    is_seeded_test_fixture = relative.startswith("tests/")
    requires_portable_paths = not is_seeded_test_fixture
    if requires_portable_paths and text is not None:
        if _WINDOWS_PATH_PATTERN.search(text) or _POSIX_USER_PATH_PATTERN.search(
            text
        ):
            findings.append(
                AuditFinding(
                    code="absolute_user_path",
                    path=relative,
                    detail="machine-specific absolute path detected",
                )
            )
    generic_credential_surface = (
        not is_sensitive_public_evidence
        and not is_seeded_test_fixture
        and not relative.startswith(("docs/", ".superpowers/"))
    ) or relative in _PUBLIC_TEXT_SURFACES
    if (
        generic_credential_surface
        and text is not None
        and _contains_unsafe_credential_assignment(text)
    ):
        findings.append(
            AuditFinding(
                code="credential_assignment",
                path=relative,
                detail="literal credential-like assignment detected",
            )
        )
    if is_sensitive_public_evidence and text is not None:
        include_case_ids = not relative.startswith(
            _PUBLIC_CASE_ID_ALLOWED_PREFIXES
        )
        findings.extend(
            _public_sensitive_evidence_findings(
                relative,
                text,
                frozen_security_values=frozen_security_values.values(
                    include_case_ids=include_case_ids
                ),
                local_identity_values=local_identity_values,
            )
        )
    if path.suffix.casefold() == ".md" and text is not None:
        findings.extend(_missing_link_findings(root, path, relative, text))
    return findings


def _is_forbidden_path(relative: str) -> bool:
    path = PurePosixPath(relative)
    name = path.name
    if relative in _ALLOWED_RUNTIME_MARKERS:
        return False
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return True
    if ".private" in path.parts:
        return True
    if relative == ".streamlit/secrets.toml":
        return True
    if path.suffix.casefold() in _FORBIDDEN_RUNTIME_SUFFIXES:
        return True
    return any(relative.startswith(prefix) for prefix in _FORBIDDEN_PREFIXES)


def _decode_text(content: bytes) -> str | None:
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    elif content.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    else:
        encoding = "utf-8"
    try:
        return content.decode(encoding)
    except UnicodeDecodeError:
        return None


def _png_dimensions(content: bytes) -> tuple[int, int] | None:
    if not content.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    offset = 8
    dimensions: tuple[int, int] | None = None
    first_chunk = True
    while offset + 12 <= len(content):
        length = int.from_bytes(content[offset : offset + 4], "big")
        chunk_type = content[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if chunk_end > len(content):
            return None
        data = content[offset + 8 : offset + 8 + length]
        expected_crc = int.from_bytes(
            content[offset + 8 + length : chunk_end],
            "big",
        )
        actual_crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            return None
        if first_chunk:
            if chunk_type != b"IHDR" or length != 13:
                return None
            width = int.from_bytes(data[0:4], "big")
            height = int.from_bytes(data[4:8], "big")
            if width <= 0 or height <= 0:
                return None
            dimensions = (width, height)
            first_chunk = False
        if chunk_type == b"IEND":
            if length != 0 or chunk_end != len(content):
                return None
            return dimensions
        offset = chunk_end
    return None


def _contains_non_example_email(text: str) -> bool:
    for match in _EMAIL_PATTERN.finditer(text):
        domain = match.group(1).casefold()
        if domain in {"example.com", "example.org", "example.net"}:
            continue
        if domain.endswith(".invalid"):
            continue
        return True
    return False


def _contains_unsafe_credential_assignment(text: str) -> bool:
    for match in _CREDENTIAL_ASSIGNMENT_PATTERN.finditer(text):
        value = match.group("value").strip().casefold()
        if value == "ollama" or any(
            marker in value for marker in _SAFE_CREDENTIAL_VALUE_MARKERS
        ):
            continue
        if value.startswith(
            (
                "$",
                "<",
                "config.",
                "env.",
                "os.",
                "self.",
                "settings.",
            )
        ):
            continue
        if set(value) <= {"*", "x"}:
            continue
        return True
    return False


def _load_frozen_security_values(
    root: Path,
) -> tuple[SecuritySensitiveValueCorpus, tuple[AuditFinding, ...]]:
    datasets: dict[str, tuple[str, IndirectInjectionDataset]] = {}
    fixture_manifests: dict[str, tuple[str, FixtureManifest]] = {}
    findings: list[AuditFinding] = []
    for relative, is_fixture_manifest, expected_split in (
        _REQUIRED_SECURITY_CORPUS_SOURCES
    ):
        value, finding = _load_required_security_corpus_source(
            root,
            relative,
            is_fixture_manifest=is_fixture_manifest,
        )
        if finding is not None:
            findings.append(finding)
            continue
        if value is None:
            findings.append(
                _security_corpus_finding(
                    relative,
                    "required security corpus split is missing",
                )
            )
            continue
        if value.split != expected_split:
            findings.append(
                _security_corpus_finding(
                    relative,
                    "security corpus split does not match its source path",
                )
            )
            continue
        if is_fixture_manifest and isinstance(value, FixtureManifest):
            target = fixture_manifests
        elif not is_fixture_manifest and isinstance(value, IndirectInjectionDataset):
            target = datasets
        else:
            findings.append(
                _security_corpus_finding(
                    relative,
                    "security corpus type does not match its source path",
                )
            )
            continue
        if value.split in target:
            previous_relative = target[value.split][0]
            detail = "security corpus contains a duplicate split"
            findings.append(_security_corpus_finding(previous_relative, detail))
            findings.append(_security_corpus_finding(relative, detail))
            continue
        target[value.split] = (relative, value)
    if findings:
        return SecuritySensitiveValueCorpus((), ()), tuple(findings)

    for split in ("dev", "test"):
        dataset_relative, dataset = datasets[split]
        fixture_relative, fixture_manifest = fixture_manifests[split]
        try:
            validate_dataset_fixture_alignment(dataset, fixture_manifest)
        except ValueError:
            detail = f"security dataset and fixture are not aligned for {split} split"
            findings.append(_security_corpus_finding(dataset_relative, detail))
            findings.append(_security_corpus_finding(fixture_relative, detail))
    if findings:
        return SecuritySensitiveValueCorpus((), ()), tuple(findings)

    return (
        collect_security_sensitive_values(
            datasets=(datasets["dev"][1], datasets["test"][1]),
            fixture_manifests=(
                fixture_manifests["dev"][1],
                fixture_manifests["test"][1],
            ),
        ),
        (),
    )


def _load_required_security_corpus_source(
    root: Path,
    relative: str,
    *,
    is_fixture_manifest: bool,
) -> tuple[
    IndirectInjectionDataset | FixtureManifest | None,
    AuditFinding | None,
]:
    path = root / relative
    if not path.is_file():
        return None, _security_corpus_finding(
            relative,
            "required security corpus file is missing",
        )
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError:
        return None, _security_corpus_finding(
            relative,
            "security corpus file is not valid UTF-8",
        )
    except OSError:
        return None, _security_corpus_finding(
            relative,
            "security corpus file is unreadable",
        )
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None, _security_corpus_finding(
            relative,
            "security corpus file contains malformed JSON",
        )
    if not isinstance(value, dict):
        return None, _security_corpus_finding(
            relative,
            "security corpus top level must be an object",
        )
    if "cases" not in value:
        return None, _security_corpus_finding(
            relative,
            "security corpus requires a cases collection",
        )
    cases = value["cases"]
    if not isinstance(cases, list):
        return None, _security_corpus_finding(
            relative,
            "security corpus cases collection must be an array",
        )
    if any(not isinstance(case, dict) for case in cases):
        return None, _security_corpus_finding(
            relative,
            "security corpus cases entries must be objects",
        )
    if is_fixture_manifest:
        finding = _validate_fixture_case_collections(relative, cases)
        if finding is not None:
            return None, finding
        model = FixtureManifest
    else:
        model = IndirectInjectionDataset
    try:
        return model.model_validate(value), None
    except ValidationError:
        return None, _security_corpus_finding(
            relative,
            "security corpus does not satisfy its strict production schema",
        )


def _validate_fixture_case_collections(
    relative: str,
    cases: list[object],
) -> AuditFinding | None:
    for case in cases:
        if not isinstance(case, dict):
            raise AssertionError("fixture cases were not prevalidated")
        for collection in ("candidates", "open_results"):
            if collection not in case:
                article = "an" if collection == "open_results" else "a"
                return _security_corpus_finding(
                    relative,
                    f"fixture case requires {article} {collection} collection",
                )
            entries = case[collection]
            if not isinstance(entries, list):
                return _security_corpus_finding(
                    relative,
                    f"fixture {collection} collection must be an array",
                )
            if any(not isinstance(item, dict) for item in entries):
                return _security_corpus_finding(
                    relative,
                    f"fixture {collection} entries must be objects",
                )
    return None


def _security_corpus_finding(relative: str, detail: str) -> AuditFinding:
    return AuditFinding(
        code="invalid_security_corpus",
        path=relative,
        detail=detail,
    )


def _local_identity_values() -> tuple[str, ...]:
    values = {
        value.casefold()
        for key in ("USERNAME", "USER")
        if (value := os.environ.get(key))
        and len(value) >= 3
        and value.casefold() not in {"admin", "administrator", "root", "runner", "user"}
    }
    profile = os.environ.get("USERPROFILE")
    if profile:
        name = Path(profile).name.casefold()
        if len(name) >= 3 and name not in {"admin", "administrator", "user"}:
            values.add(name)
    return tuple(sorted(values))


def _public_sensitive_evidence_findings(
    relative: str,
    text: str,
    *,
    frozen_security_values: tuple[str, ...],
    local_identity_values: tuple[str, ...],
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    normalized = unicodedata.normalize("NFKC", text).casefold()
    checks = (
        (
            "credential_assignment",
            _CREDENTIAL_ASSIGNMENT_PATTERN.search(text) is not None,
            "credential-like assignment detected in sensitive public evidence",
        ),
        (
            "environment_reference",
            _ENVIRONMENT_REFERENCE_PATTERN.search(text) is not None,
            "machine environment or proxy variable detected in sensitive "
            "public evidence",
        ),
        (
            "private_runtime_reference",
            _PRIVATE_RUNTIME_REFERENCE_PATTERN.search(text) is not None,
            "private runtime path detected in sensitive public evidence",
        ),
        (
            "system_prompt_fragment",
            any(
                unicodedata.normalize("NFKC", value).casefold() in normalized
                for value in _SYSTEM_PROMPT_FRAGMENTS
            ),
            "system-prompt fragment detected in sensitive public evidence",
        ),
        (
            "frozen_security_content",
            any(
                unicodedata.normalize("NFKC", value).casefold() in normalized
                for value in frozen_security_values
            ),
            "frozen question, canary, or fixture content detected in sensitive "
            "public evidence",
        ),
        (
            "local_identity",
            any(
                re.search(
                    rf"(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])",
                    normalized,
                )
                is not None
                for value in local_identity_values
            ),
            "local user identity detected in sensitive public evidence",
        ),
    )
    for code, matched, detail in checks:
        if matched:
            findings.append(AuditFinding(code=code, path=relative, detail=detail))
    return findings


def _missing_link_findings(
    root: Path,
    source: Path,
    relative: str,
    text: str,
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    seen: set[str] = set()
    for match in _MARKDOWN_LINK_PATTERN.finditer(_markdown_without_code(text)):
        target = match.group(1).strip()
        if target.startswith("<") and ">" in target:
            target = target[1 : target.index(">")]
        else:
            target = target.split(maxsplit=1)[0]
        if (
            not target
            or target.startswith("#")
            or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target)
        ):
            continue
        target = unquote(target.split("#", 1)[0].split("?", 1)[0])
        if not target or target in seen:
            continue
        seen.add(target)
        linked = (source.parent / target).resolve()
        try:
            linked.relative_to(root)
        except ValueError:
            exists = False
        else:
            exists = linked.exists()
        if not exists:
            findings.append(
                AuditFinding(
                    code="missing_local_link",
                    path=relative,
                    detail=f"local Markdown target is missing: {target}",
                )
            )
    return findings


def _markdown_without_code(text: str) -> str:
    visible: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        fence = re.match(r"(`{3,}|~{3,})", stripped)
        if fence_character is not None:
            if (
                fence is not None
                and fence.group(1)[0] == fence_character
                and len(fence.group(1)) >= fence_length
            ):
                fence_character = None
                fence_length = 0
            visible.append("\n" if line.endswith("\n") else "")
            continue
        if fence is not None:
            fence_character = fence.group(1)[0]
            fence_length = len(fence.group(1))
            visible.append("\n" if line.endswith("\n") else "")
            continue
        visible.append(re.sub(r"`[^`\n]*`", "", line))
    return "".join(visible)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit tracked and untracked nonignored public candidates."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = audit_repository(args.root)
    except RuntimeError as exc:
        print(f"audit error: {exc}")
        return 2
    for finding in report.findings:
        print(f"[{finding.code}] {finding.path}: {finding.detail}")
    print(
        f"public candidates={len(report.candidate_files)} "
        f"findings={len(report.findings)}"
    )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AuditFinding",
    "AuditReport",
    "MAX_PUBLIC_FILE_BYTES",
    "audit_repository",
]
