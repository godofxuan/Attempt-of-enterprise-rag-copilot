from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Literal

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
    UdaFinanceQaRow,
    canonical_json_bytes,
    load_uda_finance_rows,
    sha256_bytes,
)
from app.external_datasets.uda_finance_r3 import (
    R3_PROTOCOL_PATH,
    load_uda_finance_r3_protocol,
    verify_r3_protocol_selection,
)

R4_BASE_REVISION = "2065e571d77439babf76a763ac459a618950f218"
R4_PROFILE_ID = "uda-finance-r4-reserve-company-disjoint-v1"
R4_PRIVATE_ROOT = Path(".private") / "external" / "uda_finance" / "r4"
R4_SOURCE_ROOT = R4_PRIVATE_ROOT / "corpus"
R4_PREPARED_ROOT = R4_PRIVATE_ROOT / "prepared"
R4_PROTOCOL_PATH = Path("docs") / "r4" / "evidence" / "uda_finance_r4_protocol_v1.json"
R4Split = Literal["dev", "validation", "test"]
_R4_SPLITS: tuple[R4Split, ...] = ("dev", "validation", "test")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class UdaFinanceR4Selection(_StrictModel):
    split: R4Split
    company_id: str = Field(min_length=1)
    doc_name: str = Field(pattern=r"^[A-Za-z0-9.-]+_\d{4}$")
    q_uids: list[str] = Field(min_length=1)


class UdaFinanceR4Protocol(_StrictModel):
    schema_version: Literal["uda_finance_r4_protocol_v1", "uda_finance_r4_protocol_v2"]
    baseline_revision: Literal["2065e571d77439babf76a763ac459a618950f218"]
    dataset: Literal["UDA-QA/FinHybrid"]
    repository: Literal["https://github.com/qinchuanhui/UDA-Benchmark"]
    repository_revision: Literal["fca5237ac316e776d8dbccffa55ca29c0efdc185"]
    huggingface_repository: Literal["qinchuanhui/UDA-QA"]
    huggingface_revision: Literal["d4367103fe8fe86b3bb76c66be8eafc4fb4117b2"]
    license: Literal["CC-BY-SA-4.0"]
    qa_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    predecessor_r3_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    predecessor_reserve_company_count: int = Field(ge=1)
    predecessor_reserve_company_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_seed: str = Field(min_length=16)
    minimum_questions_per_document: int = Field(ge=1)
    cases_per_document: int = Field(ge=1)
    dev_company_count: int = Field(ge=1)
    validation_company_count: int = Field(ge=1)
    test_company_count: int = Field(ge=1)
    dev_case_count: int = Field(ge=1)
    validation_case_count: int = Field(ge=1)
    test_case_count: int = Field(ge=1)
    selection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_id: Literal[
        "dense_focused_bm25_page_rrf_v1",
        "dense_dual_bm25_page_rrf_v2",
    ]
    baseline_candidate_k: Literal[40]
    baseline_max_chunks_per_doc: Literal[5]
    source_top_k: Literal[20]
    candidate_k: Literal[80]
    max_chunks_per_doc: Literal[10]
    lexical_weight: float = Field(ge=0, le=1)
    original_bm25_weight: float = Field(default=0.0, ge=0, le=1)
    rrf_k: Literal[60]
    parallel_search: bool = False
    development_selection_metric: Literal["page_ndcg_at_5"]
    min_page_hit_at_5_delta: float = Field(ge=0, le=1)
    min_page_ndcg_at_5_delta: float = Field(ge=0, le=1)
    max_p95_latency_multiplier: float = Field(ge=1)
    validation_execution_limit: Literal[1]
    test_execution_limit: Literal[1]

    @model_validator(mode="after")
    def validate_contract(self) -> UdaFinanceR4Protocol:
        if self.qa_sha256 != UDA_FIN_QA_SHA256:
            raise ValueError("R4 protocol does not bind the pinned UDA QA file")
        expected_candidate = (
            "dense_focused_bm25_page_rrf_v1"
            if self.schema_version == "uda_finance_r4_protocol_v1"
            else "dense_dual_bm25_page_rrf_v2"
        )
        if self.candidate_id != expected_candidate:
            raise ValueError("R4 candidate does not match its protocol version")
        expected_v2 = self.schema_version == "uda_finance_r4_protocol_v2"
        if (
            self.lexical_weight != 0.5
            or self.original_bm25_weight != (0.5 if expected_v2 else 0.0)
            or self.parallel_search is not expected_v2
        ):
            raise ValueError("R4 retrieval parameters do not match the protocol version")
        observed = {
            "dev": self.dev_case_count,
            "validation": self.validation_case_count,
            "test": self.test_case_count,
        }
        expected = {
            "dev": self.dev_company_count * self.cases_per_document,
            "validation": self.validation_company_count * self.cases_per_document,
            "test": self.test_company_count * self.cases_per_document,
        }
        if observed != expected:
            raise ValueError("R4 case counts do not match company and case quotas")
        if (
            sum(
                (
                    self.dev_company_count,
                    self.validation_company_count,
                    self.test_company_count,
                )
            )
            != self.predecessor_reserve_company_count
        ):
            raise ValueError("R4 must account for the complete predecessor reserve")
        return self


class UdaFinanceR4PreparedCase(_StrictModel):
    schema_version: Literal["uda_finance_r4_case_v1"] = "uda_finance_r4_case_v1"
    case_id: str = Field(min_length=1)
    split: R4Split
    company_id: str = Field(min_length=1)
    doc_name: str = Field(min_length=1)
    q_uid: str = Field(min_length=1)
    question: str = Field(min_length=1)
    answers: list[str] = Field(min_length=1, max_length=2)
    gold_doc_id: str = Field(min_length=1)
    page_number: int = Field(ge=1)


class UdaFinanceR4DatasetManifest(_StrictModel):
    schema_version: Literal["uda_finance_r4_dataset_v1"] = "uda_finance_r4_dataset_v1"
    baseline_revision: Literal["2065e571d77439babf76a763ac459a618950f218"] = (
        "2065e571d77439babf76a763ac459a618950f218"
    )
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    qa_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_count: int = Field(ge=3)
    pdf_total_bytes: int = Field(ge=1)
    split_case_counts: dict[R4Split, int]
    split_case_sha256: dict[R4Split, str]


def _stable_key(seed: str, value: str) -> str:
    return sha256_bytes(f"{seed}\0{value}".encode())


def load_uda_finance_r4_protocol(
    path: Path = R4_PROTOCOL_PATH,
) -> tuple[UdaFinanceR4Protocol, str]:
    content = Path(path).resolve().read_bytes()
    if not content or len(content) > 128 * 1024:
        raise ValueError("R4 protocol is empty or too large")
    return UdaFinanceR4Protocol.model_validate_json(content), sha256_bytes(content)


def select_uda_finance_r4_cases(
    rows: Sequence[UdaFinanceQaRow],
    *,
    reserve_company_ids: Sequence[str],
    seed: str,
    minimum_questions_per_document: int,
    cases_per_document: int,
    dev_company_count: int,
    validation_company_count: int,
    test_company_count: int,
) -> list[UdaFinanceR4Selection]:
    reserve = set(reserve_company_ids)
    if len(reserve) != len(reserve_company_ids):
        raise ValueError("R4 reserve company IDs must be unique")
    by_doc: dict[str, list[UdaFinanceQaRow]] = defaultdict(list)
    for row in rows:
        by_doc[row.doc_name].append(row)
    eligible_by_company: dict[str, list[str]] = defaultdict(list)
    for doc_name, doc_rows in by_doc.items():
        company = doc_rows[0].company_id
        if company in reserve and len(doc_rows) >= minimum_questions_per_document:
            eligible_by_company[company].append(doc_name)
    if set(eligible_by_company) != reserve:
        raise ValueError("R4 predecessor reserve is not fully eligible")
    ordered_companies = sorted(
        reserve,
        key=lambda company: (_stable_key(seed, f"company:{company}"), company),
    )
    boundaries = (dev_company_count, dev_company_count + validation_company_count)
    if boundaries[1] + test_company_count != len(ordered_companies):
        raise ValueError("R4 split counts do not consume the full reserve")
    selections: list[UdaFinanceR4Selection] = []
    for index, company in enumerate(ordered_companies):
        split: R4Split = (
            "dev" if index < boundaries[0] else "validation" if index < boundaries[1] else "test"
        )
        doc_name = min(
            eligible_by_company[company],
            key=lambda value: (_stable_key(seed, f"document:{value}"), value),
        )
        selected_rows = sorted(
            by_doc[doc_name],
            key=lambda row: (_stable_key(seed, f"case:{row.q_uid}"), row.q_uid),
        )[:cases_per_document]
        selections.append(
            UdaFinanceR4Selection(
                split=split,
                company_id=company,
                doc_name=doc_name,
                q_uids=sorted(row.q_uid for row in selected_rows),
            )
        )
    validate_r4_selection(selections, cases_per_document=cases_per_document)
    return selections


def validate_r4_selection(
    selections: Sequence[UdaFinanceR4Selection], *, cases_per_document: int
) -> None:
    companies = [item.company_id for item in selections]
    documents = [item.doc_name for item in selections]
    q_uids = [q_uid for item in selections for q_uid in item.q_uids]
    if len(companies) != len(set(companies)):
        raise ValueError("R4 company splits are not disjoint")
    if len(documents) != len(set(documents)):
        raise ValueError("R4 document splits are not disjoint")
    if len(q_uids) != len(set(q_uids)):
        raise ValueError("R4 selected questions are not unique")
    if any(len(item.q_uids) != cases_per_document for item in selections):
        raise ValueError("R4 selected document has the wrong case count")


def r4_selection_sha256(selections: Sequence[UdaFinanceR4Selection]) -> str:
    ordered = sorted(selections, key=lambda item: (item.split, item.company_id, item.doc_name))
    return sha256_bytes(canonical_json_bytes(ordered))


def verify_r4_protocol_selection(
    protocol: UdaFinanceR4Protocol,
    rows: Sequence[UdaFinanceQaRow],
    *,
    r3_protocol_path: Path = R3_PROTOCOL_PATH,
) -> list[UdaFinanceR4Selection]:
    r3_protocol, r3_protocol_sha256 = load_uda_finance_r3_protocol(r3_protocol_path)
    if r3_protocol_sha256 != protocol.predecessor_r3_protocol_sha256:
        raise ValueError("R4 predecessor protocol hash mismatch")
    _, reserve = verify_r3_protocol_selection(r3_protocol, rows)
    if len(reserve) != protocol.predecessor_reserve_company_count:
        raise ValueError("R4 predecessor reserve count mismatch")
    if r3_protocol.reserve_company_ids_sha256 != protocol.predecessor_reserve_company_ids_sha256:
        raise ValueError("R4 predecessor reserve identity mismatch")
    selections = select_uda_finance_r4_cases(
        rows,
        reserve_company_ids=reserve,
        seed=protocol.selection_seed,
        minimum_questions_per_document=protocol.minimum_questions_per_document,
        cases_per_document=protocol.cases_per_document,
        dev_company_count=protocol.dev_company_count,
        validation_company_count=protocol.validation_company_count,
        test_company_count=protocol.test_company_count,
    )
    if r4_selection_sha256(selections) != protocol.selection_sha256:
        raise ValueError("R4 selection does not match the frozen protocol")
    return selections


def prepare_uda_finance_r4(
    *,
    qa_path: Path,
    pdf_root: Path,
    source_root: Path = R4_SOURCE_ROOT,
    prepared_root: Path = R4_PREPARED_ROOT,
    protocol_path: Path = R4_PROTOCOL_PATH,
) -> UdaFinanceR4DatasetManifest:
    protocol, protocol_sha256 = load_uda_finance_r4_protocol(protocol_path)
    rows = load_uda_finance_rows(qa_path)
    selections = verify_r4_protocol_selection(protocol, rows)
    source_root = Path(source_root).resolve()
    prepared_root = Path(prepared_root).resolve()
    pdf_root = Path(pdf_root).resolve()
    document_root = source_root / "documents"
    document_root.mkdir(parents=True, exist_ok=True)
    row_by_uid = {row.q_uid: row for row in rows}
    documents: list[ManifestDocument] = []
    pdf_total_bytes = 0
    for doc_name in sorted({item.doc_name for item in selections}):
        source = (pdf_root / f"{doc_name}.pdf").resolve()
        source.relative_to(pdf_root)
        content = source.read_bytes()
        if not content.startswith(b"%PDF-"):
            raise ValueError(f"R4 UDA source is not a PDF: {doc_name}")
        target = document_root / source.name
        if target.exists() and target.read_bytes() != content:
            raise FileExistsError(f"R4 prepared PDF differs: {target}")
        if not target.exists():
            shutil.copyfile(source, target)
        pdf_total_bytes += len(content)
        _, year_text = doc_name.rsplit("_", 1)
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
                    version_id=f"{doc_id}-r4-v1",
                    version="r4.1",
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
    cases_by_split: dict[R4Split, list[UdaFinanceR4PreparedCase]] = {
        "dev": [],
        "validation": [],
        "test": [],
    }
    eval_by_split: dict[R4Split, list[EvalCase]] = {
        "dev": [],
        "validation": [],
        "test": [],
    }
    for selection in selections:
        for q_uid in selection.q_uids:
            row = row_by_uid[q_uid]
            case_id = f"uda-r4-{sha256_bytes(q_uid.encode('utf-8'))[:16]}"
            doc_id = _doc_id(row.doc_name)
            case = UdaFinanceR4PreparedCase(
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
                    tags=["external", "uda", "finance", "r4", selection.split],
                )
            )
    for split in _R4_SPLITS:
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
        generator_version="uda_finance_r4_adapter_v1",
        profile_id=R4_PROFILE_ID,
        seed=int(_stable_key(protocol.selection_seed, "corpus")[:8], 16),
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
    split_bytes: dict[R4Split, bytes] = {}
    for split in _R4_SPLITS:
        split_bytes[split] = canonical_json_bytes(cases_by_split[split])
        (eval_root / f"{split}_evidence.json").write_bytes(split_bytes[split])
        (eval_root / f"{split}.json").write_bytes(canonical_json_bytes(eval_by_split[split]))
    manifest = UdaFinanceR4DatasetManifest(
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
    (prepared_root / "external_dataset_manifest.json").write_bytes(canonical_json_bytes(manifest))
    return manifest


def verify_uda_finance_r4_preparation(
    *,
    source_root: Path = R4_SOURCE_ROOT,
    prepared_root: Path = R4_PREPARED_ROOT,
) -> UdaFinanceR4DatasetManifest:
    source_root = Path(source_root).resolve()
    prepared_root = Path(prepared_root).resolve()
    manifest = UdaFinanceR4DatasetManifest.model_validate_json(
        (prepared_root / "external_dataset_manifest.json").read_bytes()
    )
    corpus_bytes = (source_root / "manifest.json").read_bytes()
    if sha256_bytes(corpus_bytes) != manifest.corpus_manifest_sha256:
        raise ValueError("R4 corpus manifest hash mismatch")
    corpus = CorpusManifest.model_validate_json(corpus_bytes)
    if corpus.profile_id != R4_PROFILE_ID or len(corpus.documents) != manifest.document_count:
        raise ValueError("R4 corpus identity mismatch")
    for document in corpus.documents:
        path = (source_root / document.path).resolve()
        path.relative_to(source_root)
        content = path.read_bytes()
        if len(content) != document.byte_count or sha256_bytes(content) != document.sha256:
            raise ValueError(f"R4 PDF integrity mismatch: {document.doc_id}")
    for split in _R4_SPLITS:
        content = (prepared_root / "eval" / f"{split}_evidence.json").read_bytes()
        cases = [
            UdaFinanceR4PreparedCase.model_validate(item)
            for item in json.loads(content.decode("utf-8"))
        ]
        if len(cases) != manifest.split_case_counts[split]:
            raise ValueError(f"R4 {split} case count mismatch")
        if sha256_bytes(content) != manifest.split_case_sha256[split]:
            raise ValueError(f"R4 {split} case hash mismatch")
    return manifest


def load_uda_finance_r4_cases(
    prepared_root: Path, *, split: R4Split
) -> tuple[list[UdaFinanceR4PreparedCase], str]:
    path = Path(prepared_root).resolve() / "eval" / f"{split}_evidence.json"
    content = path.read_bytes()
    cases = [
        UdaFinanceR4PreparedCase.model_validate(item)
        for item in json.loads(content.decode("utf-8"))
    ]
    if not cases or any(case.split != split for case in cases):
        raise ValueError(f"R4 {split} case bundle is empty or misaligned")
    return cases, hashlib.sha256(content).hexdigest()


def _doc_id(doc_name: str) -> str:
    return f"uda-fin-{doc_name.lower().replace('_', '-')}"


__all__ = [
    "R4_PREPARED_ROOT",
    "R4_PRIVATE_ROOT",
    "R4_PROTOCOL_PATH",
    "R4_SOURCE_ROOT",
    "UdaFinanceR4DatasetManifest",
    "UdaFinanceR4PreparedCase",
    "UdaFinanceR4Protocol",
    "UdaFinanceR4Selection",
    "load_uda_finance_r4_cases",
    "load_uda_finance_r4_protocol",
    "prepare_uda_finance_r4",
    "r4_selection_sha256",
    "select_uda_finance_r4_cases",
    "verify_r4_protocol_selection",
    "verify_uda_finance_r4_preparation",
]
