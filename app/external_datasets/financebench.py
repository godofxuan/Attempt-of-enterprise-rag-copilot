from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal, TypeVar
from urllib.parse import quote, urlsplit

import requests
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
)

from app.corpus.eval_cases import build_test_manifest_line
from app.corpus.schemas import (
    CorpusManifest,
    DocumentMetadata,
    EvalCase,
    EvalUserContext,
    ManifestDocument,
)
from app.retrieval.entity_scope import (
    EntityCatalog,
    EntityCatalogEntry,
    EntityDocumentBinding,
)


FINANCEBENCH_REPOSITORY = "https://github.com/patronus-ai/financebench"
FINANCEBENCH_REVISION = "cc39aeb4afdf33909ee1412188bf89035950c2eb"
FINANCEBENCH_COMMITTED_AT = datetime(
    2024,
    12,
    3,
    17,
    29,
    1,
    tzinfo=timezone.utc,
)

_FINANCEBENCH_ENTITY_ALIASES: dict[str, tuple[str, ...]] = {
    "American Express": ("AMEX",),
    "Johnson & Johnson": ("JnJ", "J&J"),
}
FINANCEBENCH_QUESTIONS_SHA256 = (
    "a5a2aa673e573e55675fc3c0f9aa38c1cf59d2abc91edb077534f71f10a71877"
)
FINANCEBENCH_DOCUMENTS_SHA256 = (
    "1c69127783879de8cdadb159d2181f39bc3123b8e0ebf74031c3969d69189575"
)
FINANCEBENCH_PROFILE_ID = f"external_financebench_open_{FINANCEBENCH_REVISION[:12]}"
FINANCEBENCH_TENANT = "financebench-public"
FINANCEBENCH_REGION = "global"
FINANCEBENCH_ACL_GROUP = "public_benchmark"
DEFAULT_PRIVATE_ROOT = (
    Path(__file__).resolve().parents[2]
    / ".private"
    / "external_datasets"
    / "financebench"
)
DEFAULT_SOURCE_ROOT = DEFAULT_PRIVATE_ROOT / "upstream" / FINANCEBENCH_REVISION
DEFAULT_PREPARED_ROOT = DEFAULT_PRIVATE_ROOT / "prepared" / FINANCEBENCH_REVISION

_QUESTIONS_RELATIVE_PATH = Path("data") / "financebench_open_source.jsonl"
_DOCUMENTS_RELATIVE_PATH = (
    Path("data") / "financebench_document_information.jsonl"
)
_RAW_BASE_URL = (
    "https://raw.githubusercontent.com/patronus-ai/financebench/"
    f"{FINANCEBENCH_REVISION}"
)
_MAX_JSONL_BYTES = 8 * 1024 * 1024
_MAX_PDF_BYTES = 16 * 1024 * 1024
_MAX_TOTAL_PDF_BYTES = 256 * 1024 * 1024
_ID_COMPONENT = re.compile(r"[^a-z0-9]+")


class FinanceBenchModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FinanceBenchEvidence(FinanceBenchModel):
    evidence_text: str = Field(min_length=1)
    evidence_doc_name: str = Field(
        min_length=1,
        validation_alias=AliasChoices("evidence_doc_name", "doc_name"),
    )
    evidence_page_num: int = Field(ge=0)
    evidence_text_full_page: str = Field(min_length=1)


class FinanceBenchQuestion(FinanceBenchModel):
    financebench_id: str = Field(min_length=1)
    company: str = Field(min_length=1)
    doc_name: str = Field(min_length=1)
    question_type: str = Field(min_length=1)
    question_reasoning: str | None = None
    domain_question_num: str | None = None
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    justification: str | None = None
    dataset_subset_label: Literal["OPEN_SOURCE"]
    evidence: list[FinanceBenchEvidence] = Field(min_length=1)


class FinanceBenchDocumentInformation(FinanceBenchModel):
    doc_name: str = Field(min_length=1)
    company: str = Field(min_length=1)
    gics_sector: str = Field(min_length=1)
    doc_type: str = Field(min_length=1)
    doc_period: int = Field(ge=1900, le=2200)
    doc_link: str = Field(min_length=1)


class FinanceBenchPreparedEvidence(FinanceBenchModel):
    doc_id: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    evidence_text: str = Field(min_length=1)
    evidence_text_full_page: str = Field(min_length=1)


class FinanceBenchPreparedCase(FinanceBenchModel):
    schema_version: Literal["financebench_case_v1"] = "financebench_case_v1"
    case_id: str = Field(min_length=1)
    split: Literal["dev", "test"]
    company: str = Field(min_length=1)
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    justification: str | None = None
    question_type: str = Field(min_length=1)
    question_reasoning: str | None = None
    gold_doc_ids: list[str] = Field(min_length=1)
    evidence: list[FinanceBenchPreparedEvidence] = Field(min_length=1)


class FinanceBenchDatasetManifest(FinanceBenchModel):
    schema_version: Literal["financebench_external_dataset_v1"] = (
        "financebench_external_dataset_v1"
    )
    dataset: Literal["financebench_open_source"] = "financebench_open_source"
    repository: Literal[
        "https://github.com/patronus-ai/financebench"
    ] = FINANCEBENCH_REPOSITORY
    revision: Literal[
        "cc39aeb4afdf33909ee1412188bf89035950c2eb"
    ] = FINANCEBENCH_REVISION
    revision_committed_at: datetime = FINANCEBENCH_COMMITTED_AT
    questions_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_information_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    split_strategy: Literal["company_grouped_stable_hash_v1"] = (
        "company_grouped_stable_hash_v1"
    )
    split_seed: int
    question_count: int = Field(ge=1)
    document_count: int = Field(ge=1)
    company_count: int = Field(ge=2)
    dev_question_count: int = Field(ge=1)
    test_question_count: int = Field(ge=1)
    dev_company_count: int = Field(ge=1)
    test_company_count: int = Field(ge=1)
    pdf_total_bytes: int = Field(ge=1)
    test_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class FinanceBenchPreparationResult(FinanceBenchModel):
    source_root: Path
    prepared_root: Path
    manifest: FinanceBenchDatasetManifest


ModelT = TypeVar("ModelT", bound=BaseModel)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    elif isinstance(value, list):
        value = [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item
            for item in value
        ]
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


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_jsonl(
    path: Path,
    model: type[ModelT],
    *,
    expected_sha256: str | None,
) -> tuple[list[ModelT], str]:
    path = Path(path)
    content = path.read_bytes()
    if not content or len(content) > _MAX_JSONL_BYTES:
        raise ValueError(f"JSONL file is empty or exceeds its byte budget: {path.name}")
    actual_sha256 = _sha256(content)
    if expected_sha256 is not None and actual_sha256 != expected_sha256:
        raise ValueError(
            f"pinned upstream hash mismatch for {path.name}: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"JSONL file is not UTF-8: {path.name}") from exc
    lines = text.splitlines()
    if not lines or any(not line.strip() for line in lines):
        raise ValueError(f"JSONL file contains blank records: {path.name}")
    result: list[ModelT] = []
    try:
        for line in lines:
            payload = json.loads(line, object_pairs_hook=_unique_object)
            result.append(model.model_validate(payload))
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ValueError(f"invalid FinanceBench JSONL: {path.name}") from exc
    return result, actual_sha256


def load_financebench_upstream(
    source_root: Path,
    *,
    verify_pinned_hashes: bool = True,
) -> tuple[
    list[FinanceBenchQuestion],
    dict[str, FinanceBenchDocumentInformation],
    str,
    str,
]:
    source_root = Path(source_root).resolve()
    questions, questions_sha256 = _read_jsonl(
        source_root / _QUESTIONS_RELATIVE_PATH,
        FinanceBenchQuestion,
        expected_sha256=(
            FINANCEBENCH_QUESTIONS_SHA256 if verify_pinned_hashes else None
        ),
    )
    documents, documents_sha256 = _read_jsonl(
        source_root / _DOCUMENTS_RELATIVE_PATH,
        FinanceBenchDocumentInformation,
        expected_sha256=(
            FINANCEBENCH_DOCUMENTS_SHA256 if verify_pinned_hashes else None
        ),
    )
    question_ids = [item.financebench_id for item in questions]
    if len(question_ids) != len(set(question_ids)):
        raise ValueError("FinanceBench question IDs are not unique")
    referenced = {
        evidence.evidence_doc_name
        for item in questions
        for evidence in item.evidence
    } | {item.doc_name for item in questions}
    documents_by_name: dict[
        str,
        list[FinanceBenchDocumentInformation],
    ] = defaultdict(list)
    for item in documents:
        documents_by_name[item.doc_name].append(item)
    conflicting_referenced = sorted(
        doc_name
        for doc_name, rows in documents_by_name.items()
        if (
            doc_name in referenced
            and len(
                {
                    json.dumps(
                        row.model_dump(mode="json"),
                        ensure_ascii=True,
                        sort_keys=True,
                    )
                    for row in rows
                }
            )
            > 1
        )
    )
    if conflicting_referenced:
        raise ValueError(
            "FinanceBench has conflicting metadata for referenced documents: "
            + ", ".join(conflicting_referenced)
        )
    document_by_name = {
        doc_name: rows[0]
        for doc_name, rows in documents_by_name.items()
    }
    missing_metadata = sorted(referenced - set(document_by_name))
    if missing_metadata:
        raise ValueError(
            "FinanceBench questions reference documents without metadata: "
            + ", ".join(missing_metadata)
        )
    for item in questions:
        metadata = document_by_name[item.doc_name]
        if metadata.company != item.company:
            raise ValueError(
                f"company mismatch for FinanceBench document {item.doc_name}"
            )
    return (
        questions,
        document_by_name,
        questions_sha256,
        documents_sha256,
    )


def _download_file(
    session: requests.Session,
    *,
    url: str,
    target: Path,
    max_bytes: int,
    expected_sha256: str | None = None,
    require_pdf: bool = False,
) -> tuple[int, str]:
    target = Path(target)
    if target.is_file():
        existing = target.read_bytes()
        existing_sha256 = _sha256(existing)
        if (
            len(existing) <= max_bytes
            and (expected_sha256 is None or existing_sha256 == expected_sha256)
            and (not require_pdf or existing.startswith(b"%PDF-"))
        ):
            return len(existing), existing_sha256

    target.parent.mkdir(parents=True, exist_ok=True)
    response = session.get(
        url,
        stream=True,
        timeout=(10, 120),
        headers={"User-Agent": "Enterprise-Agentic-RAG-FinanceBench-Adapter/1.0"},
    )
    try:
        response.raise_for_status()
        final_url = urlsplit(response.url)
        if (
            final_url.scheme != "https"
            or final_url.hostname != "raw.githubusercontent.com"
        ):
            raise ValueError("FinanceBench download escaped the pinned HTTPS origin")
        declared_length = response.headers.get("Content-Length")
        if declared_length is not None and int(declared_length) > max_bytes:
            raise ValueError(f"download exceeds byte budget: {target.name}")

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.download-",
            dir=target.parent,
        )
        digest = hashlib.sha256()
        total = 0
        prefix = b""
        try:
            with os.fdopen(descriptor, "wb") as output:
                for block in response.iter_content(chunk_size=64 * 1024):
                    if not block:
                        continue
                    total += len(block)
                    if total > max_bytes:
                        raise ValueError(f"download exceeds byte budget: {target.name}")
                    if len(prefix) < 5:
                        prefix = (prefix + block)[:5]
                    digest.update(block)
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            actual_sha256 = digest.hexdigest()
            if expected_sha256 is not None and actual_sha256 != expected_sha256:
                raise ValueError(f"download hash mismatch: {target.name}")
            if require_pdf and prefix != b"%PDF-":
                raise ValueError(f"download is not a PDF: {target.name}")
            os.replace(temporary_name, target)
            return total, actual_sha256
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
    finally:
        response.close()


def download_financebench(
    source_root: Path = DEFAULT_SOURCE_ROOT,
) -> dict[str, int | str]:
    source_root = Path(source_root).resolve()
    source_root.mkdir(parents=True, exist_ok=True)
    with requests.Session() as session:
        _download_file(
            session,
            url=f"{_RAW_BASE_URL}/{_QUESTIONS_RELATIVE_PATH.as_posix()}",
            target=source_root / _QUESTIONS_RELATIVE_PATH,
            max_bytes=_MAX_JSONL_BYTES,
            expected_sha256=FINANCEBENCH_QUESTIONS_SHA256,
        )
        _download_file(
            session,
            url=f"{_RAW_BASE_URL}/{_DOCUMENTS_RELATIVE_PATH.as_posix()}",
            target=source_root / _DOCUMENTS_RELATIVE_PATH,
            max_bytes=_MAX_JSONL_BYTES,
            expected_sha256=FINANCEBENCH_DOCUMENTS_SHA256,
        )
        questions, _, _, _ = load_financebench_upstream(source_root)
        document_names = sorted(
            {
                item.doc_name
                for item in questions
            }
            | {
                evidence.evidence_doc_name
                for item in questions
                for evidence in item.evidence
            }
        )
        total_bytes = 0
        for doc_name in document_names:
            filename = f"{doc_name}.pdf"
            byte_count, _ = _download_file(
                session,
                url=f"{_RAW_BASE_URL}/pdfs/{quote(filename)}",
                target=source_root / "pdfs" / filename,
                max_bytes=_MAX_PDF_BYTES,
                require_pdf=True,
            )
            total_bytes += byte_count
            if total_bytes > _MAX_TOTAL_PDF_BYTES:
                raise ValueError("FinanceBench PDF set exceeds its total byte budget")
    return {
        "revision": FINANCEBENCH_REVISION,
        "question_count": len(questions),
        "document_count": len(document_names),
        "pdf_total_bytes": total_bytes,
    }


def _doc_id(doc_name: str) -> str:
    return f"financebench::{doc_name}"


def _policy_id(doc_name: str) -> str:
    slug = _ID_COMPONENT.sub("-", doc_name.casefold()).strip("-")
    return f"financebench-filing::{slug}"


def _stable_company_split(
    questions: Iterable[FinanceBenchQuestion],
    *,
    seed: int,
    dev_ratio: float,
) -> dict[str, Literal["dev", "test"]]:
    if not 0.1 <= dev_ratio <= 0.5:
        raise ValueError("dev_ratio must be between 0.1 and 0.5")
    counts: dict[str, int] = defaultdict(int)
    for item in questions:
        counts[item.company] += 1
    if len(counts) < 2:
        raise ValueError("company-grouped split requires at least two companies")
    ranked = sorted(
        counts,
        key=lambda company: (
            hashlib.sha256(f"{seed}:{company}".encode("utf-8")).hexdigest(),
            company,
        ),
    )
    target = sum(counts.values()) * dev_ratio
    cumulative = 0
    candidates: list[tuple[float, int, int]] = []
    for index, company in enumerate(ranked[:-1], start=1):
        cumulative += counts[company]
        candidates.append((abs(cumulative - target), cumulative, index))
    _, _, boundary = min(candidates)
    dev_companies = set(ranked[:boundary])
    return {
        company: ("dev" if company in dev_companies else "test")
        for company in ranked
    }


def _task_type(item: FinanceBenchQuestion) -> Literal["fact_lookup", "comparison"]:
    reasoning = (item.question_reasoning or "").casefold()
    if "numerical" in reasoning or "logical" in reasoning:
        return "comparison"
    return "fact_lookup"


def _eval_case(
    item: FinanceBenchQuestion,
) -> EvalCase:
    gold_doc_ids = sorted(
        {_doc_id(evidence.evidence_doc_name) for evidence in item.evidence}
    )
    reasoning_tag = _ID_COMPONENT.sub(
        "_",
        (item.question_reasoning or "unspecified").casefold(),
    ).strip("_")
    return EvalCase(
        case_id=item.financebench_id,
        question=item.question,
        task_type=_task_type(item),
        answer_mode="answered",
        user_context=EvalUserContext(
            user_id="financebench-evaluator",
            tenant=FINANCEBENCH_TENANT,
            region=FINANCEBENCH_REGION,
            groups=[FINANCEBENCH_ACL_GROUP],
        ),
        required_fact_ids=[item.financebench_id],
        gold_doc_ids=gold_doc_ids,
        distractor_doc_ids=[],
        forbidden_doc_ids=[],
        expected_answer=item.answer,
        expected_filters={
            "tenant": FINANCEBENCH_TENANT,
            "region": FINANCEBENCH_REGION,
            "acl_groups": [FINANCEBENCH_ACL_GROUP],
        },
        expected_authority_doc_ids=gold_doc_ids,
        tags=[
            "external",
            "financebench",
            item.question_type.casefold(),
            reasoning_tag or "unspecified",
        ],
    )


def _prepared_case(
    item: FinanceBenchQuestion,
    split: Literal["dev", "test"],
) -> FinanceBenchPreparedCase:
    evidence = [
        FinanceBenchPreparedEvidence(
            doc_id=_doc_id(source.evidence_doc_name),
            page_number=source.evidence_page_num + 1,
            evidence_text=source.evidence_text,
            evidence_text_full_page=source.evidence_text_full_page,
        )
        for source in item.evidence
    ]
    return FinanceBenchPreparedCase(
        case_id=item.financebench_id,
        split=split,
        company=item.company,
        question=item.question,
        answer=item.answer,
        justification=item.justification,
        question_type=item.question_type,
        question_reasoning=item.question_reasoning,
        gold_doc_ids=sorted({source.doc_id for source in evidence}),
        evidence=evidence,
    )


def _build_corpus_manifest(
    source_root: Path,
    questions: list[FinanceBenchQuestion],
    metadata_by_name: dict[str, FinanceBenchDocumentInformation],
    *,
    questions_sha256: str,
    split_seed: int,
) -> tuple[CorpusManifest, int]:
    fact_ids_by_doc: dict[str, set[str]] = defaultdict(set)
    for item in questions:
        for evidence in item.evidence:
            fact_ids_by_doc[evidence.evidence_doc_name].add(item.financebench_id)

    documents: list[ManifestDocument] = []
    total_bytes = 0
    for doc_name in sorted(fact_ids_by_doc):
        metadata = metadata_by_name[doc_name]
        relative_path = Path("pdfs") / f"{doc_name}.pdf"
        pdf_path = source_root / relative_path
        content = pdf_path.read_bytes()
        if (
            not content.startswith(b"%PDF-")
            or len(content) > _MAX_PDF_BYTES
        ):
            raise ValueError(f"invalid or oversized FinanceBench PDF: {doc_name}")
        total_bytes += len(content)
        if total_bytes > _MAX_TOTAL_PDF_BYTES:
            raise ValueError("FinanceBench PDF set exceeds its total byte budget")
        documents.append(
            ManifestDocument(
                doc_id=_doc_id(doc_name),
                path=relative_path.as_posix(),
                sha256=_sha256(content),
                byte_count=len(content),
                format="pdf",
                source_type="filing",
                variant="authoritative",
                metadata=DocumentMetadata(
                    policy_id=_policy_id(doc_name),
                    version_id=_doc_id(doc_name),
                    version=str(metadata.doc_period),
                    status="active",
                    effective_from=date(metadata.doc_period, 1, 1),
                    effective_to=None,
                    authority=95,
                    supersedes=None,
                    actual_department="finance",
                    filed_department="finance",
                    tenant=FINANCEBENCH_TENANT,
                    region=FINANCEBENCH_REGION,
                    acl_groups=[FINANCEBENCH_ACL_GROUP],
                    variant="authoritative",
                    duplicate_of=None,
                ),
                fact_ids=sorted(fact_ids_by_doc[doc_name]),
            )
        )
    profile_payload = {
        "adapter": "financebench_v1",
        "revision": FINANCEBENCH_REVISION,
        "split_seed": split_seed,
        "document_count": len(documents),
    }
    manifest = CorpusManifest(
        schema_version="enterprise_corpus_manifest_v1",
        producer="enterprise_agentic_rag_v2",
        generator_version="financebench_adapter_v1",
        profile_id=FINANCEBENCH_PROFILE_ID,
        seed=split_seed,
        facts_sha256=questions_sha256,
        profile_sha256=_sha256(_canonical_json_bytes(profile_payload)),
        document_count=len(documents),
        counts_by_format={"pdf": len(documents)},
        counts_by_source_type={"filing": len(documents)},
        counts_by_variant={"authoritative": len(documents)},
        documents=documents,
    )
    return manifest, total_bytes


def prepare_financebench(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    prepared_root: Path = DEFAULT_PREPARED_ROOT,
    *,
    split_seed: int = 20260728,
    dev_ratio: float = 1 / 3,
    verify_pinned_hashes: bool = True,
) -> FinanceBenchPreparationResult:
    source_root = Path(source_root).resolve()
    prepared_root = Path(prepared_root).resolve()
    questions, metadata_by_name, questions_sha256, documents_sha256 = (
        load_financebench_upstream(
            source_root,
            verify_pinned_hashes=verify_pinned_hashes,
        )
    )
    split_by_company = _stable_company_split(
        questions,
        seed=split_seed,
        dev_ratio=dev_ratio,
    )
    corpus_manifest, pdf_total_bytes = _build_corpus_manifest(
        source_root,
        questions,
        metadata_by_name,
        questions_sha256=questions_sha256,
        split_seed=split_seed,
    )
    corpus_manifest_bytes = _canonical_json_bytes(corpus_manifest)

    eval_cases: dict[str, list[EvalCase]] = {"dev": [], "test": []}
    evidence_cases: dict[str, list[FinanceBenchPreparedCase]] = {
        "dev": [],
        "test": [],
    }
    for item in sorted(questions, key=lambda value: value.financebench_id):
        split = split_by_company[item.company]
        eval_cases[split].append(_eval_case(item))
        evidence_cases[split].append(_prepared_case(item, split))

    dev_companies = {
        item.company
        for item in questions
        if split_by_company[item.company] == "dev"
    }
    test_companies = set(split_by_company) - dev_companies
    if dev_companies & test_companies:
        raise AssertionError("FinanceBench company split leaked across partitions")
    test_bytes = _canonical_json_bytes(eval_cases["test"])
    manifest = FinanceBenchDatasetManifest(
        questions_sha256=questions_sha256,
        document_information_sha256=documents_sha256,
        corpus_manifest_sha256=_sha256(corpus_manifest_bytes),
        split_seed=split_seed,
        question_count=len(questions),
        document_count=corpus_manifest.document_count,
        company_count=len(split_by_company),
        dev_question_count=len(eval_cases["dev"]),
        test_question_count=len(eval_cases["test"]),
        dev_company_count=len(dev_companies),
        test_company_count=len(test_companies),
        pdf_total_bytes=pdf_total_bytes,
        test_sha256=_sha256(test_bytes),
    )

    source_root.mkdir(parents=True, exist_ok=True)
    prepared_root.mkdir(parents=True, exist_ok=True)
    eval_root = prepared_root / "eval"
    eval_root.mkdir(parents=True, exist_ok=True)
    (source_root / "manifest.json").write_bytes(corpus_manifest_bytes)
    (eval_root / "dev.json").write_bytes(_canonical_json_bytes(eval_cases["dev"]))
    (eval_root / "test.json").write_bytes(test_bytes)
    (eval_root / "dev_evidence.json").write_bytes(
        _canonical_json_bytes(evidence_cases["dev"])
    )
    (eval_root / "test_evidence.json").write_bytes(
        _canonical_json_bytes(evidence_cases["test"])
    )
    (eval_root / "test_manifest.sha256").write_text(
        build_test_manifest_line(test_bytes),
        encoding="ascii",
    )
    (prepared_root / "external_dataset_manifest.json").write_bytes(
        _canonical_json_bytes(manifest)
    )
    return FinanceBenchPreparationResult(
        source_root=source_root,
        prepared_root=prepared_root,
        manifest=manifest,
    )


def verify_financebench_preparation(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    prepared_root: Path = DEFAULT_PREPARED_ROOT,
) -> FinanceBenchDatasetManifest:
    source_root = Path(source_root).resolve()
    prepared_root = Path(prepared_root).resolve()
    dataset_manifest = FinanceBenchDatasetManifest.model_validate_json(
        (prepared_root / "external_dataset_manifest.json").read_bytes()
    )
    corpus_bytes = (source_root / "manifest.json").read_bytes()
    if _sha256(corpus_bytes) != dataset_manifest.corpus_manifest_sha256:
        raise ValueError("FinanceBench corpus manifest hash mismatch")
    corpus = CorpusManifest.model_validate_json(corpus_bytes)
    if (
        corpus.profile_id != FINANCEBENCH_PROFILE_ID
        or corpus.document_count != dataset_manifest.document_count
    ):
        raise ValueError("FinanceBench corpus manifest identity mismatch")
    for entry in corpus.documents:
        path = (source_root / entry.path).resolve()
        try:
            path.relative_to(source_root)
        except ValueError as exc:
            raise ValueError("FinanceBench document path escapes source root") from exc
        content = path.read_bytes()
        if len(content) != entry.byte_count or _sha256(content) != entry.sha256:
            raise ValueError(f"FinanceBench PDF integrity mismatch: {entry.doc_id}")

    eval_root = prepared_root / "eval"
    dev_cases = [
        EvalCase.model_validate(item)
        for item in json.loads((eval_root / "dev.json").read_text("utf-8"))
    ]
    test_bytes = (eval_root / "test.json").read_bytes()
    test_cases = [
        EvalCase.model_validate(item)
        for item in json.loads(test_bytes.decode("utf-8"))
    ]
    if (
        len(dev_cases) != dataset_manifest.dev_question_count
        or len(test_cases) != dataset_manifest.test_question_count
        or _sha256(test_bytes) != dataset_manifest.test_sha256
    ):
        raise ValueError("FinanceBench evaluation split integrity mismatch")
    dev_ids = {item.case_id for item in dev_cases}
    test_ids = {item.case_id for item in test_cases}
    if dev_ids & test_ids:
        raise ValueError("FinanceBench evaluation case leaked across splits")
    known_doc_ids = {item.doc_id for item in corpus.documents}
    if any(
        not set(item.gold_doc_ids).issubset(known_doc_ids)
        for item in [*dev_cases, *test_cases]
    ):
        raise ValueError("FinanceBench evaluation references an unknown document")
    return dataset_manifest


def build_financebench_entity_catalog(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    verify_pinned_hashes: bool = True,
) -> EntityCatalog:
    source_root = Path(source_root).resolve()
    corpus = CorpusManifest.model_validate_json(
        (source_root / "manifest.json").read_bytes()
    )
    _, documents_by_name, _, _ = load_financebench_upstream(
        source_root,
        verify_pinned_hashes=verify_pinned_hashes,
    )
    bindings_by_company: dict[str, list[EntityDocumentBinding]] = defaultdict(list)
    for document in corpus.documents:
        doc_name = Path(document.path).stem
        metadata = documents_by_name.get(doc_name)
        if metadata is None:
            raise ValueError(
                f"FinanceBench corpus document has no entity metadata: {doc_name}"
            )
        bindings_by_company[metadata.company].append(
            EntityDocumentBinding(
                policy_id=document.metadata.policy_id,
                years=[metadata.doc_period],
            )
        )

    entries: list[EntityCatalogEntry] = []
    for company, bindings in sorted(
        bindings_by_company.items(),
        key=lambda item: item[0].casefold(),
    ):
        aliases = [company, *_FINANCEBENCH_ENTITY_ALIASES.get(company, ())]
        entries.append(
            EntityCatalogEntry(
                entity_id=_ID_COMPONENT.sub("-", company.casefold()).strip("-"),
                display_name=company,
                aliases=aliases,
                documents=sorted(bindings, key=lambda item: item.policy_id),
            )
        )
    return EntityCatalog(
        schema_version="financebench_entity_catalog_v1",
        producer="enterprise_agentic_rag_v2",
        entries=entries,
    )


__all__ = [
    "DEFAULT_PREPARED_ROOT",
    "DEFAULT_PRIVATE_ROOT",
    "DEFAULT_SOURCE_ROOT",
    "FINANCEBENCH_PROFILE_ID",
    "FINANCEBENCH_REPOSITORY",
    "FINANCEBENCH_REVISION",
    "FinanceBenchDatasetManifest",
    "FinanceBenchPreparationResult",
    "build_financebench_entity_catalog",
    "download_financebench",
    "load_financebench_upstream",
    "prepare_financebench",
    "verify_financebench_preparation",
]
