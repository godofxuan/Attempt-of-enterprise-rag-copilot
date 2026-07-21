from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, unquote, urlsplit

from app.evaluation import indirect_injection_exposure_public_verifier as verifier
from app.evaluation.indirect_injection_exposure import ExposureUnitObservation
from app.evaluation.indirect_injection_exposure_public_verifier import (
    CHECKSUM_CONTENT_NAMES,
    METRIC_DEFINITIONS,
    PUBLIC_EXPOSURE_FILES,
    PUBLIC_UNIT_ROW_KEYS,
    build_public_readme,
    verify_exposure_public_package,
)
from app.evaluation.indirect_injection_exposure_writer import (
    VerifiedExposureRunSnapshot,
    _assert_content_free,
    _assert_structured_content_free,
    _validated_trusted_directory,
    load_verified_exposure_run_snapshot,
)
from app.evaluation.indirect_injection_writer import validate_security_run_id
from app.evaluation.publication_paths import (
    _atomic_publish_no_replace,
    _validated_absent_publication_target,
    _validated_publication_root,
)


_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_NETWORK_URI_SCHEMES = frozenset(
    {"ftp", "ftps", "git", "http", "https", "ldap", "ldaps", "sftp", "ssh", "ws", "wss"}
)
_NETWORK_URI_CANDIDATE = re.compile(
    r"(?i)(?<![A-Za-z0-9+.-])[A-Za-z][A-Za-z0-9+.-]*:/{2,}[^\s\"'<>]+"
)
_DNS_LABEL_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-"
)
_USERINFO_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~!$&'()*+,;=:"
)
_HEX_DIGITS = frozenset("0123456789ABCDEFabcdef")
_NON_POSIX_ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/]"),
    re.compile(r"(?:\\){2,}[A-Za-z0-9._$-]+[\\/]"),
    re.compile(r"(?i)(?<![A-Za-z0-9])file:(?:/{1,3}|[A-Z]:[\\/])"),
)
_POSIX_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9/\\])/+(?=[^/\s])"
)


def export_exposure_public_evidence(
    source_run: Path,
    output_root: Path,
    *,
    package_name: str = "r2_s3_exposure",
    expected_source_manifest_sha256: str,
    expected_source_run_id: str,
    forbidden_texts: tuple[str, ...],
) -> Path:
    """Verify, project, scan, and atomically publish public evidence."""

    validate_security_run_id(package_name)
    validate_security_run_id(expected_source_run_id)
    if not _HASH_PATTERN.fullmatch(expected_source_manifest_sha256):
        raise ValueError("expected source manifest hash must be lowercase SHA-256")
    if not forbidden_texts or any(not value for value in forbidden_texts):
        raise ValueError("a non-empty forbidden text policy is required")
    source_run = _validated_trusted_directory(
        Path(source_run),
        "source run",
    )
    source_snapshot = load_verified_exposure_run_snapshot(
        source_run,
        expected_manifest_sha256=expected_source_manifest_sha256,
        expected_run_id=expected_source_run_id,
    )
    _assert_snapshot_unchanged(source_snapshot)
    source_manifest = source_snapshot.manifest
    if (
        source_manifest.schema_version
        != "indirect_injection_exposure_run_manifest_v2"
        or source_manifest.replay_dependencies is None
    ):
        raise ValueError("public export requires private manifest v2")
    observed_source_hash = source_snapshot.manifest_sha256
    private_summary = source_snapshot.summary.model_dump(mode="json")
    private_units = source_snapshot.units
    public_rows = tuple(
        sorted(
            (
                _project_unit(source_manifest.run_id, item)
                for item in private_units
            ),
            key=lambda item: (
                item["case_fingerprint"],
                item["unit_fingerprint"],
            ),
        )
    )
    verifier_bytes = Path(verifier.__file__).read_bytes()
    definitions_bytes = _json_bytes(METRIC_DEFINITIONS)
    public_summary = {
        "schema_version": "indirect_injection_exposure_public_summary_v1",
        "source": private_summary["source"],
        "verification_inputs": private_summary["verification_inputs"],
        "summary": private_summary["summary"],
        "strata": private_summary["strata"],
        "decision": private_summary["decision"],
        "unguarded_path_findings": private_summary[
            "unguarded_path_findings"
        ],
        "limitations": private_summary["limitations"],
    }
    public_manifest = {
        "schema_version": "indirect_injection_exposure_public_manifest_v2",
        "producer": "enterprise_agentic_rag_v2",
        "package_name": package_name,
        "source_private_run_id": source_manifest.run_id,
        "source_private_manifest_sha256": observed_source_hash,
        "source": source_manifest.source.model_dump(mode="json"),
        "replay_dependencies": [
            item.model_dump(mode="json")
            for item in source_manifest.replay_dependencies
        ],
        "counterfactual_depths": list(source_manifest.counterfactual_depths),
        "decision": source_manifest.decision,
        "case_count": source_manifest.case_count,
        "attack_case_count": source_manifest.attack_case_count,
        "benign_case_count": source_manifest.benign_case_count,
        "attack_unit_count": source_manifest.attack_unit_count,
        "benign_unit_count": source_manifest.benign_unit_count,
        "row_count": len(public_rows),
        "unguarded_path_findings": [
            item.model_dump(mode="json")
            for item in source_manifest.unguarded_path_findings
        ],
        "limitations": list(source_manifest.limitations),
        "metric_definitions_sha256": hashlib.sha256(
            definitions_bytes
        ).hexdigest(),
        "verifier_sha256": hashlib.sha256(verifier_bytes).hexdigest(),
    }
    readme = build_public_readme(public_manifest)
    source_hash_text = f"{observed_source_hash}  manifest.json\n"
    private_ids = tuple(
        sorted(
            {
                value
                for item in private_units
                for value in (item.case_id, item.unit_id)
            }
        )
    )
    forbidden_policy = tuple(sorted({*forbidden_texts, *private_ids}))
    for value in (public_manifest, public_summary, public_rows, METRIC_DEFINITIONS):
        _assert_structured_content_free(value, forbidden_policy)
        _assert_structured_paths_are_relative(value, "public structured data")
    for value in (readme, source_hash_text):
        _assert_structured_content_free(value, forbidden_policy)
        _assert_text_paths_are_relative(value, "public text")

    output_root = _validated_publication_root(
        Path(output_root),
        "output root",
    )
    target = _validated_absent_publication_target(
        output_root,
        package_name,
        "public exposure package",
        "package name resolves outside output root",
    )
    stage_root = Path(
        tempfile.mkdtemp(prefix=f".{package_name}.staging-", dir=output_root)
    ).resolve()
    stage = stage_root / package_name
    stage.mkdir()
    try:
        (stage / "verify.py").write_bytes(verifier_bytes)
        (stage / "metric_definitions.json").write_bytes(definitions_bytes)
        (stage / "manifest.redacted.json").write_bytes(
            _json_bytes(public_manifest)
        )
        (stage / "summary.json").write_bytes(_json_bytes(public_summary))
        (stage / "per_unit.redacted.jsonl").write_bytes(
            b"".join(_json_line(item) + b"\n" for item in public_rows)
        )
        (stage / "README.md").write_text(
            readme, encoding="utf-8", newline=""
        )
        (stage / "source_run.sha256").write_text(
            source_hash_text, encoding="utf-8", newline=""
        )
        for name in CHECKSUM_CONTENT_NAMES:
            if name == "checksums.sha256":
                continue
            payload = (stage / name).read_bytes()
            _assert_content_free(payload, forbidden_policy)
            _assert_no_absolute_paths(payload, name)
        (stage / "checksums.sha256").write_bytes(_checksum_bytes(stage))
        if {item.name for item in stage.iterdir()} != set(PUBLIC_EXPOSURE_FILES):
            raise ValueError("public exposure package has an unexpected artifact set")
        verify_exposure_public_package(stage)
        _atomic_publish_no_replace(stage, target)
        stage_root.rmdir()
    except Exception:
        shutil.rmtree(stage_root, ignore_errors=True)
        raise
    return target


def _assert_snapshot_unchanged(
    snapshot: VerifiedExposureRunSnapshot,
) -> None:
    snapshot.assert_unchanged()


def _project_unit(
    source_run_id: str,
    item: ExposureUnitObservation,
) -> dict[str, Any]:
    payload = item.model_dump(mode="json")
    case_id = payload.pop("case_id")
    unit_id = payload.pop("unit_id")
    projected = {
        "schema_version": "indirect_injection_exposure_public_unit_v1",
        "case_fingerprint": _fingerprint(
            "r2-s3-case-v1", source_run_id, case_id
        ),
        "unit_fingerprint": _fingerprint(
            "r2-s3-unit-v1", source_run_id, case_id, unit_id
        ),
        **payload,
    }
    if set(projected) != set(PUBLIC_UNIT_ROW_KEYS):
        raise ValueError("public unit projection keys are not exact")
    return projected


def _fingerprint(domain: str, *values: str) -> str:
    framed = "\0".join((domain, *values)).encode("utf-8")
    return hashlib.sha256(framed).hexdigest()


def _assert_no_absolute_paths(payload: bytes, label: str) -> None:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} is not UTF-8") from exc
    _assert_text_paths_are_relative(text, label)


def _assert_structured_paths_are_relative(value: Any, label: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_structured_paths_are_relative(key, label)
            _assert_structured_paths_are_relative(item, label)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_structured_paths_are_relative(item, label)
    elif isinstance(value, str):
        _assert_text_paths_are_relative(value, label)


def _assert_text_paths_are_relative(text: str, label: str) -> None:
    scanned_text = _elide_recognized_network_uris(text, label)
    if _contains_absolute_local_path(scanned_text, include_posix=True):
        raise ValueError(f"{label} contains an absolute local path")


def _elide_recognized_network_uris(text: str, label: str) -> str:
    def replace(match: re.Match[str]) -> str:
        candidate = match.group(0)
        parsed = _parse_valid_network_uri(candidate)
        if parsed is not None:
            _assert_network_uri_components_are_path_free(parsed, label)
            return " " * len(candidate)
        return candidate

    return _NETWORK_URI_CANDIDATE.sub(replace, text)


def _is_valid_network_uri(candidate: str) -> bool:
    return _parse_valid_network_uri(candidate) is not None


def _parse_valid_network_uri(candidate: str) -> SplitResult | None:
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None
    if (
        parsed.scheme.lower() in _NETWORK_URI_SCHEMES
        and _is_valid_network_authority(parsed)
    ):
        return parsed
    return None


def _assert_network_uri_components_are_path_free(
    parsed: SplitResult,
    label: str,
) -> None:
    userinfo, separator, _host_port = parsed.netloc.rpartition("@")
    components = (
        userinfo if separator else "",
        parsed.query,
        parsed.fragment,
    )
    if any(
        _contains_absolute_local_path(
            _decode_percent_escapes(component),
            include_posix=True,
        )
        for component in components
        if component
    ):
        raise ValueError(f"{label} contains an absolute local path")
    if _contains_absolute_local_path(
        _decode_percent_escapes(parsed.path),
        include_posix=False,
    ):
        raise ValueError(f"{label} contains an absolute local path")


def _decode_percent_escapes(value: str) -> str:
    decoded = value
    for _ in range(3):
        updated = unquote(decoded)
        if updated == decoded:
            break
        decoded = updated
    return decoded


def _contains_absolute_local_path(
    text: str,
    *,
    include_posix: bool,
) -> bool:
    if text.startswith("\\\\") or any(
        pattern.search(text) for pattern in _NON_POSIX_ABSOLUTE_PATH_PATTERNS
    ):
        return True
    return include_posix and (
        text.startswith("/")
        or _POSIX_ABSOLUTE_PATH_PATTERN.search(text) is not None
    )


def _is_valid_network_authority(parsed: SplitResult) -> bool:
    try:
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    if not hostname or not parsed.netloc:
        return False

    userinfo, separator, host_port = parsed.netloc.rpartition("@")
    if separator:
        if not _is_valid_userinfo(userinfo):
            return False
    else:
        host_port = parsed.netloc
    if not host_port:
        return False

    if host_port.startswith("["):
        closing_bracket = host_port.find("]")
        if closing_bracket < 0:
            return False
        raw_hostname = host_port[1:closing_bracket]
        port_suffix = host_port[closing_bracket + 1 :]
        if not _is_valid_port_suffix(port_suffix, port):
            return False
        if "%" in raw_hostname:
            return False
        try:
            return isinstance(
                ipaddress.ip_address(hostname),
                ipaddress.IPv6Address,
            )
        except ValueError:
            return False

    if "[" in host_port or "]" in host_port or host_port.count(":") > 1:
        return False
    raw_hostname, port_separator, raw_port = host_port.partition(":")
    if port_separator:
        if not _is_valid_explicit_port(raw_port, port):
            return False
    elif port is not None:
        return False
    if not raw_hostname:
        return False
    return _is_valid_ipv4_or_dns_hostname(hostname)


def _is_valid_port_suffix(port_suffix: str, port: int | None) -> bool:
    if not port_suffix:
        return port is None
    if not port_suffix.startswith(":"):
        return False
    return _is_valid_explicit_port(port_suffix[1:], port)


def _is_valid_explicit_port(raw_port: str, port: int | None) -> bool:
    return (
        bool(raw_port)
        and raw_port.isascii()
        and raw_port.isdecimal()
        and port is not None
    )


def _is_valid_userinfo(userinfo: str) -> bool:
    index = 0
    while index < len(userinfo):
        character = userinfo[index]
        if character == "%":
            escape = userinfo[index + 1 : index + 3]
            if len(escape) != 2 or any(
                value not in _HEX_DIGITS for value in escape
            ):
                return False
            index += 3
            continue
        if character not in _USERINFO_CHARS:
            return False
        index += 1
    return True


def _is_valid_ipv4_or_dns_hostname(hostname: str) -> bool:
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        return isinstance(address, ipaddress.IPv4Address)

    try:
        ascii_hostname = hostname.encode("idna").decode("ascii")
        ascii_hostname.encode("ascii").decode("idna")
    except UnicodeError:
        return False
    has_terminal_root = ascii_hostname.endswith(".")
    dns_text = ascii_hostname[:-1] if has_terminal_root else ascii_hostname
    text_limit = 254 if has_terminal_root else 253
    if not dns_text or len(ascii_hostname) > text_limit:
        return False
    labels = dns_text.split(".")
    wire_length = 1 + sum(len(label) + 1 for label in labels)
    return all(
        bool(label)
        and len(label) <= 63
        and label[0] != "-"
        and label[-1] != "-"
        and all(character in _DNS_LABEL_CHARS for character in label)
        for label in labels
    ) and wire_length <= 255


def _checksum_bytes(stage: Path) -> bytes:
    return "".join(
        f"{_sha256(stage / name)}  {name}\n"
        for name in CHECKSUM_CONTENT_NAMES
    ).encode("utf-8")


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _json_line(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = ["export_exposure_public_evidence"]
