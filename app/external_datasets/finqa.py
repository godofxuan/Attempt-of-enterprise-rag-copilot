from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Literal

import requests
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


FINQA_REPOSITORY = "https://github.com/czyssrs/FinQA"
FINQA_REVISION = "0f16e2867befa6840783e58be38c9efb9229d742"
FINQA_DEV_SHA256 = (
    "a847fb7e0d61a3125a1e2909852df6b89f1ee64d2c5ff1bf689e332214deee51"
)
FINQA_TEST_SHA256 = (
    "831dbfb2e785dbc227f895ce3f24046433467aec67b09db2bd6ac7692a8a30dc"
)
DEFAULT_PRIVATE_ROOT = (
    Path(__file__).resolve().parents[2]
    / ".private"
    / "external_datasets"
    / "finqa"
)
DEFAULT_SOURCE_ROOT = DEFAULT_PRIVATE_ROOT / "upstream" / FINQA_REVISION

_MAX_SPLIT_BYTES = 64 * 1024 * 1024
_UNIT_ID = re.compile(r"^(?:text|table)_[0-9]+$")
_RAW_BASE_URL = (
    "https://raw.githubusercontent.com/czyssrs/FinQA/"
    f"{FINQA_REVISION}/dataset"
)


class FinQAModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FinQAQuestion(FinQAModel):
    question: str = Field(min_length=1)
    answer: str
    explanation: str
    ann_table_rows: list[Any]
    ann_text_rows: list[Any]
    steps: list[Any]
    program: str = Field(min_length=1)
    gold_inds: dict[str, str] = Field(min_length=1)
    exe_ans: int | float | str
    tfidftopn: dict[str, Any]
    program_re: str = Field(min_length=1)
    model_input: list[Any]

    @field_validator("exe_ans")
    @classmethod
    def validate_execution_answer(cls, value: int | float | str) -> int | float | str:
        if isinstance(value, bool):
            raise ValueError("FinQA execution answer must not be boolean")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("FinQA execution answer must be finite")
        if isinstance(value, str) and not value:
            raise ValueError("FinQA execution answer string must be non-empty")
        return value

    @field_validator("gold_inds")
    @classmethod
    def validate_gold_ids(cls, value: dict[str, str]) -> dict[str, str]:
        if any(
            not _UNIT_ID.fullmatch(unit_id) or not text
            for unit_id, text in value.items()
        ):
            raise ValueError("FinQA gold evidence contains an invalid unit")
        return value


class FinQACase(FinQAModel):
    pre_text: list[str]
    post_text: list[str]
    filename: str = Field(min_length=1)
    table_ori: list[list[str]] = Field(min_length=1)
    table: list[list[str]] = Field(min_length=1)
    qa: FinQAQuestion
    id: str = Field(min_length=1)
    table_retrieved: list[Any]
    text_retrieved: list[Any]
    table_retrieved_all: list[Any]
    text_retrieved_all: list[Any]

    @model_validator(mode="after")
    def validate_table(self) -> "FinQACase":
        width = len(self.table[0])
        if (
            width < 2
            or any(len(row) != width for row in self.table)
            or any(not row[0] for row in self.table[1:])
        ):
            raise ValueError("FinQA table must be rectangular and non-empty")
        return self


class FinQAEvidenceUnit(FinQAModel):
    unit_id: str = Field(pattern=r"^(?:text|table)_[0-9]+$")
    kind: Literal["text", "table"]
    ordinal: int = Field(ge=0)
    text: str = Field(min_length=1)


def load_finqa_split(
    path: Path,
    *,
    expected_sha256: str | None = None,
) -> tuple[list[FinQACase], str]:
    path = Path(path)
    content = path.read_bytes()
    if not content or len(content) > _MAX_SPLIT_BYTES:
        raise ValueError("FinQA split is empty or exceeds its byte budget")
    digest = hashlib.sha256(content).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError(
            "pinned FinQA split hash mismatch: "
            f"expected {expected_sha256}, got {digest}"
        )
    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("FinQA split is not canonical UTF-8 JSON") from exc
    if not isinstance(payload, list) or not payload:
        raise ValueError("FinQA split must be a non-empty JSON array")
    cases = [FinQACase.model_validate(item) for item in payload]
    case_ids = [case.id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("FinQA case IDs must be unique")
    for case in cases:
        validate_finqa_gold_evidence(case)
    return cases, digest


def download_finqa_split(
    *,
    split: Literal["dev", "test"],
    source_root: Path = DEFAULT_SOURCE_ROOT,
    allow_test: bool = False,
    session: requests.Session | None = None,
) -> tuple[Path, str, int]:
    if split == "test" and not allow_test:
        raise ValueError("FinQA test download requires explicit confirmation")
    expected_sha256 = (
        FINQA_DEV_SHA256 if split == "dev" else FINQA_TEST_SHA256
    )
    target = Path(source_root).resolve() / "dataset" / f"{split}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        content = target.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if (
            not content
            or len(content) > _MAX_SPLIT_BYTES
            or digest != expected_sha256
        ):
            raise ValueError("existing FinQA split does not match pinned bytes")
        return target, digest, len(content)

    client = session or requests.Session()
    client.trust_env = False
    response = client.get(
        f"{_RAW_BASE_URL}/{split}.json",
        stream=True,
        timeout=(5, 60),
        allow_redirects=False,
    )
    response.raise_for_status()
    if response.is_redirect:
        raise ValueError("FinQA split download must not follow redirects")
    digest_builder = hashlib.sha256()
    byte_count = 0
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{split}.",
        suffix=".download",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                byte_count += len(chunk)
                if byte_count > _MAX_SPLIT_BYTES:
                    raise ValueError("FinQA split exceeds its download byte budget")
                digest_builder.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        digest = digest_builder.hexdigest()
        if not byte_count or digest != expected_sha256:
            raise ValueError("downloaded FinQA split hash does not match pin")
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target, digest, byte_count


def build_finqa_evidence_units(case: FinQACase) -> tuple[FinQAEvidenceUnit, ...]:
    units = [
        FinQAEvidenceUnit(
            unit_id=f"text_{index}",
            kind="text",
            ordinal=index,
            text=text,
        )
        for index, text in enumerate([*case.pre_text, *case.post_text])
        if text.strip()
    ]
    header = case.table[0]
    units.extend(
        FinQAEvidenceUnit(
            unit_id=f"table_{index}",
            kind="table",
            ordinal=index,
            text=table_row_to_text(header, row),
        )
        for index, row in enumerate(case.table)
    )
    unit_ids = [unit.unit_id for unit in units]
    if len(unit_ids) != len(set(unit_ids)):
        raise ValueError("FinQA evidence unit IDs must be unique")
    return tuple(units)


def validate_finqa_gold_evidence(case: FinQACase) -> None:
    units = {unit.unit_id: unit.text for unit in build_finqa_evidence_units(case)}
    missing = sorted(set(case.qa.gold_inds) - set(units))
    if missing:
        raise ValueError(
            "FinQA gold evidence references missing units: " + ", ".join(missing)
        )
    mismatched = sorted(
        unit_id
        for unit_id, expected_text in case.qa.gold_inds.items()
        if _normalize_alignment(units[unit_id])
        != _normalize_alignment(expected_text)
    )
    if mismatched:
        raise ValueError(
            "FinQA gold evidence text does not match source units: "
            + ", ".join(mismatched)
        )


def stable_sample_finqa_cases(
    cases: list[FinQACase],
    *,
    count: int,
    seed: str,
) -> list[FinQACase]:
    if not seed or len(seed) > 200:
        raise ValueError("FinQA sample seed must contain 1-200 characters")
    if not 1 <= count <= len(cases):
        raise ValueError("FinQA sample count is outside the dataset bounds")
    return sorted(
        cases,
        key=lambda case: (
            hashlib.sha256(f"{seed}:{case.id}".encode("utf-8")).hexdigest(),
            case.id,
        ),
    )[:count]


def table_row_to_text(header: list[str], row: list[str]) -> str:
    if len(header) != len(row) or len(header) < 2:
        raise ValueError("FinQA table header and row must have equal width")
    prefix = f"{header[0]} " if header[0] else ""
    cells = "".join(
        f"the {row[0]} of {heading} is {cell} ; "
        for heading, cell in zip(header[1:], row[1:], strict=True)
    )
    return _normalize_space(prefix + cells)


def _normalize_space(value: str) -> str:
    return " ".join(value.split())


def _normalize_alignment(value: str) -> str:
    return re.sub(r"\s+([,.;:!?])", r"\1", _normalize_space(value)).casefold()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


__all__ = [
    "DEFAULT_PRIVATE_ROOT",
    "DEFAULT_SOURCE_ROOT",
    "FINQA_DEV_SHA256",
    "FINQA_REPOSITORY",
    "FINQA_REVISION",
    "FINQA_TEST_SHA256",
    "FinQACase",
    "FinQAEvidenceUnit",
    "FinQAQuestion",
    "build_finqa_evidence_units",
    "download_finqa_split",
    "load_finqa_split",
    "stable_sample_finqa_cases",
    "table_row_to_text",
    "validate_finqa_gold_evidence",
]
