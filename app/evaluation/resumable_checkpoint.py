from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from collections.abc import Callable
from typing import Any, Mapping, Sequence, TypeVar

from pydantic import BaseModel


_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_RECORD_PATTERN = re.compile(r"^(\d{6})\.json$")
_SCHEMA_VERSION = "resumable_case_checkpoint_v1"
_ZERO_SHA256 = "0" * 64
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_RowT = TypeVar("_RowT", bound=BaseModel)
_CaseT = TypeVar("_CaseT")


class ResumableCaseCheckpoint:
    """Append-only, hash-chained per-case evaluation checkpoint."""

    def __init__(
        self,
        *,
        checkpoint_dir: Path,
        expected_case_ids: tuple[str, ...],
    ) -> None:
        self.checkpoint_dir = checkpoint_dir
        self.records_dir = checkpoint_dir / "records"
        self._expected_case_ids = expected_case_ids

    @classmethod
    def open(
        cls,
        *,
        root: Path,
        run_id: str,
        contract: Mapping[str, Any],
        expected_case_ids: Sequence[str],
    ) -> ResumableCaseCheckpoint:
        if not _RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError("checkpoint run_id contains unsafe characters")
        case_ids = tuple(expected_case_ids)
        if not case_ids or any(not case_id for case_id in case_ids):
            raise ValueError("checkpoint expected_case_ids must be non-empty")
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("checkpoint expected_case_ids must be unique")

        checkpoint_dir = Path(root).resolve() / run_id
        records_dir = checkpoint_dir / "records"
        records_dir.mkdir(parents=True, exist_ok=True)
        cls._remove_uncommitted_files(checkpoint_dir)
        cls._remove_uncommitted_files(records_dir)

        contract_payload = {
            "schema_version": _SCHEMA_VERSION,
            "run_id": run_id,
            "selected_case_count": len(case_ids),
            "selected_case_ids_sha256": _case_ids_sha256(case_ids),
            "contract": dict(contract),
        }
        contract_bytes = _canonical_json_bytes(contract_payload) + b"\n"
        contract_path = checkpoint_dir / "contract.json"
        if contract_path.exists():
            if contract_path.read_bytes() != contract_bytes:
                raise ValueError("checkpoint contract does not match existing run")
        else:
            _commit_new_file(contract_path, contract_bytes)

        checkpoint = cls(
            checkpoint_dir=checkpoint_dir,
            expected_case_ids=case_ids,
        )
        checkpoint._load_envelopes()
        checkpoint._validate_seal()
        return checkpoint

    @property
    def completed_count(self) -> int:
        return len(self._load_envelopes())

    def append(self, row: BaseModel) -> None:
        if self.seal_path.exists():
            raise ValueError("checkpoint is sealed")
        envelopes = self._load_envelopes()
        ordinal = len(envelopes) + 1
        if ordinal > len(self._expected_case_ids):
            raise ValueError("checkpoint already contains every expected case")

        row_data = row.model_dump(mode="json")
        case_id = row_data.get("case_id")
        expected_case_id = self._expected_case_ids[ordinal - 1]
        if case_id != expected_case_id:
            raise ValueError(
                "checkpoint row case_id does not match expected case order"
            )
        row_bytes = _canonical_json_bytes(row_data)
        previous_sha256 = (
            _file_sha256(self.records_dir / f"{ordinal - 1:06d}.json")
            if ordinal > 1
            else _ZERO_SHA256
        )
        envelope = {
            "schema_version": _SCHEMA_VERSION,
            "ordinal": ordinal,
            "case_id": case_id,
            "previous_record_sha256": previous_sha256,
            "row_sha256": hashlib.sha256(row_bytes).hexdigest(),
            "row": row_data,
        }
        _commit_new_file(
            self.records_dir / f"{ordinal:06d}.json",
            _canonical_json_bytes(envelope) + b"\n",
        )

    @property
    def seal_path(self) -> Path:
        return self.checkpoint_dir / "seal.json"

    def seal(
        self,
        *,
        final_manifest_sha256: str,
        final_details_sha256: str,
    ) -> None:
        if not _SHA256_PATTERN.fullmatch(final_manifest_sha256):
            raise ValueError("final_manifest_sha256 must be lowercase SHA-256")
        if not _SHA256_PATTERN.fullmatch(final_details_sha256):
            raise ValueError("final_details_sha256 must be lowercase SHA-256")
        envelopes = self._load_envelopes()
        if len(envelopes) != len(self._expected_case_ids):
            raise ValueError("checkpoint cannot be sealed before all cases")
        seal = {
            "schema_version": _SCHEMA_VERSION,
            "selected_case_count": len(envelopes),
            "record_chain_head_sha256": _file_sha256(
                self.records_dir / f"{len(envelopes):06d}.json"
            ),
            "final_manifest_sha256": final_manifest_sha256,
            "final_details_sha256": final_details_sha256,
        }
        payload = _canonical_json_bytes(seal) + b"\n"
        if self.seal_path.exists():
            if self.seal_path.read_bytes() != payload:
                raise ValueError("checkpoint seal does not match final run")
            return
        _commit_new_file(self.seal_path, payload)

    def load_rows(self, row_type: type[_RowT]) -> list[_RowT]:
        return [
            row_type.model_validate(envelope["row"])
            for envelope in self._load_envelopes()
        ]

    def _load_envelopes(self) -> list[dict[str, Any]]:
        record_paths = sorted(self.records_dir.glob("*.json"))
        envelopes: list[dict[str, Any]] = []
        previous_sha256 = _ZERO_SHA256
        for ordinal, path in enumerate(record_paths, start=1):
            match = _RECORD_PATTERN.fullmatch(path.name)
            if match is None or int(match.group(1)) != ordinal:
                raise ValueError("checkpoint records are not contiguous")
            try:
                envelope = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("checkpoint record is unreadable") from exc
            if (
                envelope.get("schema_version") != _SCHEMA_VERSION
                or envelope.get("ordinal") != ordinal
                or envelope.get("case_id")
                != self._expected_case_ids[ordinal - 1]
                or envelope.get("previous_record_sha256") != previous_sha256
            ):
                raise ValueError("checkpoint record contract is invalid")
            row = envelope.get("row")
            row_bytes = _canonical_json_bytes(row)
            if envelope.get("row_sha256") != hashlib.sha256(
                row_bytes
            ).hexdigest():
                raise ValueError("checkpoint row hash mismatch")
            envelopes.append(envelope)
            previous_sha256 = _file_sha256(path)
        if len(envelopes) > len(self._expected_case_ids):
            raise ValueError("checkpoint contains unexpected extra cases")
        return envelopes

    def _validate_seal(self) -> None:
        if not self.seal_path.exists():
            return
        try:
            seal = json.loads(self.seal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("checkpoint seal is unreadable") from exc
        envelopes = self._load_envelopes()
        if not envelopes:
            raise ValueError("checkpoint seal has no records")
        expected = {
            "schema_version": _SCHEMA_VERSION,
            "selected_case_count": len(envelopes),
            "record_chain_head_sha256": _file_sha256(
                self.records_dir / f"{len(envelopes):06d}.json"
            ),
            "final_manifest_sha256": seal.get("final_manifest_sha256"),
            "final_details_sha256": seal.get("final_details_sha256"),
        }
        if (
            seal != expected
            or len(envelopes) != len(self._expected_case_ids)
            or not _SHA256_PATTERN.fullmatch(
                str(seal.get("final_manifest_sha256", ""))
            )
            or not _SHA256_PATTERN.fullmatch(
                str(seal.get("final_details_sha256", ""))
            )
        ):
            raise ValueError("checkpoint seal contract is invalid")

    @staticmethod
    def _remove_uncommitted_files(directory: Path) -> None:
        for path in directory.glob(".pending-*.tmp"):
            path.unlink()


def _commit_new_file(path: Path, payload: bytes) -> None:
    pending = path.parent / f".pending-{uuid.uuid4().hex}.tmp"
    try:
        with pending.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(pending, path)
        except FileExistsError as exc:
            raise ValueError(
                f"checkpoint artifact already exists: {path.name}"
            ) from exc
    finally:
        pending.unlink(missing_ok=True)


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _case_ids_sha256(case_ids: Sequence[str]) -> str:
    return hashlib.sha256(
        "\n".join(case_ids).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_resumable_cases(
    *,
    checkpoint: ResumableCaseCheckpoint,
    row_type: type[_RowT],
    cases: Sequence[_CaseT],
    evaluate: Callable[[int, _CaseT], _RowT],
) -> list[_RowT]:
    rows = checkpoint.load_rows(row_type)
    if len(rows) > len(cases):
        raise ValueError("checkpoint contains more rows than input cases")
    for index in range(len(rows), len(cases)):
        row = evaluate(index, cases[index])
        checkpoint.append(row)
        rows.append(row)
    return rows


__all__ = ["ResumableCaseCheckpoint", "run_resumable_cases"]
