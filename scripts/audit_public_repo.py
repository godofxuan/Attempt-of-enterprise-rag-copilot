from __future__ import annotations

import argparse
import re
import subprocess
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence
from urllib.parse import unquote

from pydantic import ValidationError

from app.evaluation.public_snapshot import PublicDemoSnapshot


MAX_PUBLIC_FILE_BYTES = 2 * 1024 * 1024
_PUBLIC_SNAPSHOT_PATH = "data/v2/public/demo_snapshot.json"
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
    "load_runs/",
    "logs/",
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
        findings.extend(_audit_one(root, relative))
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


def _audit_one(root: Path, relative: str) -> list[AuditFinding]:
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

    requires_portable_paths = (
        relative in _PUBLIC_TEXT_SURFACES or path.suffix.casefold() == ".md"
    )
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
