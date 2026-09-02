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
    DEFAULT_PROTOCOL_PATH,
    UDA_FIN_QA_SHA256,
    UdaFinancePreparedCase,
    UdaFinanceQaRow,
    canonical_json_bytes,
    load_uda_finance_protocol,
    load_uda_finance_rows,
    select_uda_finance_cases,
    sha256_bytes,
)
from app.external_datasets.uda_finance_r3 import (
    R3_PROTOCOL_PATH,
    load_uda_finance_r3_protocol,
    verify_r3_protocol_selection,
)

R5_PRIVATE_ROOT = Path(".private") / "external" / "uda_finance" / "r5"
R5_SOURCE_ROOT = R5_PRIVATE_ROOT / "corpus"
R5_PREPARED_ROOT = R5_PRIVATE_ROOT / "prepared"
R5_PROTOCOL_PATH = Path("docs") / "r5" / "evidence" / "uda_finance_r5_protocol_v1.json"
R4_V3_PROTOCOL_PATH = Path("docs") / "r4" / "evidence" / "uda_finance_r4_protocol_v3.json"
R5_PROFILE_ID = "uda-finance-r5-fresh-confirmation-v1"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class UdaFinanceR5Selection(_StrictModel):
    company_id: str = Field(min_length=1)
    doc_name: str = Field(pattern=r"^[A-Za-z0-9.-]+_\d{4}$")
    q_uids: list[str] = Field(min_length=1)


class UdaFinanceR5Protocol(_StrictModel):
    schema_version: Literal["uda_finance_r5_protocol_v1"]
    dataset: Literal["UDA-QA/FinHybrid"]
    repository_revision: Literal["fca5237ac316e776d8dbccffa55ca29c0efdc185"]
    huggingface_revision: Literal["d4367103fe8fe86b3bb76c66be8eafc4fb4117b2"]
    license: Literal["CC-BY-SA-4.0"]
    qa_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    predecessor_page_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    predecessor_r3_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    predecessor_r4_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    excluded_company_count: int = Field(ge=1)
    excluded_company_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_seed: str = Field(min_length=16)
    minimum_questions_per_document: int = Field(ge=1)
    company_count: int = Field(ge=20)
    max_cases_per_document: int = Field(ge=1)
    case_count: int = Field(ge=1)
    selection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_id: Literal["dense_dual_bm25_shared_scope_page_rrf_v3"]
    baseline_candidate_k: Literal[40]
    baseline_max_chunks_per_doc: Literal[5]
    source_top_k: Literal[20]
    candidate_k: Literal[80]
    max_chunks_per_doc: Literal[10]
    lexical_weight: float = Field(ge=0, le=1)
    original_bm25_weight: float = Field(ge=0, le=1)
    rrf_k: Literal[60]
    shared_scope_search: Literal[True]
    bootstrap_seed: int
    bootstrap_iterations: int = Field(ge=10_000)
    min_page_hit_at_5_delta: float = Field(ge=0, le=1)
    min_page_ndcg_at_5_delta: float = Field(ge=0, le=1)
    require_hit_bootstrap_lower_bound_positive: Literal[True]
    require_ndcg_bootstrap_lower_bound_positive: Literal[True]
    require_rescues_exceed_regressions: Literal[True]
    max_p95_latency_multiplier: float = Field(ge=1)
    execution_limit: Literal[1]

    @model_validator(mode="after")
    def validate_contract(self) -> UdaFinanceR5Protocol:
        if self.qa_sha256 != UDA_FIN_QA_SHA256:
            raise ValueError("R5 protocol does not bind the pinned UDA QA file")
        if self.minimum_questions_per_document > self.max_cases_per_document:
            raise ValueError("R5 minimum question count exceeds the maximum case quota")
        if self.case_count < self.company_count * self.minimum_questions_per_document:
            raise ValueError("R5 case count is below the minimum company coverage")
        if self.lexical_weight != 0.5 or self.original_bm25_weight != 0.5:
            raise ValueError("R5 must preserve the frozen equal lexical weights")
        return self


class UdaFinanceR5DatasetManifest(_StrictModel):
    schema_version: Literal["uda_finance_r5_dataset_v1"] = "uda_finance_r5_dataset_v1"
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    qa_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_count: int = Field(ge=1)
    case_count: int = Field(ge=1)
    cases_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pdf_total_bytes: int = Field(ge=1)


def stable_key(seed: str, value: str) -> str:
    return sha256_bytes(f"{seed}\0{value}".encode())


def load_uda_finance_r5_protocol(
    path: Path = R5_PROTOCOL_PATH,
) -> tuple[UdaFinanceR5Protocol, str]:
    content = Path(path).resolve().read_bytes()
    if not content or len(content) > 128 * 1024:
        raise ValueError("R5 protocol is empty or too large")
    return UdaFinanceR5Protocol.model_validate_json(content), sha256_bytes(content)


def consumed_company_ids(
    rows: Sequence[UdaFinanceQaRow],
    *,
    page_protocol_path: Path = DEFAULT_PROTOCOL_PATH,
    r3_protocol_path: Path = R3_PROTOCOL_PATH,
) -> list[str]:
    page_protocol, _ = load_uda_finance_protocol(page_protocol_path)
    page_selections = select_uda_finance_cases(
        rows,
        seed=page_protocol.selection_seed,
        minimum_questions_per_document=page_protocol.minimum_questions_per_document,
        dev_company_count=page_protocol.dev_company_count,
        test_company_count=page_protocol.test_company_count,
        cases_per_document=page_protocol.cases_per_document,
    )
    r3_protocol, _ = load_uda_finance_r3_protocol(r3_protocol_path)
    r3_selections, r4_reserve = verify_r3_protocol_selection(r3_protocol, rows)
    return sorted(
        {
            *(item.company_id for item in page_selections),
            *(item.company_id for item in r3_selections),
            *r4_reserve,
        }
    )


def company_ids_sha256(company_ids: Sequence[str]) -> str:
    return sha256_bytes(canonical_json_bytes(sorted(company_ids)))


def select_uda_finance_r5_cases(
    rows: Sequence[UdaFinanceQaRow],
    *,
    excluded_company_ids: Sequence[str],
    seed: str,
    minimum_questions_per_document: int,
    company_count: int,
    max_cases_per_document: int,
) -> list[UdaFinanceR5Selection]:
    if minimum_questions_per_document > max_cases_per_document:
        raise ValueError("minimum questions cannot exceed the maximum case quota")
    excluded = set(excluded_company_ids)
    if len(excluded) != len(excluded_company_ids):
        raise ValueError("R5 excluded company IDs must be unique")
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
    if len(ordered_companies) < company_count:
        raise ValueError("UDA finance data has too few fresh eligible companies")
    selections: list[UdaFinanceR5Selection] = []
    for company in ordered_companies[:company_count]:
        doc_name = min(
            eligible_by_company[company],
            key=lambda value: (
                -len(by_doc[value]),
                stable_key(seed, f"document:{value}"),
                value,
            ),
        )
        chosen = sorted(
            by_doc[doc_name],
            key=lambda row: (stable_key(seed, f"case:{row.q_uid}"), row.q_uid),
        )[:max_cases_per_document]
        selections.append(
            UdaFinanceR5Selection(
                company_id=company,
                doc_name=doc_name,
                q_uids=sorted(row.q_uid for row in chosen),
            )
        )
    _validate_selection(
        selections,
        minimum_questions_per_document=minimum_questions_per_document,
        max_cases_per_document=max_cases_per_document,
    )
    return selections


def selection_sha256(selections: Sequence[UdaFinanceR5Selection]) -> str:
    ordered = sorted(selections, key=lambda item: (item.company_id, item.doc_name))
    return sha256_bytes(canonical_json_bytes(ordered))


def verify_r5_protocol_selection(
    protocol: UdaFinanceR5Protocol,
    rows: Sequence[UdaFinanceQaRow],
    *,
    page_protocol_path: Path = DEFAULT_PROTOCOL_PATH,
    r3_protocol_path: Path = R3_PROTOCOL_PATH,
    r4_protocol_path: Path = R4_V3_PROTOCOL_PATH,
) -> list[UdaFinanceR5Selection]:
    page_bytes = Path(page_protocol_path).read_bytes()
    r3_bytes = Path(r3_protocol_path).read_bytes()
    r4_bytes = Path(r4_protocol_path).read_bytes()
    if hashlib.sha256(page_bytes).hexdigest() != protocol.predecessor_page_protocol_sha256:
        raise ValueError("R5 predecessor page protocol hash mismatch")
    if hashlib.sha256(r3_bytes).hexdigest() != protocol.predecessor_r3_protocol_sha256:
        raise ValueError("R5 predecessor R3 protocol hash mismatch")
    if hashlib.sha256(r4_bytes).hexdigest() != protocol.predecessor_r4_protocol_sha256:
        raise ValueError("R5 predecessor R4 protocol hash mismatch")
    excluded = consumed_company_ids(
        rows,
        page_protocol_path=page_protocol_path,
        r3_protocol_path=r3_protocol_path,
    )
    if len(excluded) != protocol.excluded_company_count:
        raise ValueError("R5 excluded company count mismatch")
    if company_ids_sha256(excluded) != protocol.excluded_company_ids_sha256:
        raise ValueError("R5 excluded company identity mismatch")
    selections = select_uda_finance_r5_cases(
        rows,
        excluded_company_ids=excluded,
        seed=protocol.selection_seed,
        minimum_questions_per_document=protocol.minimum_questions_per_document,
        company_count=protocol.company_count,
        max_cases_per_document=protocol.max_cases_per_document,
    )
    if selection_sha256(selections) != protocol.selection_sha256:
        raise ValueError("R5 selection does not match the frozen protocol")
    return selections


def prepare_uda_finance_r5(
    *,
    qa_path: Path,
    pdf_root: Path,
    source_root: Path = R5_SOURCE_ROOT,
    prepared_root: Path = R5_PREPARED_ROOT,
    protocol_path: Path = R5_PROTOCOL_PATH,
) -> UdaFinanceR5DatasetManifest:
    protocol, protocol_sha256 = load_uda_finance_r5_protocol(protocol_path)
    rows = load_uda_finance_rows(qa_path)
    selections = verify_r5_protocol_selection(protocol, rows)
    source_root = Path(source_root).resolve()
    prepared_root = Path(prepared_root).resolve()
    pdf_root = Path(pdf_root).resolve()
    documents_root = source_root / "documents"
    documents_root.mkdir(parents=True, exist_ok=True)
    row_by_uid = {row.q_uid: row for row in rows}
    documents: list[ManifestDocument] = []
    pdf_total_bytes = 0
    for doc_name in sorted(item.doc_name for item in selections):
        source = (pdf_root / f"{doc_name}.pdf").resolve()
        source.relative_to(pdf_root)
        content = source.read_bytes()
        if not content.startswith(b"%PDF-"):
            raise ValueError(f"R5 UDA source is not a PDF: {doc_name}")
        target = documents_root / source.name
        if target.exists() and target.read_bytes() != content:
            raise FileExistsError(f"R5 prepared PDF differs: {target}")
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
                    version_id=f"{doc_id}-r5-v1",
                    version="r5.1",
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
    cases: list[UdaFinancePreparedCase] = []
    eval_cases: list[EvalCase] = []
    for selection in selections:
        for q_uid in selection.q_uids:
            row = row_by_uid[q_uid]
            case_id = f"uda-r5-{sha256_bytes(q_uid.encode('utf-8'))[:16]}"
            doc_id = _doc_id(row.doc_name)
            cases.append(
                UdaFinancePreparedCase(
                    case_id=case_id,
                    split="test",
                    company_id=row.company_id,
                    doc_name=row.doc_name,
                    q_uid=row.q_uid,
                    question=row.question,
                    answers=[value for value in (row.answer_1, row.answer_2) if value],
                    gold_doc_id=doc_id,
                    page_number=row.page_number,
                )
            )
            eval_cases.append(
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
                    tags=["external", "uda", "finance", "r5", "confirmation"],
                )
            )
    cases.sort(key=lambda item: item.case_id)
    eval_cases.sort(key=lambda item: item.case_id)
    corpus = CorpusManifest(
        schema_version="enterprise_corpus_manifest_v1",
        producer="enterprise_agentic_rag_v2",
        generator_version="uda_finance_r5_adapter_v1",
        profile_id=R5_PROFILE_ID,
        seed=int(stable_key(protocol.selection_seed, "corpus")[:8], 16),
        facts_sha256=protocol.qa_sha256,
        profile_sha256=sha256_bytes(
            canonical_json_bytes(
                {"protocol_sha256": protocol_sha256, "selection_sha256": protocol.selection_sha256}
            )
        ),
        document_count=len(documents),
        counts_by_format={"pdf": len(documents)},
        counts_by_source_type={"filing": len(documents)},
        counts_by_variant={"authoritative": len(documents)},
        documents=documents,
    )
    corpus_bytes = canonical_json_bytes(corpus)
    source_root.mkdir(parents=True, exist_ok=True)
    (source_root / "manifest.json").write_bytes(corpus_bytes)
    eval_root = prepared_root / "eval"
    eval_root.mkdir(parents=True, exist_ok=True)
    case_bytes = canonical_json_bytes(cases)
    (eval_root / "confirmation_evidence.json").write_bytes(case_bytes)
    (eval_root / "confirmation.json").write_bytes(canonical_json_bytes(eval_cases))
    manifest = UdaFinanceR5DatasetManifest(
        protocol_sha256=protocol_sha256,
        selection_sha256=protocol.selection_sha256,
        qa_sha256=protocol.qa_sha256,
        corpus_manifest_sha256=sha256_bytes(corpus_bytes),
        document_count=len(documents),
        case_count=len(cases),
        cases_sha256=sha256_bytes(case_bytes),
        pdf_total_bytes=pdf_total_bytes,
    )
    prepared_root.mkdir(parents=True, exist_ok=True)
    (prepared_root / "external_dataset_manifest.json").write_bytes(canonical_json_bytes(manifest))
    return manifest


def verify_uda_finance_r5_preparation(
    *,
    source_root: Path = R5_SOURCE_ROOT,
    prepared_root: Path = R5_PREPARED_ROOT,
) -> UdaFinanceR5DatasetManifest:
    source_root = Path(source_root).resolve()
    prepared_root = Path(prepared_root).resolve()
    manifest = UdaFinanceR5DatasetManifest.model_validate_json(
        (prepared_root / "external_dataset_manifest.json").read_bytes()
    )
    corpus_bytes = (source_root / "manifest.json").read_bytes()
    if sha256_bytes(corpus_bytes) != manifest.corpus_manifest_sha256:
        raise ValueError("R5 corpus manifest hash mismatch")
    corpus = CorpusManifest.model_validate_json(corpus_bytes)
    if corpus.profile_id != R5_PROFILE_ID or len(corpus.documents) != manifest.document_count:
        raise ValueError("R5 corpus identity mismatch")
    for document in corpus.documents:
        path = (source_root / document.path).resolve()
        path.relative_to(source_root)
        content = path.read_bytes()
        if len(content) != document.byte_count or sha256_bytes(content) != document.sha256:
            raise ValueError(f"R5 PDF integrity mismatch: {document.doc_id}")
    case_bytes = (prepared_root / "eval" / "confirmation_evidence.json").read_bytes()
    cases = [
        UdaFinancePreparedCase.model_validate(item)
        for item in json.loads(case_bytes.decode("utf-8"))
    ]
    if len(cases) != manifest.case_count or sha256_bytes(case_bytes) != manifest.cases_sha256:
        raise ValueError("R5 confirmation case integrity mismatch")
    return manifest


def load_uda_finance_r5_cases(
    prepared_root: Path = R5_PREPARED_ROOT,
) -> tuple[list[UdaFinancePreparedCase], str]:
    content = (Path(prepared_root).resolve() / "eval" / "confirmation_evidence.json").read_bytes()
    cases = [
        UdaFinancePreparedCase.model_validate(item) for item in json.loads(content.decode("utf-8"))
    ]
    if not cases or any(case.split != "test" for case in cases):
        raise ValueError("R5 confirmation bundle is empty or misaligned")
    return cases, sha256_bytes(content)


def _validate_selection(
    selections: Sequence[UdaFinanceR5Selection],
    *,
    minimum_questions_per_document: int,
    max_cases_per_document: int,
) -> None:
    companies = [item.company_id for item in selections]
    documents = [item.doc_name for item in selections]
    q_uids = [q_uid for item in selections for q_uid in item.q_uids]
    if len(companies) != len(set(companies)):
        raise ValueError("R5 companies must be disjoint")
    if len(documents) != len(set(documents)):
        raise ValueError("R5 documents must be disjoint")
    if len(q_uids) != len(set(q_uids)):
        raise ValueError("R5 questions must be unique")
    if any(
        not minimum_questions_per_document <= len(item.q_uids) <= max_cases_per_document
        for item in selections
    ):
        raise ValueError("R5 selected document has a case count outside the frozen bounds")


def _doc_id(doc_name: str) -> str:
    return f"uda-fin-{doc_name.lower().replace('_', '-')}"


__all__ = [
    "R5_PREPARED_ROOT",
    "R5_PRIVATE_ROOT",
    "R5_PROTOCOL_PATH",
    "R5_SOURCE_ROOT",
    "UdaFinanceR5DatasetManifest",
    "UdaFinanceR5Protocol",
    "UdaFinanceR5Selection",
    "company_ids_sha256",
    "consumed_company_ids",
    "load_uda_finance_r5_cases",
    "load_uda_finance_r5_protocol",
    "prepare_uda_finance_r5",
    "select_uda_finance_r5_cases",
    "selection_sha256",
    "verify_r5_protocol_selection",
    "verify_uda_finance_r5_preparation",
]
