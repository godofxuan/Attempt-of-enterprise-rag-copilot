from __future__ import annotations

import argparse
import ast
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
    "data/v2/public/r2_s4_cross_model/",
    "docs/security/r2_s5/evidence/",
)
_PUBLIC_CASE_ID_ALLOWED_PREFIXES = ("data/v2/public/r2_s1_d7/",)
_PUBLIC_PNG_DIMENSIONS = {
    "docs/assets/ask.png": (1440, 1000),
    "docs/assets/trace.png": (1440, 1000),
    "docs/assets/evaluation.png": (1440, 1000),
}
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
_ALLOWED_MANIFEST_BOUND_HIDDEN_METADATA = frozenset(
    f"data/v2/public/{package}/dataset/.private/lifecycle/"
    f"g10-expanded-lifecycle-v4/{filename}"
    for package in ("lifecycle_g10_v2", "lifecycle_g10_v3")
    for filename in (
        "change_descriptor.json",
        "manifest.json",
        "query_descriptor.json",
    )
)
_FORBIDDEN_RUNTIME_SUFFIXES = {".db", ".log", ".sqlite", ".sqlite3"}
_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----"
)
_TOKEN_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."
        r"[A-Za-z0-9_-]{20,}\b"
    ),
)
_PRIVATE_KEY_BYTES_PATTERN = re.compile(
    rb"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----"
)
_TOKEN_BYTES_PATTERNS = (
    re.compile(rb"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(rb"\bghp_[A-Za-z0-9]{30,}\b"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(rb"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(
        rb"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."
        rb"[A-Za-z0-9_-]{20,}\b"
    ),
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
_CREDENTIAL_NAME_EXPRESSION = (
    r"aws[_-]?secret[_-]?access[_-]?key|"
    r"aws[_-]?session[_-]?token|"
    r"client[_-]?secret|consumer[_-]?secret|"
    r"secret[_-]?access[_-]?key|secret[_-]?key|private[_-]?key|"
    r"refresh[_-]?token|bearer[_-]?token|auth[_-]?token|"
    r"api[_-]?key|access[_-]?(?:key|token)|"
    r"password|passwd|pwd|authorization|secret|token"
)
_CREDENTIAL_NAME_PATTERN = re.compile(
    rf"(?ix)^(?:{_CREDENTIAL_NAME_EXPRESSION})$"
)
_CREDENTIAL_ASSIGNMENT_PATTERN = re.compile(
    rf"(?ix)\b(?P<key>{_CREDENTIAL_NAME_EXPRESSION})"
    r"\b\s*[:=]\s*(?:"
    r"\"(?P<double_quoted>[^\"\r\n]*)\"|"
    r"'(?P<single_quoted>[^'\r\n]*)'|"
    r"(?P<bare>[^\s\"',;]{4,})"
    r")"
)
_SAFE_CREDENTIAL_VALUE_PATTERN = re.compile(
    r"(?ix)^(?:bearer\s+)?(?:"
    r"(?:attacker|operator|user)-token|"
    r"(?:dummy|example|fake|not-real|placeholder|redacted|"
    r"should-not-be-public)(?:[-_/.:][a-z0-9_.:/-]+)?|"
    r"never-(?:expose|show)(?:[-_/.:][a-z0-9_.:/-]+)?|"
    r"test(?:[-_/.:][a-z0-9_.:/-]+)?|"
    r"sk-test-[a-z0-9]+|"
    r"[a-z0-9]+_test_(?:private_)?key_[a-z0-9]+"
    r")$"
)
_EXPLICIT_DYNAMIC_CREDENTIAL_PATTERN = re.compile(
    r"(?ix)^(?:"
    r"(?:bearer\s+)?\$(?:[A-Za-z_][A-Za-z0-9_]*|"
    r"\{[A-Za-z_][A-Za-z0-9_]*\})|"
    r"<[A-Za-z_][A-Za-z0-9_.:-]*>|"
    r"\{[A-Za-z_][A-Za-z0-9_.:-]*\}"
    r")$"
)
_SYSTEM_PROMPT_FRAGMENTS = (
    "You are a grounded enterprise knowledge-base answer generator operating ",
    "你是企业知识库 RAG 的证据充分性判定器。",
    "你是企业知识库助手。",
)
_SCANNER_RULE_DEFINITION_NAMES = frozenset(
    {
        "_ALLOWED_RUNTIME_MARKERS",
        "_CREDENTIAL_ASSIGNMENT_PATTERN",
        "_CREDENTIAL_NAME_EXPRESSION",
        "_CREDENTIAL_NAME_PATTERN",
        "_ENVIRONMENT_REFERENCE_PATTERN",
        "_FORBIDDEN_PREFIXES",
        "_POSIX_USER_PATH_PATTERN",
        "_PRIVATE_RUNTIME_REFERENCE_PATTERN",
        "_EXPLICIT_DYNAMIC_CREDENTIAL_PATTERN",
        "_SAFE_CREDENTIAL_VALUE_PATTERN",
        "_SYSTEM_PROMPT_FRAGMENTS",
    }
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
    top_level = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "rev-parse",
            "--show-toplevel",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if top_level.returncode != 0:
        raise RuntimeError("audit root is not a Git worktree")
    try:
        discovered_root = Path(
            top_level.stdout.decode("utf-8").strip()
        ).resolve()
    except (UnicodeDecodeError, OSError) as exc:
        raise RuntimeError("Git worktree root is invalid") from exc
    if discovered_root != root:
        raise RuntimeError("audit root is not the Git worktree root")

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
    if text is not None:
        strong_scan_text = _text_for_strong_scan(relative, text)
        sensitive_evidence = relative.startswith(
            _SENSITIVE_PUBLIC_EVIDENCE_PREFIXES
        )
        include_case_ids = not relative.startswith(
            _PUBLIC_CASE_ID_ALLOWED_PREFIXES
        )
        findings.extend(
            _strong_public_text_findings(
                relative,
                strong_scan_text,
                frozen_security_values=frozen_security_values.values(
                    include_case_ids=include_case_ids
                ),
                local_identity_values=local_identity_values,
                sensitive_evidence=sensitive_evidence,
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
    if relative in _ALLOWED_MANIFEST_BOUND_HIDDEN_METADATA:
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


def _contains_unsafe_credential_assignment(
    text: str,
    *,
    python_source: bool,
) -> bool:
    if python_source:
        return _python_contains_unsafe_credential_assignment(text)
    return _text_contains_unsafe_credential_assignment(text)


def _text_contains_unsafe_credential_assignment(text: str) -> bool:
    for match in _CREDENTIAL_ASSIGNMENT_PATTERN.finditer(text):
        raw_value = next(
            (
                match.group(name)
                for name in ("double_quoted", "single_quoted", "bare")
                if match.group(name) is not None
            ),
            "",
        )
        if (
            match.group("bare") is not None
            and _bare_credential_reference_is_safe(raw_value)
        ):
            continue
        if _credential_value_is_safe(raw_value):
            continue
        return True
    return False


def _python_contains_unsafe_credential_assignment(text: str) -> bool:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _text_contains_unsafe_credential_assignment(text)

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _text_contains_unsafe_credential_assignment(node.value):
                return True
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target]
            )
            value = _literal_credential_value(node.value)
            if value is not None and any(
                _is_credential_target(target)
                for target in targets
            ) and not _credential_value_is_safe(value):
                return True
        if isinstance(node, ast.keyword) and node.arg is not None:
            value = _literal_credential_value(node.value)
            if (
                _CREDENTIAL_NAME_PATTERN.fullmatch(node.arg)
                and value is not None
                and not _credential_value_is_safe(value)
            ):
                return True
        if isinstance(node, ast.Dict):
            for key_node, value_node in zip(node.keys, node.values):
                key = _literal_credential_value(key_node)
                value = _literal_credential_value(value_node)
                if (
                    isinstance(key, str)
                    and _CREDENTIAL_NAME_PATTERN.fullmatch(key)
                    and value is not None
                    and not _credential_value_is_safe(value)
                ):
                    return True
    return False


def _is_credential_target(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return _CREDENTIAL_NAME_PATTERN.fullmatch(node.id) is not None
    if isinstance(node, ast.Attribute):
        return _CREDENTIAL_NAME_PATTERN.fullmatch(node.attr) is not None
    if isinstance(node, ast.Subscript):
        key = _literal_credential_value(node.slice)
        return (
            isinstance(key, str)
            and _CREDENTIAL_NAME_PATTERN.fullmatch(key) is not None
        )
    if isinstance(node, (ast.Tuple, ast.List)):
        return any(_is_credential_target(item) for item in node.elts)
    return False


def _literal_credential_value(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return node.value
        if isinstance(node.value, bytes):
            try:
                return node.value.decode("ascii")
            except UnicodeDecodeError:
                return None
    return None


def _credential_value_is_safe(raw_value: str) -> bool:
    value = raw_value.strip().casefold()
    if not value:
        return True
    candidate = value
    for left, right in (("`", "`"), ("[", "]"), ("<", ">")):
        if candidate.startswith(left) and candidate.endswith(right):
            candidate = candidate[1:-1].strip()
            break
    candidate = candidate.rstrip("`")
    if value == "ollama" or _SAFE_CREDENTIAL_VALUE_PATTERN.fullmatch(candidate):
        return True
    if value in {"bearer", "bearer jwt", "bearer <jwt>"}:
        return True
    if value.strip("`").isdigit():
        return True
    if _EXPLICIT_DYNAMIC_CREDENTIAL_PATTERN.fullmatch(value):
        return True
    if value.startswith(
        (
            "config.",
            "env.",
            "os.",
            "self.",
            "settings.",
        )
    ):
        return True
    if set(value) <= {"*", "x"}:
        return True
    return False


def _bare_credential_reference_is_safe(raw_value: str) -> bool:
    value = raw_value.strip().casefold()
    if _EXPLICIT_DYNAMIC_CREDENTIAL_PATTERN.fullmatch(value):
        return True
    if value.startswith(
        (
            "config.",
            "env.",
            "os.",
            "self.",
            "settings.",
            "bind_request_context(",
        )
    ):
        return True
    return re.fullmatch(
        r"[a-z_][a-z0-9_.]*(?:_token|_secret|_key)",
        value,
    ) is not None


def _text_for_strong_scan(relative: str, text: str) -> str:
    if relative == "scripts/audit_public_repo.py":
        return _mask_scanner_rule_definitions(text)
    return text


def _mask_scanner_rule_definitions(text: str) -> str:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text
    nodes: list[ast.AST] = []
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            names = {
                target.id
                for target in statement.targets
                if isinstance(target, ast.Name)
            }
            if names & _SCANNER_RULE_DEFINITION_NAMES:
                nodes.append(statement.value)
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id in _SCANNER_RULE_DEFINITION_NAMES
            and statement.value is not None
        ):
            nodes.append(statement.value)
    for function in (
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_local_identity_values"
    ):
        nodes.extend(
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
    return _mask_ast_source_ranges(text, nodes)


def _mask_ast_source_ranges(text: str, nodes: Iterable[ast.AST]) -> str:
    lines = text.splitlines(keepends=True)
    starts: list[int] = []
    offset = 0
    for line in lines:
        starts.append(offset)
        offset += len(line)
    masked = list(text)
    for node in nodes:
        if not all(
            hasattr(node, attribute)
            for attribute in ("lineno", "col_offset", "end_lineno", "end_col_offset")
        ):
            continue
        start_line = int(node.lineno) - 1
        end_line = int(node.end_lineno) - 1
        if not (0 <= start_line < len(lines) and 0 <= end_line < len(lines)):
            continue
        start = starts[start_line] + _utf8_column_to_character(
            lines[start_line],
            int(node.col_offset),
        )
        end = starts[end_line] + _utf8_column_to_character(
            lines[end_line],
            int(node.end_col_offset),
        )
        for index in range(start, min(end, len(masked))):
            if masked[index] not in "\r\n":
                masked[index] = " "
    return "".join(masked)


def _utf8_column_to_character(line: str, byte_column: int) -> int:
    return len(line.encode("utf-8")[:byte_column].decode("utf-8"))


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


def _strong_public_text_findings(
    relative: str,
    text: str,
    *,
    frozen_security_values: tuple[str, ...],
    local_identity_values: tuple[str, ...],
    sensitive_evidence: bool,
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    normalized = unicodedata.normalize("NFKC", text).casefold()
    checks = (
        (
            "credential_assignment",
            _contains_unsafe_credential_assignment(
                text,
                python_source=relative.casefold().endswith(".py"),
            ),
            "literal credential-like assignment detected",
        ),
        (
            "environment_reference",
            sensitive_evidence
            and _ENVIRONMENT_REFERENCE_PATTERN.search(text) is not None,
            "machine environment or proxy variable detected",
        ),
        (
            "private_runtime_reference",
            sensitive_evidence
            and _PRIVATE_RUNTIME_REFERENCE_PATTERN.search(text) is not None,
            "private runtime path detected",
        ),
        (
            "system_prompt_fragment",
            sensitive_evidence
            and any(
                unicodedata.normalize("NFKC", value).casefold() in normalized
                for value in _SYSTEM_PROMPT_FRAGMENTS
            ),
            "system-prompt fragment detected",
        ),
        (
            "frozen_security_content",
            sensitive_evidence
            and any(
                unicodedata.normalize("NFKC", value).casefold() in normalized
                for value in frozen_security_values
            ),
            "frozen question, canary, or fixture content detected",
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
            "local user identity detected",
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
