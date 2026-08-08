from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.corpus.schemas import (
    CorpusManifest,
    DocumentMetadata,
    EvalCase,
    EvalUserContext,
    ManifestDocument,
)
from app.external_datasets.uda_finance import (
    UDA_FIN_QA_SHA256,
    UDA_HF_REPOSITORY,
    UDA_HF_REVISION,
    UDA_LICENSE,
    UDA_REPOSITORY,
    UDA_REVISION,
    UdaFinanceQaRow,
    canonical_json_bytes,
    load_uda_finance_rows,
    sha256_bytes,
)


R3_BASE_REVISION = "169e84ed1ee845cd07085f16e553bd5021fd73a2"
R3_PROFILE_ID = "uda-finance-r3-company-disjoint-v1"
R3_PRIVATE_ROOT = Path(".private") / "external" / "uda_finance" / "r3"
R3_SOURCE_ROOT = R3_PRIVATE_ROOT / "corpus"
R3_PREPARED_ROOT = R3_PRIVATE_ROOT / "prepared"
R3_PROTOCOL_PATH = Path("docs") / "r3" / "evidence" / "uda_finance_r3_protocol_v1.json"
R3Split = Literal["dev", "validation", "test"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class UdaFinanceR3Selection(_StrictModel):
    split: R3Split
    company_id: str = Field(min_length=1)
    doc_name: str = Field(pattern=r"^[A-Za-z0-9.-]+_\d{4}$")
    q_uids: list[str] = Field(min_length=1)


class UdaFinanceR3Protocol(_StrictModel):
    schema_version: Literal["uda_finance_r3_protocol_v1"]
    baseline_revision: Literal[R3_BASE_REVISION]
    dataset: Literal["UDA-QA/FinHybrid"]
    repository: Literal[UDA_REPOSITORY]
    repository_revision: Literal[UDA_REVISION]
    huggingface_repository: Literal[UDA_HF_REPOSITORY]
    huggingface_revision: Literal[UDA_HF_REVISION]
    license: Literal[UDA_LICENSE]
    qa_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_seed: str = Field(min_length=16)
    excluded_company_ids: list[str] = Field(min_length=20)
    minimum_questions_per_document: int = Field(ge=1)
    cases_per_document: int = Field(ge=1)
    dev_company_count: int = Field(ge=1)
    validation_company_count: int = Field(ge=1)
    test_company_count: int = Field(ge=1)
    dev_case_count: int = Field(ge=1)
    validation_case_count: int = Field(ge=1)
    test_case_count: int = Field(ge=1)
    selection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reserve_company_count: int = Field(ge=1)
    reserve_company_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_execution_limit: Literal[1]
    test_execution_limit: Literal[1]

    @model_validator(mode="after")
    def validate_contract(self) -> "UdaFinanceR3Protocol":
        if self.qa_sha256 != UDA_FIN_QA_SHA256:
            raise ValueError("R3 protocol does not bind the pinned UDA QA file")
        if self.excluded_company_ids != sorted(set(self.excluded_company_ids)):
            raise ValueError("R3 excluded companies must be sorted and unique")
        expected = {
            "dev": self.dev_company_count * self.cases_per_document,
            "validation": self.validation_company_count * self.cases_per_document,
            "test": self.test_company_count * self.cases_per_document,
        }
        observed = {
            "dev": self.dev_case_count,
            "validation": self.validation_case_count,
            "test": self.test_case_count,
        }
        if observed != expected:
            raise ValueError("R3 case counts do not match company and case quotas")
        return self


class UdaFinanceR3PreparedCase(_StrictModel):
    schema_version: Literal["uda_finance_r3_case_v1"] = "uda_finance_r3_case_v1"
    case_id: str = Field(min_length=1)
    split: R3Split
    company_id: str = Field(min_length=1)
    doc_name: str = Field(min_length=1)
    q_uid: str = Field(min_length=1)
    question: str = Field(min_length=1)
    answers: list[str] = Field(min_length=1, max_length=2)
    gold_doc_id: str = Field(min_length=1)
    page_number: int = Field(ge=1)


class UdaFinanceR3DatasetManifest(_StrictModel):
    schema_version: Literal["uda_finance_r3_dataset_v1"] = "uda_finance_r3_dataset_v1"
    baseline_revision: Literal[R3_BASE_REVISION] = R3_BASE_REVISION
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    qa_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_count: int = Field(ge=3)
    pdf_total_bytes: int = Field(ge=1)
    split_case_counts: dict[R3Split, int]
    split_case_sha256: dict[R3Split, str]


def stable_key(seed: str, value: str) -> str:
    return sha256_bytes(f"{seed}\0{value}".encode("utf-8"))


def select_uda_finance_r3_cases(
    rows: Sequence[UdaFinanceQaRow],
    *,
    seed: str,
    excluded_company_ids: Sequence[str],
    minimum_questions_per_document: int,
    cases_per_document: int,
    dev_company_count: int,
    validation_company_count: int,
    test_company_count: int,
) -> tuple[list[UdaFinanceR3Selection], list[str]]:
    if minimum_questions_per_document < cases_per_document:
        raise ValueError("minimum questions must cover cases per document")
    excluded = set(excluded_company_ids)
    by_doc: dict[str, list[UdaFinanceQaRow]] = defaultdict(list)
    for row in rows:
        by_doc[row.doc_name].append(row)
    eligible_by_company: dict[str, list[str]] = defaultdict(list)
    for doc_name, doc_rows in by_doc.items():
        company = doc_rows[0].company_id
        if company not in excluded and len(doc_rows) >= minimum_questions_per_document:
            eligible_by_company[company].append(doc_name)
    ordered_companies = sorted(
        eligible_by_company,
        key=lambda company: (stable_key(seed, f"company:{company}"), company),
    )
    required = dev_company_count + validation_company_count + test_company_count
    if len(ordered_companies) < required:
        raise ValueError("R3 UDA population has too few unused eligible companies")
    boundaries = (dev_company_count, dev_company_count + validation_company_count)
    selections: list[UdaFinanceR3Selection] = []
    for index, company in enumerate(ordered_companies[:required]):
        split: R3Split
        if index < boundaries[0]:
            split = "dev"
        elif index < boundaries[1]:
            split = "validation"
        else:
            split = "test"
        doc_name = min(
            eligible_by_company[company],
            key=lambda value: (stable_key(seed, f"document:{value}"), value),
        )
        selected_rows = sorted(
            by_doc[doc_name],
            key=lambda row: (stable_key(seed, f"case:{row.q_uid}"), row.q_uid),
        )[:cases_per_document]
        selections.append(
            UdaFinanceR3Selection(
                split=split,
                company_id=company,
                doc_name=doc_name,
                q_uids=sorted(row.q_uid for row in selected_rows),
            )
        )
    validate_r3_selection(
        selections,
        excluded_company_ids=excluded,
        cases_per_document=cases_per_document,
    )
    return selections, ordered_companies[required:]


def validate_r3_selection(
    selections: Sequence[UdaFinanceR3Selection],
    *,
    excluded_company_ids: set[str],
    cases_per_document: int,
) -> None:
    companies = [item.company_id for item in selections]
    documents = [item.doc_name for item in selections]
    q_uids = [q_uid for item in selections for q_uid in item.q_uids]
    if set(companies) & excluded_company_ids:
        raise ValueError("R3 selection reuses a consumed company")
    if len(companies) != len(set(companies)):
        raise ValueError("R3 company splits are not disjoint")
    if len(documents) != len(set(documents)):
        raise ValueError("R3 document splits are not disjoint")
    if len(q_uids) != len(set(q_uids)):
        raise ValueError("R3 selected questions are not unique")
    if any(len(item.q_uids) != cases_per_document for item in selections):
        raise ValueError("R3 selected document has the wrong case count")


def r3_selection_sha256(selections: Sequence[UdaFinanceR3Selection]) -> str:
    ordered = sorted(
        selections, key=lambda item: (item.split, item.company_id, item.doc_name)
    )
    return sha256_bytes(canonical_json_bytes(ordered))


def reserve_company_ids_sha256(company_ids: Sequence[str]) -> str:
    return sha256_bytes(canonical_json_bytes(sorted(company_ids)))


def load_uda_finance_r3_protocol(
    path: Path = R3_PROTOCOL_PATH,
) -> tuple[UdaFinanceR3Protocol, str]:
    content = Path(path).resolve().read_bytes()
    if not content or len(content) > 128 * 1024:
        raise ValueError("R3 UDA protocol is empty or too large")
    return UdaFinanceR3Protocol.model_validate_json(content), sha256_bytes(content)


def verify_r3_protocol_selection(
    protocol: UdaFinanceR3Protocol, rows: Sequence[UdaFinanceQaRow]
) -> tuple[list[UdaFinanceR3Selection], list[str]]:
    selections, reserve = select_uda_finance_r3_cases(
        rows,
        seed=protocol.selection_seed,
        excluded_company_ids=protocol.excluded_company_ids,
        minimum_questions_per_document=protocol.minimum_questions_per_document,
        cases_per_document=protocol.cases_per_document,
        dev_company_count=protocol.dev_company_count,
        validation_company_count=protocol.validation_company_count,
        test_company_count=protocol.test_company_count,
    )
    if r3_selection_sha256(selections) != protocol.selection_sha256:
        raise ValueError("R3 UDA selection does not match the frozen protocol")
    if len(reserve) != protocol.reserve_company_count:
        raise ValueError("R3 reserve company count does not match the protocol")
    if reserve_company_ids_sha256(reserve) != protocol.reserve_company_ids_sha256:
        raise ValueError("R3 reserve company hash does not match the protocol")
    return selections, reserve


def prepare_uda_finance_r3(
    *,
    qa_path: Path,
    pdf_root: Path,
    source_root: Path = R3_SOURCE_ROOT,
    prepared_root: Path = R3_PREPARED_ROOT,
    protocol_path: Path = R3_PROTOCOL_PATH,
) -> UdaFinanceR3DatasetManifest:
    protocol, protocol_sha256 = load_uda_finance_r3_protocol(protocol_path)
    rows = load_uda_finance_rows(qa_path)
    selections, _ = verify_r3_protocol_selection(protocol, rows)
    source_root = Path(source_root).resolve()
    prepared_root = Path(prepared_root).resolve()
    pdf_root = Path(pdf_root).resolve()
    source_root.mkdir(parents=True, exist_ok=True)
    document_root = source_root / "documents"
    document_root.mkdir(exist_ok=True)
    row_by_uid = {row.q_uid: row for row in rows}
    documents: list[ManifestDocument] = []
    pdf_total_bytes = 0
    for doc_name in sorted({item.doc_name for item in selections}):
        source = (pdf_root / f"{doc_name}.pdf").resolve()
        source.relative_to(pdf_root)
        content = source.read_bytes()
        if not content.startswith(b"%PDF-"):
            raise ValueError(f"R3 UDA source is not a PDF: {doc_name}")
        target = document_root / source.name
        if target.exists() and target.read_bytes() != content:
            raise FileExistsError(f"R3 prepared PDF differs: {target}")
        if not target.exists():
            shutil.copyfile(source, target)
        pdf_total_bytes += len(content)
        company, year_text = doc_name.rsplit("_", 1)
        doc_id = _doc_id(doc_name)
        documents.append(
            ManifestDocument(
                doc_id=doc_id,
                path=f"documents/{source.name}",
                sha256=sha256_bytes(content),
                byte_count=len(content),
                format="pdf",
                source_type="filing",
                variant="authoritative",
                metadata=DocumentMetadata(
                    policy_id=doc_id,
                    version_id=f"{doc_id}-r3-v1",
                    version="r3.1",
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
    cases_by_split: dict[R3Split, list[UdaFinanceR3PreparedCase]] = {
        "dev": [],
        "validation": [],
        "test": [],
    }
    eval_by_split: dict[R3Split, list[EvalCase]] = {
        "dev": [],
        "validation": [],
        "test": [],
    }
    for selection in selections:
        for q_uid in selection.q_uids:
            row = row_by_uid[q_uid]
            case_id = f"uda-r3-{sha256_bytes(q_uid.encode('utf-8'))[:16]}"
            doc_id = _doc_id(row.doc_name)
            case = UdaFinanceR3PreparedCase(
                case_id=case_id,
                split=selection.split,
                company_id=row.company_id,
                doc_name=row.doc_name,
                q_uid=row.q_uid,
                question=row.question,
                answers=[value for value in (row.answer_1, row.answer_2) if value],
                gold_doc_id=doc_id,
                page_number=row.page_number,
            )
            cases_by_split[selection.split].append(case)
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
                    tags=["external", "uda", "finance", "r3", selection.split],
                )
            )
    for split in ("dev", "validation", "test"):
        cases_by_split[split].sort(key=lambda item: item.case_id)
        eval_by_split[split].sort(key=lambda item: item.case_id)
    profile = {
        "baseline_revision": protocol.baseline_revision,
        "protocol_sha256": protocol_sha256,
        "selection_sha256": protocol.selection_sha256,
    }
    corpus_manifest = CorpusManifest(
        schema_version="enterprise_corpus_manifest_v1",
        producer="enterprise_agentic_rag_v2",
        generator_version="uda_finance_r3_adapter_v1",
        profile_id=R3_PROFILE_ID,
        seed=int(stable_key(protocol.selection_seed, "corpus")[:8], 16),
        facts_sha256=protocol.qa_sha256,
        profile_sha256=sha256_bytes(canonical_json_bytes(profile)),
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
    split_bytes: dict[R3Split, bytes] = {}
    for split in ("dev", "validation", "test"):
        split_bytes[split] = canonical_json_bytes(cases_by_split[split])
        (eval_root / f"{split}_evidence.json").write_bytes(split_bytes[split])
        (eval_root / f"{split}.json").write_bytes(canonical_json_bytes(eval_by_split[split]))
    manifest = UdaFinanceR3DatasetManifest(
        protocol_sha256=protocol_sha256,
        selection_sha256=protocol.selection_sha256,
        qa_sha256=protocol.qa_sha256,
        corpus_manifest_sha256=sha256_bytes(corpus_bytes),
        document_count=len(documents),
        pdf_total_bytes=pdf_total_bytes,
        split_case_counts={key: len(value) for key, value in cases_by_split.items()},
        split_case_sha256={key: sha256_bytes(value) for key, value in split_bytes.items()},
    )
    prepared_root.mkdir(parents=True, exist_ok=True)
    (prepared_root / "external_dataset_manifest.json").write_bytes(
        canonical_json_bytes(manifest)
    )
    return manifest


def verify_uda_finance_r3_preparation(
    *,
    source_root: Path = R3_SOURCE_ROOT,
    prepared_root: Path = R3_PREPARED_ROOT,
) -> UdaFinanceR3DatasetManifest:
    source_root = Path(source_root).resolve()
    prepared_root = Path(prepared_root).resolve()
    manifest = UdaFinanceR3DatasetManifest.model_validate_json(
        (prepared_root / "external_dataset_manifest.json").read_bytes()
    )
    corpus_bytes = (source_root / "manifest.json").read_bytes()
    if sha256_bytes(corpus_bytes) != manifest.corpus_manifest_sha256:
        raise ValueError("R3 corpus manifest hash mismatch")
    corpus = CorpusManifest.model_validate_json(corpus_bytes)
    if corpus.profile_id != R3_PROFILE_ID or len(corpus.documents) != manifest.document_count:
        raise ValueError("R3 corpus identity mismatch")
    for document in corpus.documents:
        path = (source_root / document.path).resolve()
        path.relative_to(source_root)
        content = path.read_bytes()
        if len(content) != document.byte_count or sha256_bytes(content) != document.sha256:
            raise ValueError(f"R3 PDF integrity mismatch: {document.doc_id}")
    for split in ("dev", "validation", "test"):
        content = (prepared_root / "eval" / f"{split}_evidence.json").read_bytes()
        cases = [
            UdaFinanceR3PreparedCase.model_validate(item)
            for item in json.loads(content.decode("utf-8"))
        ]
        if len(cases) != manifest.split_case_counts[split]:
            raise ValueError(f"R3 {split} case count mismatch")
        if sha256_bytes(content) != manifest.split_case_sha256[split]:
            raise ValueError(f"R3 {split} case hash mismatch")
    return manifest


def load_uda_finance_r3_cases(
    prepared_root: Path, *, split: R3Split
) -> tuple[list[UdaFinanceR3PreparedCase], str]:
    path = Path(prepared_root).resolve() / "eval" / f"{split}_evidence.json"
    content = path.read_bytes()
    cases = [
        UdaFinanceR3PreparedCase.model_validate(item)
        for item in json.loads(content.decode("utf-8"))
    ]
    if not cases or any(case.split != split for case in cases):
        raise ValueError(f"R3 {split} case bundle is empty or misaligned")
    return cases, hashlib.sha256(content).hexdigest()


def _doc_id(doc_name: str) -> str:
    return f"uda-fin-{doc_name.lower().replace('_', '-')}"


__all__ = [
    "R3_BASE_REVISION",
    "R3_PREPARED_ROOT",
    "R3_PRIVATE_ROOT",
    "R3_PROTOCOL_PATH",
    "R3_SOURCE_ROOT",
    "UdaFinanceR3DatasetManifest",
    "UdaFinanceR3PreparedCase",
    "UdaFinanceR3Protocol",
    "UdaFinanceR3Selection",
    "load_uda_finance_r3_cases",
    "load_uda_finance_r3_protocol",
    "prepare_uda_finance_r3",
    "r3_selection_sha256",
    "reserve_company_ids_sha256",
    "select_uda_finance_r3_cases",
    "verify_r3_protocol_selection",
    "verify_uda_finance_r3_preparation",
]
