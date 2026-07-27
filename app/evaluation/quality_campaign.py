from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.evaluation.contracts import StrictModel
from app.evaluation.quality_review import verify_quality_review_packet
from app.filesystem import atomic_directory_move
from app.security.private_fs import harden_private_directory


_CAMPAIGN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}")
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_REVIEWER_SLOTS = ("reviewer-a", "reviewer-b")
_MUTABLE_DIRECTORIES = ("inbox", "submissions", "evidence")
_PACKET_FILES = (
    "manifest.json",
    "REVIEW_INSTRUCTIONS.md",
    "review_items.jsonl",
    "rubric.json",
    "submission_template.csv",
)
_COORDINATOR_ARTIFACTS = {
    "coordinator/COMMANDS.md",
}
_IDENTITY_PLACEHOLDERS = (
    "coordinator/reviewer-a.identity.txt",
    "coordinator/reviewer-b.identity.txt",
)
class QualityReviewCampaignKit(StrictModel):
    slot: Literal["reviewer-a", "reviewer-b"]
    root_relpath: str
    packet_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    artifacts: dict[str, str]

    @field_validator("root_relpath")
    @classmethod
    def validate_root_relpath(cls, value: str) -> str:
        return _validate_relative_path(value)

    @field_validator("artifacts")
    @classmethod
    def validate_artifacts(cls, values: dict[str, str]) -> dict[str, str]:
        if not values:
            raise ValueError("quality review campaign kit has no artifacts")
        for path, digest in values.items():
            _validate_relative_path(path)
            if re.fullmatch(_SHA256_PATTERN, digest) is None:
                raise ValueError("quality review campaign kit hash is invalid")
        return values


class QualityReviewCampaignManifest(StrictModel):
    schema_version: Literal["enterprise_quality_review_campaign_v1"] = (
        "enterprise_quality_review_campaign_v1"
    )
    campaign_id: str
    created_at_utc: datetime
    status: Literal["NOT_RUN"] = "NOT_RUN"
    packet_id: str
    packet_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    reviewer_slots: tuple[str, str] = _REVIEWER_SLOTS
    identity_pepper_relpath: str = "coordinator/identity-pepper.bin"
    reviewer_identity_relpaths: tuple[str, str] = _IDENTITY_PLACEHOLDERS
    reviewer_identity_domain_sha256: str = Field(pattern=_SHA256_PATTERN)
    coordinator_artifacts: dict[str, str]
    reviewer_kits: tuple[QualityReviewCampaignKit, QualityReviewCampaignKit]
    human_judgements_completed: Literal[0] = 0
    independence_status: Literal["not_independent"] = "not_independent"
    claim_status: Literal["NOT_RUN"] = "NOT_RUN"

    @field_validator("campaign_id")
    @classmethod
    def validate_campaign_id(cls, value: str) -> str:
        if _CAMPAIGN_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("quality review campaign ID is invalid")
        return value

    @field_validator("created_at_utc")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("quality review campaign timestamp must be timezone-aware")
        return value

    @field_validator("identity_pepper_relpath")
    @classmethod
    def validate_identity_pepper_relpath(cls, value: str) -> str:
        return _validate_relative_path(value)

    @field_validator("coordinator_artifacts")
    @classmethod
    def validate_coordinator_artifacts(
        cls,
        values: dict[str, str],
    ) -> dict[str, str]:
        if not values:
            raise ValueError("quality review coordinator artifacts are missing")
        for path, digest in values.items():
            normalized = _validate_relative_path(path)
            if not normalized.startswith("coordinator/"):
                raise ValueError(
                    "quality review coordinator artifact escapes coordinator root"
                )
            if re.fullmatch(_SHA256_PATTERN, digest) is None:
                raise ValueError("quality review coordinator hash is invalid")
        return values

    @model_validator(mode="after")
    def validate_campaign_contract(self) -> QualityReviewCampaignManifest:
        if self.reviewer_slots != _REVIEWER_SLOTS:
            raise ValueError("quality review campaign reviewer slots changed")
        if self.reviewer_identity_relpaths != _IDENTITY_PLACEHOLDERS:
            raise ValueError(
                "quality review campaign identity placeholders changed"
            )
        if tuple(item.slot for item in self.reviewer_kits) != _REVIEWER_SLOTS:
            raise ValueError("quality review campaign kits changed")
        if set(self.coordinator_artifacts) != _COORDINATOR_ARTIFACTS:
            raise ValueError(
                "quality review campaign coordinator artifacts changed"
            )
        if self.identity_pepper_relpath in self.coordinator_artifacts:
            raise ValueError(
                "quality review campaign identity pepper cannot be a "
                "shareable artifact"
            )
        if len({item.root_relpath for item in self.reviewer_kits}) != 2:
            raise ValueError("quality review campaign kit roots must be distinct")
        for kit in self.reviewer_kits:
            if kit.root_relpath != f"reviewer-kits/{kit.slot}":
                raise ValueError("quality review campaign kit root changed")
            if set(kit.artifacts) != _expected_kit_artifacts(self.packet_id):
                raise ValueError("quality review campaign kit artifacts changed")
            if kit.packet_manifest_sha256 != self.packet_manifest_sha256:
                raise ValueError(
                    "quality review campaign kit packet binding changed"
                )
        return self


def initialize_quality_review_campaign(
    *,
    packet_dir: Path,
    out_root: Path,
    campaign_id: str,
) -> Path:
    if _CAMPAIGN_ID_PATTERN.fullmatch(campaign_id) is None:
        raise ValueError("quality review campaign ID is invalid")
    packet_root = Path(packet_dir).absolute()
    if packet_root.is_symlink() or not packet_root.is_dir():
        raise ValueError("quality review campaign packet root is unsafe")
    packet = verify_quality_review_packet(packet_root)

    root = Path(out_root).absolute()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("quality review campaign output root is unsafe")
    target = root / campaign_id
    if target.exists() or target.is_symlink():
        raise FileExistsError("quality review campaign already exists")

    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{campaign_id}.staging-",
            dir=root,
        )
    )
    try:
        pepper = secrets.token_bytes(32)
        coordinator = stage / "coordinator"
        coordinator.mkdir()
        _write_exclusive(coordinator / "identity-pepper.bin", pepper)
        _write_exclusive(coordinator / "reviewer-a.identity.txt", b"")
        _write_exclusive(coordinator / "reviewer-b.identity.txt", b"")
        commands = _coordinator_commands(campaign_id, packet.packet_id)
        _write_exclusive(coordinator / "COMMANDS.md", commands.encode("utf-8"))
        harden_private_directory(coordinator)

        for name in _MUTABLE_DIRECTORIES:
            (stage / name).mkdir()

        packet_manifest_sha256 = _sha256(packet_root / "manifest.json")
        kits: list[QualityReviewCampaignKit] = []
        for slot in _REVIEWER_SLOTS:
            kit_root = stage / "reviewer-kits" / slot
            kit_packet = kit_root / packet.packet_id
            kit_packet.mkdir(parents=True)
            for name in _PACKET_FILES:
                source = _require_regular_file(packet_root / name)
                shutil.copyfile(source, kit_packet / name)
            shutil.copyfile(
                packet_root / "submission_template.csv",
                kit_root / "completed_template.csv",
            )
            task = _reviewer_task(slot, packet.packet_id)
            (kit_root / "REVIEWER_TASK.md").write_text(
                task,
                encoding="utf-8",
                newline="\n",
            )
            kit_artifacts = _hash_tree(kit_root)
            kits.append(
                QualityReviewCampaignKit(
                    slot=slot,
                    root_relpath=kit_root.relative_to(stage).as_posix(),
                    packet_manifest_sha256=packet_manifest_sha256,
                    artifacts=kit_artifacts,
                )
            )

        coordinator_artifacts = {
            "coordinator/COMMANDS.md": _sha256(coordinator / "COMMANDS.md"),
        }
        manifest = QualityReviewCampaignManifest(
            campaign_id=campaign_id,
            created_at_utc=datetime.now(timezone.utc),
            packet_id=packet.packet_id,
            packet_manifest_sha256=packet_manifest_sha256,
            reviewer_identity_domain_sha256=hashlib.sha256(pepper).hexdigest(),
            coordinator_artifacts=coordinator_artifacts,
            reviewer_kits=tuple(kits),
        )
        (stage / "campaign_manifest.json").write_bytes(
            _canonical_json_bytes(manifest.model_dump(mode="json"))
        )
        _verify_quality_review_campaign_readiness(
            stage,
            require_directory_name=False,
        )
        atomic_directory_move(stage, target)
        verify_quality_review_campaign_readiness(target)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return target


def verify_quality_review_campaign_readiness(
    campaign_dir: Path,
) -> QualityReviewCampaignManifest:
    return _verify_quality_review_campaign_readiness(
        campaign_dir,
        require_directory_name=True,
    )


def validate_quality_review_campaign_owner_context() -> None:
    if os.name != "nt":
        return
    token_username = _windows_token_username()
    intended_username = os.environ.get("USERNAME", "").strip()
    _require_matching_owner(token_username, intended_username)


def _verify_quality_review_campaign_readiness(
    campaign_dir: Path,
    *,
    require_directory_name: bool,
) -> QualityReviewCampaignManifest:
    root = Path(campaign_dir).absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("quality review campaign root is unsafe")
    manifest_path = _resolve_regular_file(root, "campaign_manifest.json")
    manifest_content = manifest_path.read_bytes()
    manifest = QualityReviewCampaignManifest.model_validate_json(
        manifest_content
    )
    if manifest_content != _canonical_json_bytes(
        manifest.model_dump(mode="json")
    ):
        raise ValueError("quality review campaign manifest is not canonical")
    if require_directory_name and root.name != manifest.campaign_id:
        raise ValueError("quality review campaign directory ID mismatch")

    pepper_path = _resolve_regular_file(
        root,
        manifest.identity_pepper_relpath,
    )
    pepper = pepper_path.read_bytes()
    if len(pepper) < 32 or len(set(pepper)) < 8:
        raise ValueError("quality review campaign identity pepper is weak")
    if hashlib.sha256(pepper).hexdigest() != (
        manifest.reviewer_identity_domain_sha256
    ):
        raise ValueError("quality review campaign identity domain mismatch")

    expected_files = {
        "campaign_manifest.json",
        manifest.identity_pepper_relpath,
    }
    for relative in manifest.reviewer_identity_relpaths:
        path = _resolve_regular_file(root, relative)
        if path.read_bytes():
            raise ValueError(
                "quality review campaign identity placeholder is not blank"
            )
        expected_files.add(relative)
    for relative, expected_hash in manifest.coordinator_artifacts.items():
        path = _resolve_regular_file(root, relative)
        if _sha256(path) != expected_hash:
            raise ValueError(
                f"quality review coordinator artifact hash mismatch: {relative}"
            )
        expected_files.add(relative)

    for kit in manifest.reviewer_kits:
        kit_root = root / Path(*PurePosixPath(kit.root_relpath).parts)
        if kit_root.is_symlink() or not kit_root.is_dir():
            raise ValueError("quality review campaign kit root is unsafe")
        for relative, expected_hash in kit.artifacts.items():
            full_relative = (
                PurePosixPath(kit.root_relpath) / PurePosixPath(relative)
            ).as_posix()
            path = _resolve_regular_file(root, full_relative)
            if _sha256(path) != expected_hash:
                raise ValueError(
                    f"quality review campaign kit hash mismatch: {full_relative}"
                )
            if pepper in path.read_bytes():
                raise ValueError(
                    "quality review campaign identity pepper leaked into "
                    "a reviewer kit"
                )
            expected_files.add(full_relative)
        packet_root = kit_root / manifest.packet_id
        packet = verify_quality_review_packet(packet_root)
        if packet.packet_id != manifest.packet_id:
            raise ValueError("quality review campaign kit packet ID mismatch")
        if _sha256(packet_root / "manifest.json") != (
            kit.packet_manifest_sha256
        ):
            raise ValueError(
                "quality review campaign kit packet manifest mismatch"
            )
        if (kit_root / "completed_template.csv").read_bytes() != (
            packet_root / "submission_template.csv"
        ).read_bytes():
            raise ValueError(
                "quality review campaign completed template is not blank"
            )

    for name in _MUTABLE_DIRECTORIES:
        path = root / name
        if path.is_symlink() or not path.is_dir():
            raise ValueError(
                f"quality review campaign mutable directory is unsafe: {name}"
            )
    observed_files = _all_regular_files(root)
    if observed_files != expected_files:
        raise ValueError(
            "quality review campaign contains missing or undeclared files"
        )
    return manifest


def _windows_token_username() -> str:
    buffer = ctypes.create_unicode_buffer(256)
    length = ctypes.c_ulong(len(buffer))
    get_user_name = ctypes.windll.advapi32.GetUserNameW
    get_user_name.argtypes = [
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    get_user_name.restype = ctypes.c_int
    if not get_user_name(buffer, ctypes.byref(length)) or not buffer.value:
        raise RuntimeError(
            "quality review campaign cannot resolve the Windows token owner"
        )
    return buffer.value


def _require_matching_owner(
    token_username: str,
    intended_username: str,
) -> None:
    if not intended_username:
        raise RuntimeError(
            "quality review campaign intended Windows owner is unavailable"
        )
    if token_username.casefold() != intended_username.casefold():
        raise RuntimeError(
            "quality review campaign owner mismatch: run initialization "
            "from the intended Windows account outside the delegated sandbox"
        )


def _coordinator_commands(campaign_id: str, packet_id: str) -> str:
    campaign = f".private\\quality\\campaigns\\{campaign_id}"
    return f"""# Coordinator commands

Keep `coordinator/` private. Send each person only their matching reviewer kit.
Save returned CSV files under `inbox/` and fill the two identity placeholders
with stable organizational identities before submission.

Packet: `{packet_id}`

Reviewer A submission:

```powershell
.\\.venv\\Scripts\\python.exe -m scripts.submit_quality_review `
  --packet-dir {campaign}\\reviewer-kits\\reviewer-a\\{packet_id} `
  --completed-template {campaign}\\inbox\\reviewer-a.csv `
  --reviewer-id-file {campaign}\\coordinator\\reviewer-a.identity.txt `
  --identity-pepper-file {campaign}\\coordinator\\identity-pepper.bin `
  --out-dir {campaign}\\submissions\\reviewer-a `
  --attest-blind --attest-independent
```

Reviewer B submission:

```powershell
.\\.venv\\Scripts\\python.exe -m scripts.submit_quality_review `
  --packet-dir {campaign}\\reviewer-kits\\reviewer-b\\{packet_id} `
  --completed-template {campaign}\\inbox\\reviewer-b.csv `
  --reviewer-id-file {campaign}\\coordinator\\reviewer-b.identity.txt `
  --identity-pepper-file {campaign}\\coordinator\\identity-pepper.bin `
  --out-dir {campaign}\\submissions\\reviewer-b `
  --attest-blind --attest-independent
```

Do not use `--fixture-only` for real human work.
"""


def _reviewer_task(slot: str, packet_id: str) -> str:
    return f"""# Reviewer task: {slot}

Packet: `{packet_id}`

Review independently. Do not inspect the repository, machine verdicts, control
maps, or another reviewer's work. Read the packet and rubric, then edit only
`completed_template.csv`. Return that CSV to the coordinator. Do not add your
name, identity, attestations, or timestamp to the CSV.
"""


def _expected_kit_artifacts(packet_id: str) -> set[str]:
    packet_root = _validate_relative_path(packet_id)
    if "/" in packet_root:
        raise ValueError("quality review campaign packet ID is unsafe")
    return {
        "REVIEWER_TASK.md",
        "completed_template.csv",
        *(f"{packet_root}/{name}" for name in _PACKET_FILES),
    }


def _validate_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or not path.parts
        or "." in path.parts
        or ".." in path.parts
        or path.as_posix() != normalized
    ):
        raise ValueError("quality review campaign path is unsafe")
    return normalized


def _resolve_regular_file(root: Path, relative: str) -> Path:
    normalized = _validate_relative_path(relative)
    candidate = root
    for part in PurePosixPath(normalized).parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError(
                f"quality review campaign path contains a symlink: {normalized}"
            )
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(
            f"quality review campaign file is missing: {normalized}"
        ) from exc
    if not resolved.is_file():
        raise ValueError(
            f"quality review campaign path is not a file: {normalized}"
        )
    return resolved


def _require_regular_file(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"quality review packet artifact is unsafe: {path.name}")
    return path


def _hash_tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _all_regular_files(root: Path) -> set[str]:
    files: set[str] = set()
    for current, directory_names, file_names in os.walk(
        root,
        topdown=True,
        followlinks=False,
    ):
        current_path = Path(current)
        for name in directory_names:
            path = current_path / name
            if path.is_symlink():
                raise ValueError(
                    "quality review campaign cannot contain symlinks"
                )
        for name in file_names:
            path = current_path / name
            if path.is_symlink() or not path.is_file():
                raise ValueError(
                    "quality review campaign payload must be a regular file"
                )
            files.add(path.relative_to(root).as_posix())
    return files


def _write_exclusive(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "QualityReviewCampaignKit",
    "QualityReviewCampaignManifest",
    "initialize_quality_review_campaign",
    "validate_quality_review_campaign_owner_context",
    "verify_quality_review_campaign_readiness",
]
