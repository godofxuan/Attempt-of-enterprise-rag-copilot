from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.corpus.schemas import (
    CorpusManifest,
    DocumentMetadata,
    EvalCase,
    EvalUserContext,
    ManifestDocument,
)


UDA_REPOSITORY = "https://github.com/qinchuanhui/UDA-Benchmark"
UDA_REVISION = "fca5237ac316e776d8dbccffa55ca29c0efdc185"
UDA_HF_REPOSITORY = "qinchuanhui/UDA-QA"
UDA_HF_REVISION = "d4367103fe8fe86b3bb76c66be8eafc4fb4117b2"
UDA_FIN_QA_SHA256 = (
    "2a0a671027852d6ba7bda429d1a5d62b5a7b440ab7e98779853088b1c3f2e8a5"
)
UDA_LICENSE = "CC-BY-SA-4.0"
UDA_PROFILE_ID = "uda-finance-company-disjoint-v1"
DEFAULT_PRIVATE_ROOT = Path(".private") / "external" / "uda_finance"
DEFAULT_SOURCE_ROOT = DEFAULT_PRIVATE_ROOT / "corpus"
DEFAULT_PREPARED_ROOT = DEFAULT_PRIVATE_ROOT / "prepared"
DEFAULT_PROTOCOL_PATH = (
    Path("docs")
    / "external_datasets"
    / "evidence"
    / "uda_finance_page_protocol_v1.json"
)

_Q_UID = re.compile(
    r"^(?P<company>[A-Za-z0-9.-]+)/(?P<year>\d{4})/"
    r"page_(?P<page>\d+)\.pdf-(?P<item>\d+)$"
)
_DOC_NAME = re.compile(r"^[A-Za-z0-9.-]+_\d{4}$")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class UdaFinanceQaRow(_StrictModel):
    doc_name: str = Field(pattern=r"^[A-Za-z0-9.-]+_\d{4}$")
    q_uid: str = Field(min_length=1)
    question: str = Field(min_length=1)
    answer_1: str = ""
    answer_2: str = ""
    company_id: str = Field(min_length=1)
    report_year: int = Field(ge=1900, le=2200)
    page_number: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_answers(self) -> UdaFinanceQaRow:
        if not self.answer_1 and not self.answer_2:
            raise ValueError("UDA finance row must provide at least one answer")
        return self


class UdaFinanceSelection(_StrictModel):
    split: Literal["dev", "test"]
    company_id: str = Field(min_length=1)
    doc_name: str = Field(pattern=r"^[A-Za-z0-9.-]+_\d{4}$")
    q_uids: list[str] = Field(min_length=1)


class UdaFinanceProtocol(_StrictModel):
    schema_version: Literal["uda_finance_page_protocol_v1"]
    dataset: Literal["UDA-QA/FinHybrid"]
    repository: Literal[UDA_REPOSITORY]
    repository_revision: Literal[UDA_REVISION]
    huggingface_repository: Literal[UDA_HF_REPOSITORY]
    huggingface_revision: Literal[UDA_HF_REVISION]
    license: Literal[UDA_LICENSE]
    qa_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_seed: str = Field(min_length=1)
    minimum_questions_per_document: int = Field(ge=1)
    dev_company_count: int = Field(ge=1)
    test_company_count: int = Field(ge=1)
    cases_per_document: int = Field(ge=1)
    selection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dev_case_count: int = Field(ge=1)
    test_case_count: int = Field(ge=1)
    retrieval_arms: list[Literal["bm25", "dense", "hybrid_rrf"]]
    selection_metric: Literal["page_ndcg_at_5"]
    tie_break_metrics: list[Literal["page_hit_at_5", "latency_ms_p95"]]
    test_execution_limit: Literal[1]

    @model_validator(mode="after")
    def validate_protocol(self) -> UdaFinanceProtocol:
        if self.qa_sha256 != UDA_FIN_QA_SHA256:
            raise ValueError("UDA finance QA hash is not the pinned upstream file")
        if self.dev_case_count != self.dev_company_count * self.cases_per_document:
            raise ValueError("UDA dev case count does not match the protocol")
        if self.test_case_count != self.test_company_count * self.cases_per_document:
            raise ValueError("UDA test case count does not match the protocol")
        if self.retrieval_arms != ["bm25", "dense", "hybrid_rrf"]:
            raise ValueError("UDA retrieval arms must keep their preregistered order")
        if self.tie_break_metrics != ["page_hit_at_5", "latency_ms_p95"]:
            raise ValueError("UDA tie-break metrics are not preregistered")
        return self


class UdaFinancePreparedCase(_StrictModel):
    schema_version: Literal["uda_finance_case_v1"] = "uda_finance_case_v1"
    case_id: str = Field(min_length=1)
    split: Literal["dev", "test"]
    company_id: str = Field(min_length=1)
    doc_name: str = Field(min_length=1)
    q_uid: str = Field(min_length=1)
    question: str = Field(min_length=1)
    answers: list[str] = Field(min_length=1, max_length=2)
    gold_doc_id: str = Field(min_length=1)
    page_number: int = Field(ge=1)


class UdaFinanceDatasetManifest(_StrictModel):
    schema_version: Literal["uda_finance_external_dataset_v1"] = (
        "uda_finance_external_dataset_v1"
    )
    dataset: Literal["UDA-QA/FinHybrid"] = "UDA-QA/FinHybrid"
    repository_revision: Literal[UDA_REVISION] = UDA_REVISION
    huggingface_revision: Literal[UDA_HF_REVISION] = UDA_HF_REVISION
    qa_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_count: int = Field(ge=2)
    dev_case_count: int = Field(ge=1)
    test_case_count: int = Field(ge=1)
    pdf_total_bytes: int = Field(ge=1)
    dev_cases_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    test_cases_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
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


def _stable_key(seed: str, value: str) -> str:
    return sha256_bytes(f"{seed}\0{value}".encode("utf-8"))


def load_uda_finance_rows(path: Path, *, verify_hash: bool = True) -> list[UdaFinanceQaRow]:
    path = Path(path).resolve()
    content = path.read_bytes()
    if verify_hash and sha256_bytes(content) != UDA_FIN_QA_SHA256:
        raise ValueError("UDA finance QA file does not match the pinned SHA-256")
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(text.splitlines(), delimiter="|")
    expected = ["doc_name", "q_uid", "question", "answer_1", "answer_2"]
    if reader.fieldnames != expected:
        raise ValueError(f"UDA finance QA columns are invalid: {reader.fieldnames!r}")
    rows: list[UdaFinanceQaRow] = []
    seen: set[str] = set()
    for raw in reader:
        match = _Q_UID.fullmatch(raw["q_uid"].strip())
        if match is None:
            raise ValueError(f"UDA q_uid is malformed: {raw['q_uid']!r}")
        doc_name = raw["doc_name"].strip()
        expected_doc = f"{match.group('company')}_{match.group('year')}"
        if not _DOC_NAME.fullmatch(doc_name) or doc_name != expected_doc:
            raise ValueError(
                f"UDA q_uid/document identity mismatch: {raw['q_uid']!r}"
            )
        if raw["q_uid"] in seen:
            raise ValueError(f"UDA q_uid is duplicated: {raw['q_uid']!r}")
        seen.add(raw["q_uid"])
        rows.append(
            UdaFinanceQaRow(
                **raw,
                company_id=match.group("company"),
                report_year=int(match.group("year")),
                page_number=int(match.group("page")),
            )
        )
    if not rows:
        raise ValueError("UDA finance QA file contains no rows")
    return rows


def select_uda_finance_cases(
    rows: Sequence[UdaFinanceQaRow],
    *,
    seed: str,
    minimum_questions_per_document: int,
    dev_company_count: int,
    test_company_count: int,
    cases_per_document: int,
) -> list[UdaFinanceSelection]:
    if minimum_questions_per_document < cases_per_document:
        raise ValueError("minimum questions must cover cases per document")
    by_doc: dict[str, list[UdaFinanceQaRow]] = defaultdict(list)
    for row in rows:
        by_doc[row.doc_name].append(row)
    eligible_by_company: dict[str, list[str]] = defaultdict(list)
    for doc_name, doc_rows in by_doc.items():
        if len(doc_rows) >= minimum_questions_per_document:
            eligible_by_company[doc_rows[0].company_id].append(doc_name)
    required_companies = dev_company_count + test_company_count
    companies = sorted(
        eligible_by_company,
        key=lambda company: (_stable_key(seed, f"company:{company}"), company),
    )
    if len(companies) < required_companies:
        raise ValueError("UDA finance QA has too few eligible companies")
    selections: list[UdaFinanceSelection] = []
    for index, company in enumerate(companies[:required_companies]):
        doc_name = min(
            eligible_by_company[company],
            key=lambda value: (_stable_key(seed, f"document:{value}"), value),
        )
        selected_rows = sorted(
            by_doc[doc_name],
            key=lambda row: (_stable_key(seed, f"case:{row.q_uid}"), row.q_uid),
        )[:cases_per_document]
        selections.append(
            UdaFinanceSelection(
                split="dev" if index < dev_company_count else "test",
                company_id=company,
                doc_name=doc_name,
                q_uids=sorted(row.q_uid for row in selected_rows),
            )
        )
    _validate_selection(selections, cases_per_document=cases_per_document)
    return selections


def selection_sha256(selections: Sequence[UdaFinanceSelection]) -> str:
    ordered = sorted(
        selections,
        key=lambda item: (item.split, item.company_id, item.doc_name),
    )
    return sha256_bytes(canonical_json_bytes(ordered))


def load_uda_finance_protocol(path: Path = DEFAULT_PROTOCOL_PATH) -> tuple[UdaFinanceProtocol, str]:
    content = Path(path).resolve().read_bytes()
    if not content or len(content) > 64 * 1024:
        raise ValueError("UDA finance protocol is empty or too large")
    return UdaFinanceProtocol.model_validate_json(content), sha256_bytes(content)


def extract_selected_pdfs(
    archive_path: Path,
    destination: Path,
    doc_names: Sequence[str],
) -> dict[str, Path]:
    archive_path = Path(archive_path).resolve()
    destination = Path(destination).resolve()
    wanted = {f"{name}.pdf" for name in doc_names}
    if len(wanted) != len(doc_names):
        raise ValueError("UDA selected document names must be unique")
    destination.mkdir(parents=True, exist_ok=True)
    found: dict[str, zipfile.ZipInfo] = {}
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            path = PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("UDA PDF archive contains an unsafe path")
            if member.is_dir() or path.name not in wanted:
                continue
            if path.name in found:
                raise ValueError(f"UDA PDF archive duplicates {path.name!r}")
            found[path.name] = member
        missing = wanted - set(found)
        if missing:
            raise ValueError(f"UDA PDF archive is missing {sorted(missing)!r}")
        outputs: dict[str, Path] = {}
        for name in sorted(wanted):
            target = destination / name
            if target.exists():
                raise FileExistsError(f"refusing to overwrite UDA PDF: {target}")
            with archive.open(found[name]) as source, target.open("xb") as sink:
                shutil.copyfileobj(source, sink, length=1024 * 1024)
            outputs[name[:-4]] = target
    return outputs


def prepare_uda_finance(
    *,
    qa_path: Path,
    pdf_root: Path,
    source_root: Path = DEFAULT_SOURCE_ROOT,
    prepared_root: Path = DEFAULT_PREPARED_ROOT,
    protocol_path: Path = DEFAULT_PROTOCOL_PATH,
) -> UdaFinanceDatasetManifest:
    protocol, protocol_sha256 = load_uda_finance_protocol(protocol_path)
    rows = load_uda_finance_rows(qa_path)
    selections = select_uda_finance_cases(
        rows,
        seed=protocol.selection_seed,
        minimum_questions_per_document=protocol.minimum_questions_per_document,
        dev_company_count=protocol.dev_company_count,
        test_company_count=protocol.test_company_count,
        cases_per_document=protocol.cases_per_document,
    )
    observed_selection_sha256 = selection_sha256(selections)
    if observed_selection_sha256 != protocol.selection_sha256:
        raise ValueError("UDA finance selection does not match the frozen protocol")

    source_root = Path(source_root).resolve()
    prepared_root = Path(prepared_root).resolve()
    pdf_root = Path(pdf_root).resolve()
    source_root.mkdir(parents=True, exist_ok=True)
    (source_root / "documents").mkdir(exist_ok=True)
    row_by_uid = {row.q_uid: row for row in rows}
    documents: list[ManifestDocument] = []
    selected_doc_names = sorted({item.doc_name for item in selections})
    pdf_total_bytes = 0
    for doc_name in selected_doc_names:
        source_pdf = (pdf_root / f"{doc_name}.pdf").resolve()
        try:
            source_pdf.relative_to(pdf_root)
        except ValueError as exc:
            raise ValueError("UDA PDF path escapes the extracted root") from exc
        content = source_pdf.read_bytes()
        if not content.startswith(b"%PDF-"):
            raise ValueError(f"UDA source is not a PDF: {doc_name}")
        target = source_root / "documents" / f"{doc_name}.pdf"
        if target.exists() and target.read_bytes() != content:
            raise FileExistsError(f"UDA prepared PDF differs: {target}")
        if not target.exists():
            shutil.copyfile(source_pdf, target)
        pdf_total_bytes += len(content)
        company, year_text = doc_name.rsplit("_", 1)
        doc_id = _doc_id(doc_name)
        documents.append(
            ManifestDocument(
                doc_id=doc_id,
                path=f"documents/{doc_name}.pdf",
                sha256=sha256_bytes(content),
                byte_count=len(content),
                format="pdf",
                source_type="filing",
                variant="authoritative",
                metadata=DocumentMetadata(
                    policy_id=doc_id,
                    version_id=f"{doc_id}-v1",
                    version="1.0",
                    status="active",
                    effective_from=date(int(year_text), 1, 1),
                    authority=90,
                    actual_department="finance",
                    filed_department="finance",
                    tenant="uda-external",
                    region="global",
                    acl_groups=["uda-evaluator"],
                    variant="authoritative",
                ),
                fact_ids=[],
            )
        )

    cases_by_split: dict[str, list[UdaFinancePreparedCase]] = {"dev": [], "test": []}
    eval_by_split: dict[str, list[EvalCase]] = {"dev": [], "test": []}
    for selection in selections:
        for q_uid in selection.q_uids:
            row = row_by_uid[q_uid]
            case_id = f"uda-fin-{sha256_bytes(q_uid.encode('utf-8'))[:16]}"
            doc_id = _doc_id(row.doc_name)
            prepared = UdaFinancePreparedCase(
                case_id=case_id,
                split=selection.split,
                company_id=row.company_id,
                doc_name=row.doc_name,
                q_uid=row.q_uid,
                question=row.question,
                answers=[answer for answer in (row.answer_1, row.answer_2) if answer],
                gold_doc_id=doc_id,
                page_number=row.page_number,
            )
            cases_by_split[selection.split].append(prepared)
            eval_by_split[selection.split].append(
                EvalCase(
                    case_id=case_id,
                    question=row.question,
                    task_type="fact_lookup",
                    answer_mode="answered",
                    user_context=EvalUserContext(
                        user_id="uda-evaluator",
                        tenant="uda-external",
                        region="global",
                        groups=["uda-evaluator"],
                    ),
                    gold_doc_ids=[doc_id],
                    expected_answer=row.answer_1 or row.answer_2,
                    expected_filters={"policy_ids": [doc_id]},
                    expected_authority_doc_ids=[doc_id],
                    tags=["external", "uda", "finance", selection.split],
                )
            )
    for split in ("dev", "test"):
        cases_by_split[split].sort(key=lambda item: item.case_id)
        eval_by_split[split].sort(key=lambda item: item.case_id)

    profile_payload = {
        "dataset": "UDA-QA/FinHybrid",
        "protocol_sha256": protocol_sha256,
        "selection_sha256": observed_selection_sha256,
    }
    corpus_manifest = CorpusManifest(
        schema_version="enterprise_corpus_manifest_v1",
        producer="enterprise_agentic_rag_v2",
        generator_version="uda_finance_adapter_v1",
        profile_id=UDA_PROFILE_ID,
        seed=int(protocol.selection_seed[-8:], 16),
        facts_sha256=protocol.qa_sha256,
        profile_sha256=sha256_bytes(canonical_json_bytes(profile_payload)),
        document_count=len(documents),
        counts_by_format={"pdf": len(documents)},
        counts_by_source_type={"filing": len(documents)},
        counts_by_variant={"authoritative": len(documents)},
        documents=documents,
    )
    corpus_bytes = canonical_json_bytes(corpus_manifest)
    (source_root / "manifest.json").write_bytes(corpus_bytes)
    eval_root = prepared_root / "eval"
    eval_root.mkdir(parents=True, exist_ok=True)
    split_bytes: dict[str, bytes] = {}
    for split in ("dev", "test"):
        split_bytes[split] = canonical_json_bytes(cases_by_split[split])
        (eval_root / f"{split}_evidence.json").write_bytes(split_bytes[split])
        (eval_root / f"{split}.json").write_bytes(
            canonical_json_bytes(eval_by_split[split])
        )
    manifest = UdaFinanceDatasetManifest(
        qa_sha256=protocol.qa_sha256,
        protocol_sha256=protocol_sha256,
        selection_sha256=observed_selection_sha256,
        corpus_manifest_sha256=sha256_bytes(corpus_bytes),
        document_count=len(documents),
        dev_case_count=len(cases_by_split["dev"]),
        test_case_count=len(cases_by_split["test"]),
        pdf_total_bytes=pdf_total_bytes,
        dev_cases_sha256=sha256_bytes(split_bytes["dev"]),
        test_cases_sha256=sha256_bytes(split_bytes["test"]),
    )
    (prepared_root / "external_dataset_manifest.json").write_bytes(
        canonical_json_bytes(manifest)
    )
    return manifest


def verify_uda_finance_preparation(
    *,
    source_root: Path = DEFAULT_SOURCE_ROOT,
    prepared_root: Path = DEFAULT_PREPARED_ROOT,
) -> UdaFinanceDatasetManifest:
    source_root = Path(source_root).resolve()
    prepared_root = Path(prepared_root).resolve()
    manifest = UdaFinanceDatasetManifest.model_validate_json(
        (prepared_root / "external_dataset_manifest.json").read_bytes()
    )
    corpus_bytes = (source_root / "manifest.json").read_bytes()
    if sha256_bytes(corpus_bytes) != manifest.corpus_manifest_sha256:
        raise ValueError("UDA corpus manifest hash mismatch")
    corpus = CorpusManifest.model_validate_json(corpus_bytes)
    if corpus.profile_id != UDA_PROFILE_ID or len(corpus.documents) != manifest.document_count:
        raise ValueError("UDA corpus identity mismatch")
    for document in corpus.documents:
        path = (source_root / document.path).resolve()
        try:
            path.relative_to(source_root)
        except ValueError as exc:
            raise ValueError("UDA corpus path escapes source root") from exc
        content = path.read_bytes()
        if len(content) != document.byte_count or sha256_bytes(content) != document.sha256:
            raise ValueError(f"UDA PDF integrity mismatch: {document.doc_id}")
    for split, expected_count, expected_hash in (
        ("dev", manifest.dev_case_count, manifest.dev_cases_sha256),
        ("test", manifest.test_case_count, manifest.test_cases_sha256),
    ):
        content = (prepared_root / "eval" / f"{split}_evidence.json").read_bytes()
        cases = [
            UdaFinancePreparedCase.model_validate(item)
            for item in json.loads(content.decode("utf-8"))
        ]
        if len(cases) != expected_count or sha256_bytes(content) != expected_hash:
            raise ValueError(f"UDA {split} evaluation integrity mismatch")
    return manifest


def _validate_selection(
    selections: Sequence[UdaFinanceSelection], *, cases_per_document: int
) -> None:
    companies = [item.company_id for item in selections]
    documents = [item.doc_name for item in selections]
    q_uids = [q_uid for item in selections for q_uid in item.q_uids]
    if len(companies) != len(set(companies)):
        raise ValueError("UDA company split is not disjoint")
    if len(documents) != len(set(documents)):
        raise ValueError("UDA document split is not disjoint")
    if len(q_uids) != len(set(q_uids)):
        raise ValueError("UDA selected question IDs are not unique")
    if any(len(item.q_uids) != cases_per_document for item in selections):
        raise ValueError("UDA selected documents have the wrong case count")


def _doc_id(doc_name: str) -> str:
    return f"uda-fin-{doc_name.lower().replace('_', '-')}"


__all__ = [
    "DEFAULT_PREPARED_ROOT",
    "DEFAULT_PRIVATE_ROOT",
    "DEFAULT_PROTOCOL_PATH",
    "DEFAULT_SOURCE_ROOT",
    "UDA_FIN_QA_SHA256",
    "UDA_HF_REVISION",
    "UDA_REVISION",
    "UdaFinanceDatasetManifest",
    "UdaFinancePreparedCase",
    "UdaFinanceProtocol",
    "canonical_json_bytes",
    "extract_selected_pdfs",
    "load_uda_finance_protocol",
    "load_uda_finance_rows",
    "prepare_uda_finance",
    "select_uda_finance_cases",
    "selection_sha256",
    "verify_uda_finance_preparation",
]
