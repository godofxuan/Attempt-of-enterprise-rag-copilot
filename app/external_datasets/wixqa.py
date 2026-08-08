from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enterprise_documents import EnterpriseDocument, RawProvenance


WIXQA_REVISION = "d662dc42479c14e202eccd832f8c4b66a035c4cc"
DEFAULT_WIXQA_ROOT = Path(".private/external/wixqa/source")
DEFAULT_WIXQA_MANIFEST = Path("data_manifests/WIXQA_MANIFEST.json")
WixQACohort = Literal["synthetic", "simulated", "expertwritten"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class WixQASourceFile(_StrictModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(ge=1)
    row_count: int = Field(ge=1)
    role: Literal["corpus", "development", "validation", "fixed_external"]


class WixQAManifest(_StrictModel):
    schema_version: Literal["wixqa_dataset_manifest_v1"]
    dataset_name: Literal["WixQA"]
    official_source: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    download_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    license: Literal["MIT"]
    source_commit: Literal[WIXQA_REVISION]
    acquisition: Literal["official_huggingface_dataset_repository"]
    number_of_documents: Literal[6221]
    number_of_questions: dict[str, int]
    official_split: dict[str, str]
    locally_used_split: dict[str, str]
    data_types: list[str] = Field(min_length=1)
    provenance: dict[str, str]
    files: list[WixQASourceFile] = Field(min_length=4, max_length=4)
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_contract(self) -> "WixQAManifest":
        expected_questions = {
            "synthetic": 6221,
            "simulated": 200,
            "expertwritten": 200,
        }
        if self.number_of_questions != expected_questions:
            raise ValueError("WixQA question counts do not match frozen contract")
        paths = [item.path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("WixQA manifest paths must be unique")
        if any(Path(path).is_absolute() or ".." in Path(path).parts for path in paths):
            raise ValueError("WixQA manifest paths must be confined relative paths")
        return self


class WixQARawArticle(_StrictModel):
    id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    contents: str = Field(min_length=1)
    title: str = Field(min_length=1)
    html_content: str = Field(min_length=1)
    article_type: Literal["article", "feature_request", "known_issue"]


class WixQARawQuestion(_StrictModel):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    article_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_articles(self) -> "WixQARawQuestion":
        if len(self.article_ids) != len(set(self.article_ids)):
            raise ValueError("WixQA article IDs must be unique within a question")
        return self


class WixQAQuestion(_StrictModel):
    question_id: str = Field(pattern=r"^wixqa:[a-z]+:[0-9a-f]{24}$")
    id_origin: Literal["derived_from_canonical_source_row_v1"] = (
        "derived_from_canonical_source_row_v1"
    )
    cohort: WixQACohort
    source_row: int = Field(ge=1)
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    article_ids: list[str] = Field(min_length=1)
    raw_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_wixqa_manifest(path: Path = DEFAULT_WIXQA_MANIFEST) -> WixQAManifest:
    return WixQAManifest.model_validate_json(Path(path).read_bytes())


def verify_wixqa_source(
    source_root: Path = DEFAULT_WIXQA_ROOT,
    manifest_path: Path = DEFAULT_WIXQA_MANIFEST,
) -> WixQAManifest:
    root = Path(source_root).resolve()
    manifest = load_wixqa_manifest(manifest_path)
    for item in manifest.files:
        path = (root / item.path).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("WixQA source path escapes source root") from exc
        if not path.is_file():
            raise FileNotFoundError(f"WixQA source file is missing: {item.path}")
        if path.stat().st_size != item.byte_count:
            raise ValueError(f"WixQA byte count mismatch: {item.path}")
        if sha256_file(path) != item.sha256:
            raise ValueError(f"WixQA SHA-256 mismatch: {item.path}")
        if _count_nonempty_lines(path) != item.row_count:
            raise ValueError(f"WixQA row count mismatch: {item.path}")
    return manifest


def load_wixqa_articles(
    source_root: Path = DEFAULT_WIXQA_ROOT,
) -> list[EnterpriseDocument]:
    relative = "wix_kb_corpus/wix_kb_corpus.jsonl"
    path = Path(source_root).resolve() / relative
    documents: list[EnterpriseDocument] = []
    for row_number, payload, raw_hash in _iter_jsonl(path):
        article = WixQARawArticle.model_validate(payload)
        documents.append(
            EnterpriseDocument(
                document_id=f"wixqa:article:{article.id}",
                source_type="support_article",
                source_native_id=article.id,
                title=article.title,
                text=article.contents,
                source_metadata={
                    "article_type": article.article_type,
                    "url": article.url,
                    "html_content": article.html_content,
                },
                raw_provenance=RawProvenance(
                    dataset_name="WixQA",
                    source_revision=WIXQA_REVISION,
                    source_file=relative,
                    source_row=row_number,
                    source_native_id=article.id,
                    raw_record_sha256=raw_hash,
                ),
            )
        )
    _require_unique((item.source_native_id for item in documents), "article ID")
    return documents


def load_wixqa_questions(
    cohort: WixQACohort,
    source_root: Path = DEFAULT_WIXQA_ROOT,
) -> list[WixQAQuestion]:
    relative = f"wixqa_{cohort}/test.jsonl"
    path = Path(source_root).resolve() / relative
    questions: list[WixQAQuestion] = []
    for row_number, payload, raw_hash in _iter_jsonl(path):
        raw = WixQARawQuestion.model_validate(payload)
        questions.append(
            WixQAQuestion(
                question_id=f"wixqa:{cohort}:{raw_hash[:24]}",
                cohort=cohort,
                source_row=row_number,
                question=raw.question,
                answer=raw.answer,
                article_ids=raw.article_ids,
                raw_record_sha256=raw_hash,
            )
        )
    _require_unique((item.question_id for item in questions), "derived question ID")
    return questions


def validate_wixqa_references(
    articles: Sequence[EnterpriseDocument],
    questions: Sequence[WixQAQuestion],
) -> None:
    known = {article.source_native_id for article in articles}
    missing = sorted(
        {
            article_id
            for question in questions
            for article_id in question.article_ids
            if article_id not in known
        }
    )
    if missing:
        raise ValueError(f"WixQA questions reference unknown articles: {missing[:5]}")


def question_ids_sha256(questions: Sequence[WixQAQuestion]) -> str:
    return hashlib.sha256(
        canonical_json_bytes([item.question_id for item in questions])
    ).hexdigest()


def _iter_jsonl(path: Path) -> Iterator[tuple[int, object, str]]:
    with Path(path).open("rb") as handle:
        for row_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            payload = json.loads(raw_line.decode("utf-8"))
            canonical = canonical_json_bytes(payload)
            yield row_number, payload, hashlib.sha256(canonical).hexdigest()


def _count_nonempty_lines(path: Path) -> int:
    with Path(path).open("rb") as handle:
        return sum(bool(line.strip()) for line in handle)


def _require_unique(values: Iterator[str], label: str) -> None:
    rows = list(values)
    if len(rows) != len(set(rows)):
        raise ValueError(f"WixQA {label} values must be unique")


__all__ = [
    "DEFAULT_WIXQA_MANIFEST",
    "DEFAULT_WIXQA_ROOT",
    "WIXQA_REVISION",
    "WixQAManifest",
    "WixQAQuestion",
    "load_wixqa_articles",
    "load_wixqa_manifest",
    "load_wixqa_questions",
    "question_ids_sha256",
    "validate_wixqa_references",
    "verify_wixqa_source",
]

