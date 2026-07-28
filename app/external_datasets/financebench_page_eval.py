from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.corpus.schemas import EvalCase
from app.evaluation.page_retrieval import (
    PageReference,
    PageRetrievalCaseScore,
    score_page_retrieval,
)
from app.evaluation.retrieval import evaluate_retrieval_case
from app.external_datasets.financebench import (
    FINANCEBENCH_REVISION,
    FinanceBenchPreparedCase,
)
from app.filesystem import atomic_directory_move


_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_RUN_ARTIFACTS = {"summary.json", "details.jsonl"}


class FinanceBenchPageEvalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FinanceBenchPageFreezeConfiguration(FinanceBenchPageEvalModel):
    top_k: Literal[5] = 5
    candidate_k: Literal[20] = 20
    max_chunks_per_doc: Literal[2] = 2
    include_parent: Literal[True] = True
    page_drilldown: Literal[True] = True
    drilldown_max_documents: Literal[1] = 1
    drilldown_chunks_per_doc: Literal[5] = 5
    drilldown_mode: Literal["dense"] = "dense"
    metric_contract: Literal["unique_doc_page_v1"] = "unique_doc_page_v1"
    entity_scope: Literal["exact_year_plus_entity_history_v5"] = (
        "exact_year_plus_entity_history_v5"
    )


class FinanceBenchPageFreezeProtocol(FinanceBenchPageEvalModel):
    schema_version: Literal["financebench_page_retrieval_freeze_v1"] = (
        "financebench_page_retrieval_freeze_v1"
    )
    protocol_id: Literal["financebench-page-retrieval-v1"] = (
        "financebench-page-retrieval-v1"
    )
    dataset_revision: Literal[
        "cc39aeb4afdf33909ee1412188bf89035950c2eb"
    ] = FINANCEBENCH_REVISION
    selected_dev_run_id: str = Field(min_length=1, max_length=200)
    selected_dev_summary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    configuration: FinanceBenchPageFreezeConfiguration
    test_execution_policy: Literal[
        "explicit_confirmation_after_clean_committed_evaluator"
    ] = "explicit_confirmation_after_clean_committed_evaluator"


class FinanceBenchPageCaseResult(FinanceBenchPageEvalModel):
    case_id: str = Field(min_length=1, max_length=500)
    ranked_doc_ids: list[str] = Field(default_factory=list, max_length=20)
    document_recall_at_5: float = Field(ge=0.0, le=1.0)
    page_score: PageRetrievalCaseScore
    passed: bool
    latency_ms: float = Field(ge=0.0)
    page_search_count: int = Field(default=0, ge=0, le=20)
    page_search_latency_ms: float = Field(default=0.0, ge=0.0)
    stage_counts: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_result(self) -> "FinanceBenchPageCaseResult":
        if len(self.ranked_doc_ids) != len(set(self.ranked_doc_ids)):
            raise ValueError("ranked document IDs must be unique")
        if any(value < 0 for value in self.stage_counts.values()):
            raise ValueError("stage counts must be non-negative")
        expected_pass = (
            self.document_recall_at_5 == 1.0
            and self.page_score.passed_at_max_cutoff
        )
        if self.passed != expected_pass:
            raise ValueError("case pass does not match document and page metrics")
        return self


class FinanceBenchPageCutoffSummary(FinanceBenchPageEvalModel):
    cutoff: int = Field(ge=1, le=100)
    case_count: int = Field(ge=1)
    page_hit_count: int = Field(ge=0)
    complete_page_recall_count: int = Field(ge=0)
    page_hit_rate: float = Field(ge=0.0, le=1.0)
    complete_page_recall_rate: float = Field(ge=0.0, le=1.0)
    macro_page_recall: float = Field(ge=0.0, le=1.0)
    macro_page_precision: float = Field(ge=0.0, le=1.0)
    macro_page_locator_coverage: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_rates(self) -> "FinanceBenchPageCutoffSummary":
        if (
            self.page_hit_count > self.case_count
            or self.complete_page_recall_count > self.case_count
        ):
            raise ValueError("page summary counts exceed case count")
        if abs(self.page_hit_rate - self.page_hit_count / self.case_count) > 1e-12:
            raise ValueError("page hit rate does not match counts")
        expected_complete = self.complete_page_recall_count / self.case_count
        if abs(self.complete_page_recall_rate - expected_complete) > 1e-12:
            raise ValueError("complete page recall rate does not match counts")
        return self


class FinanceBenchPageRunSummary(FinanceBenchPageEvalModel):
    case_count: int = Field(ge=1)
    passed_case_count: int = Field(ge=0)
    passed_case_rate: float = Field(ge=0.0, le=1.0)
    document_recall_at_5_mean: float = Field(ge=0.0, le=1.0)
    latency_ms_mean: float = Field(ge=0.0)
    latency_ms_p95: float = Field(ge=0.0)
    cutoffs: list[FinanceBenchPageCutoffSummary] = Field(
        min_length=1,
        max_length=10,
    )

    @model_validator(mode="after")
    def validate_summary(self) -> "FinanceBenchPageRunSummary":
        if self.passed_case_count > self.case_count:
            raise ValueError("passed case count exceeds case count")
        if abs(self.passed_case_rate - self.passed_case_count / self.case_count) > 1e-12:
            raise ValueError("passed case rate does not match counts")
        cutoff_values = [item.cutoff for item in self.cutoffs]
        if cutoff_values != sorted(set(cutoff_values)):
            raise ValueError("summary cutoffs must be sorted and unique")
        if any(item.case_count != self.case_count for item in self.cutoffs):
            raise ValueError("cutoff summaries must cover every case")
        return self


class FinanceBenchArtifactEvidence(FinanceBenchPageEvalModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(ge=1)


class FinanceBenchPageRunManifest(FinanceBenchPageEvalModel):
    schema_version: Literal["financebench_page_retrieval_run_v1"] = (
        "financebench_page_retrieval_run_v1"
    )
    producer: Literal["enterprise_agentic_rag_v2"] = "enterprise_agentic_rag_v2"
    run_id: str = Field(min_length=1, max_length=200)
    split: Literal["dev", "test"] = "dev"
    created_at_utc: datetime
    dataset_revision: Literal[
        "cc39aeb4afdf33909ee1412188bf89035950c2eb"
    ] = FINANCEBENCH_REVISION
    source_hashes: dict[str, str]
    index_run_id: str = Field(min_length=1, max_length=500)
    index_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    entity_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_model: str = Field(min_length=1, max_length=200)
    embedding_calls: int = Field(ge=0)
    code_revision: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{40}$",
    )
    freeze_protocol_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    config: dict[str, int | str]
    summary: FinanceBenchPageRunSummary
    artifacts: dict[str, FinanceBenchArtifactEvidence]

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        if value in {".", ".."} or not _RUN_ID_PATTERN.fullmatch(value):
            raise ValueError("FinanceBench page run ID is invalid")
        return value

    @field_validator("source_hashes")
    @classmethod
    def validate_source_hashes(cls, values: dict[str, str]) -> dict[str, str]:
        if any(not _SHA256_PATTERN.fullmatch(value) for value in values.values()):
            raise ValueError("FinanceBench page source hash is invalid")
        return values

    @model_validator(mode="after")
    def validate_manifest(self) -> "FinanceBenchPageRunManifest":
        if (
            self.created_at_utc.tzinfo is None
            or self.created_at_utc.utcoffset() is None
        ):
            raise ValueError("run timestamp must be timezone-aware")
        if set(self.artifacts) != _RUN_ARTIFACTS:
            raise ValueError("FinanceBench page artifact set is invalid")
        expected_hashes = {
            "dataset_manifest",
            f"{self.split}_eval",
            f"{self.split}_evidence",
        }
        if set(self.source_hashes) != expected_hashes:
            raise ValueError("FinanceBench page source hash set is invalid")
        if self.split == "test" and (
            self.code_revision is None
            or self.freeze_protocol_sha256 is None
        ):
            raise ValueError(
                "FinanceBench test run requires code and freeze provenance"
            )
        return self


def load_financebench_bundle(
    prepared_root: Path,
    *,
    split: Literal["dev", "test"],
) -> tuple[list[EvalCase], list[FinanceBenchPreparedCase], dict[str, str]]:
    prepared_root = Path(prepared_root).resolve()
    eval_root = prepared_root / "eval"
    dataset_manifest_path = prepared_root / "external_dataset_manifest.json"
    eval_path = eval_root / f"{split}.json"
    evidence_path = eval_root / f"{split}_evidence.json"
    cases = [
        EvalCase.model_validate(item)
        for item in _read_json_array(eval_path)
    ]
    evidence_cases = [
        FinanceBenchPreparedCase.model_validate(item)
        for item in _read_json_array(evidence_path)
    ]
    _validate_bundle_alignment(cases, evidence_cases, split=split)
    return (
        cases,
        evidence_cases,
        {
            "dataset_manifest": _sha256(dataset_manifest_path),
            f"{split}_eval": _sha256(eval_path),
            f"{split}_evidence": _sha256(evidence_path),
        },
    )


def load_financebench_dev_bundle(
    prepared_root: Path,
) -> tuple[list[EvalCase], list[FinanceBenchPreparedCase], dict[str, str]]:
    return load_financebench_bundle(prepared_root, split="dev")


def load_financebench_page_freeze_protocol(
    path: Path,
) -> tuple[FinanceBenchPageFreezeProtocol, str]:
    path = Path(path).resolve()
    content = path.read_bytes()
    if not content or len(content) > 64 * 1024:
        raise ValueError("FinanceBench page freeze protocol is empty or too large")
    protocol = FinanceBenchPageFreezeProtocol.model_validate_json(content)
    return protocol, hashlib.sha256(content).hexdigest()


def evaluate_financebench_page_cases(
    *,
    cases: Sequence[EvalCase],
    evidence_cases: Sequence[FinanceBenchPreparedCase],
    pipeline,
    top_k: int = 5,
    candidate_k: int = 20,
    max_chunks_per_doc: int = 2,
    include_parent: bool = True,
    split: Literal["dev", "test"] = "dev",
    page_drilldown_backend=None,
    drilldown_max_documents: int = 3,
    drilldown_chunks_per_doc: int = 5,
    drilldown_mode: Literal["hybrid", "dense", "bm25"] = "hybrid",
) -> list[FinanceBenchPageCaseResult]:
    if top_k != 5:
        raise ValueError("FinanceBench page v1 requires top_k=5")
    if candidate_k < top_k or candidate_k > 200:
        raise ValueError("candidate_k must be between top_k and 200")
    if not 1 <= drilldown_max_documents <= 5:
        raise ValueError("drilldown_max_documents must be between 1 and 5")
    if not 1 <= drilldown_chunks_per_doc <= 10:
        raise ValueError("drilldown_chunks_per_doc must be between 1 and 10")
    _validate_bundle_alignment(cases, evidence_cases, split=split)
    evidence_by_id = {item.case_id: item for item in evidence_cases}
    results: list[FinanceBenchPageCaseResult] = []
    for case in cases:
        evaluated = evaluate_retrieval_case(
            case,
            pipeline,
            top_k=top_k,
            candidate_k=candidate_k,
            max_chunks_per_doc=max_chunks_per_doc,
            include_parent=include_parent,
        )
        evidence = evidence_by_id[case.case_id]
        page_hits = list(evaluated.observation.result.hits)
        page_search_count = 0
        page_search_latency_ms = 0.0
        page_stage_counts: dict[str, int] = {}
        if page_drilldown_backend is not None:
            drilldown_started = time.perf_counter()
            page_hits, page_search_count = _document_drilldown_hits(
                request=evaluated.observation.request,
                document_result=evaluated.observation.result,
                backend=page_drilldown_backend,
                max_documents=drilldown_max_documents,
                chunks_per_doc=drilldown_chunks_per_doc,
                output_k=top_k,
                mode=drilldown_mode,
            )
            page_search_latency_ms = (
                time.perf_counter() - drilldown_started
            ) * 1000
            page_stage_counts = {
                "page_drilldown_searches": page_search_count,
                "page_drilldown_returned": len(page_hits),
            }
        gold_pages = _unique_page_references(evidence)
        page_score = score_page_retrieval(
            case_id=case.case_id,
            hits=page_hits,
            gold_pages=gold_pages,
        )
        document_recall = float(
            evaluated.layer.metrics["document_recall@5"] or 0.0
        )
        results.append(
            FinanceBenchPageCaseResult(
                case_id=case.case_id,
                ranked_doc_ids=evaluated.observation.ranked_doc_ids,
                document_recall_at_5=document_recall,
                page_score=page_score,
                passed=document_recall == 1.0
                and page_score.passed_at_max_cutoff,
                latency_ms=(
                    evaluated.observation.latency_ms
                    + page_search_latency_ms
                ),
                page_search_count=page_search_count,
                page_search_latency_ms=page_search_latency_ms,
                stage_counts={
                    **evaluated.observation.result.stage_counts,
                    **page_stage_counts,
                    "gold_evidence_snippets": len(evidence.evidence),
                    "gold_unique_pages": len(gold_pages),
                },
            )
        )
    return results


def summarize_financebench_page_cases(
    details: Sequence[FinanceBenchPageCaseResult],
) -> FinanceBenchPageRunSummary:
    rows = list(details)
    if not rows:
        raise ValueError("FinanceBench page summary requires cases")
    cutoff_values = [item.cutoff for item in rows[0].page_score.cutoffs]
    if any(
        [item.cutoff for item in row.page_score.cutoffs] != cutoff_values
        for row in rows
    ):
        raise ValueError("FinanceBench page cases use different cutoffs")
    cutoff_summaries: list[FinanceBenchPageCutoffSummary] = []
    for index, cutoff in enumerate(cutoff_values):
        metrics = [row.page_score.cutoffs[index] for row in rows]
        page_hits = sum(item.page_hit for item in metrics)
        complete = sum(item.page_recall == 1.0 for item in metrics)
        cutoff_summaries.append(
            FinanceBenchPageCutoffSummary(
                cutoff=cutoff,
                case_count=len(rows),
                page_hit_count=page_hits,
                complete_page_recall_count=complete,
                page_hit_rate=page_hits / len(rows),
                complete_page_recall_rate=complete / len(rows),
                macro_page_recall=_mean(item.page_recall for item in metrics),
                macro_page_precision=_mean(
                    item.page_precision for item in metrics
                ),
                macro_page_locator_coverage=_mean(
                    item.page_locator_coverage for item in metrics
                ),
            )
        )
    latencies = sorted(item.latency_ms for item in rows)
    passed = sum(item.passed for item in rows)
    return FinanceBenchPageRunSummary(
        case_count=len(rows),
        passed_case_count=passed,
        passed_case_rate=passed / len(rows),
        document_recall_at_5_mean=_mean(
            item.document_recall_at_5 for item in rows
        ),
        latency_ms_mean=_mean(item.latency_ms for item in rows),
        latency_ms_p95=latencies[_nearest_rank_index(len(latencies), 0.95)],
        cutoffs=cutoff_summaries,
    )


def publish_financebench_page_run(
    *,
    root: Path,
    manifest: FinanceBenchPageRunManifest,
    details: Sequence[FinanceBenchPageCaseResult],
) -> Path:
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / manifest.run_id).resolve()
    if target.parent != root:
        raise ValueError("FinanceBench page run resolves outside output root")
    if target.exists():
        raise FileExistsError(f"output run already exists: {target}")
    if manifest.summary != summarize_financebench_page_cases(details):
        raise ValueError("manifest summary does not match page case details")
    stage = Path(
        tempfile.mkdtemp(prefix=f".{manifest.run_id}.staging-", dir=root)
    ).resolve()
    try:
        summary_bytes = _canonical_json_bytes(
            manifest.summary.model_dump(mode="json")
        )
        detail_bytes = b"".join(
            _canonical_json_bytes(item.model_dump(mode="json"))
            for item in details
        )
        artifact_bytes = {
            "summary.json": summary_bytes,
            "details.jsonl": detail_bytes,
        }
        artifacts = {
            name: FinanceBenchArtifactEvidence(
                sha256=hashlib.sha256(content).hexdigest(),
                byte_count=len(content),
            )
            for name, content in artifact_bytes.items()
        }
        final_manifest = manifest.model_copy(update={"artifacts": artifacts})
        for name, content in artifact_bytes.items():
            (stage / name).write_bytes(content)
        (stage / "manifest.json").write_bytes(
            _canonical_json_bytes(final_manifest.model_dump(mode="json"))
        )
        verify_financebench_page_run(stage)
        atomic_directory_move(stage, target)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return target


def verify_financebench_page_run(run_dir: Path) -> FinanceBenchPageRunManifest:
    run_dir = Path(run_dir).resolve()
    expected_files = {*_RUN_ARTIFACTS, "manifest.json"}
    actual_files = {
        path.name for path in run_dir.iterdir() if path.is_file()
    }
    if actual_files != expected_files or any(path.is_dir() for path in run_dir.iterdir()):
        raise ValueError("FinanceBench page run has an unexpected artifact set")
    manifest = FinanceBenchPageRunManifest.model_validate_json(
        (run_dir / "manifest.json").read_bytes()
    )
    if (
        manifest.run_id != run_dir.name
        and ".staging-" not in run_dir.name
    ):
        raise ValueError("FinanceBench page run directory and ID mismatch")
    for name, evidence in manifest.artifacts.items():
        path = run_dir / name
        if (
            path.stat().st_size != evidence.byte_count
            or _sha256(path) != evidence.sha256
        ):
            raise ValueError(f"FinanceBench page artifact mismatch: {name}")
    summary = FinanceBenchPageRunSummary.model_validate_json(
        (run_dir / "summary.json").read_bytes()
    )
    details = [
        FinanceBenchPageCaseResult.model_validate_json(line)
        for line in (run_dir / "details.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line
    ]
    if manifest.summary != summary:
        raise ValueError("FinanceBench page manifest summary mismatch")
    if summary != summarize_financebench_page_cases(details):
        raise ValueError("FinanceBench page summary does not recompute")
    return manifest


def build_financebench_page_manifest(
    *,
    run_id: str,
    source_hashes: dict[str, str],
    index_run_id: str,
    index_manifest_sha256: str,
    entity_catalog_sha256: str,
    embedding_model: str,
    embedding_calls: int,
    split: Literal["dev", "test"] = "dev",
    code_revision: str | None = None,
    freeze_protocol_sha256: str | None = None,
    candidate_k: int,
    max_chunks_per_doc: int,
    include_parent: bool,
    page_drilldown: bool,
    drilldown_max_documents: int,
    drilldown_chunks_per_doc: int,
    drilldown_mode: Literal["hybrid", "dense", "bm25"],
    summary: FinanceBenchPageRunSummary,
    created_at_utc: datetime | None = None,
) -> FinanceBenchPageRunManifest:
    return FinanceBenchPageRunManifest(
        run_id=run_id,
        split=split,
        created_at_utc=created_at_utc or datetime.now(timezone.utc),
        source_hashes=source_hashes,
        index_run_id=index_run_id,
        index_manifest_sha256=index_manifest_sha256,
        entity_catalog_sha256=entity_catalog_sha256,
        embedding_model=embedding_model,
        embedding_calls=embedding_calls,
        code_revision=code_revision,
        freeze_protocol_sha256=freeze_protocol_sha256,
        config={
            "top_k": 5,
            "candidate_k": candidate_k,
            "max_chunks_per_doc": max_chunks_per_doc,
            "include_parent": str(include_parent).lower(),
            "page_drilldown": str(page_drilldown).lower(),
            "drilldown_max_documents": drilldown_max_documents,
            "drilldown_chunks_per_doc": drilldown_chunks_per_doc,
            "drilldown_mode": drilldown_mode,
            "cutoffs": "1,3,5",
            "metric_contract": "unique_doc_page_v1",
            "entity_scope": "exact_year_plus_entity_history_v5",
        },
        summary=summary,
        artifacts={
            name: FinanceBenchArtifactEvidence(
                sha256="0" * 64,
                byte_count=1,
            )
            for name in sorted(_RUN_ARTIFACTS)
        },
    )


def _validate_bundle_alignment(
    cases: Sequence[EvalCase],
    evidence_cases: Sequence[FinanceBenchPreparedCase],
    *,
    split: Literal["dev", "test"],
) -> None:
    if not cases or not evidence_cases:
        raise ValueError("FinanceBench dev bundle must be non-empty")
    case_by_id = {item.case_id: item for item in cases}
    evidence_by_id = {item.case_id: item for item in evidence_cases}
    if len(case_by_id) != len(cases) or len(evidence_by_id) != len(evidence_cases):
        raise ValueError("FinanceBench dev bundle contains duplicate case IDs")
    if set(case_by_id) != set(evidence_by_id):
        raise ValueError("FinanceBench dev eval and evidence case IDs differ")
    for case_id, case in case_by_id.items():
        evidence = evidence_by_id[case_id]
        if evidence.split != split:
            raise ValueError(
                f"FinanceBench page bundle expected {split} evidence"
            )
        if (
            case.question != evidence.question
            or case.answer_mode != "answered"
            or case.gold_doc_ids != evidence.gold_doc_ids
        ):
            raise ValueError(
                f"FinanceBench dev eval/evidence mismatch: {case_id}"
            )


def _unique_page_references(
    evidence: FinanceBenchPreparedCase,
) -> list[PageReference]:
    keys = sorted(
        {
            (item.doc_id, item.page_number)
            for item in evidence.evidence
        }
    )
    return [
        PageReference(doc_id=doc_id, page_number=page_number)
        for doc_id, page_number in keys
    ]


def _document_drilldown_hits(
    *,
    request,
    document_result,
    backend,
    max_documents: int,
    chunks_per_doc: int,
    output_k: int,
    mode: Literal["hybrid", "dense", "bm25"],
):
    candidates: list[tuple[str, str]] = []
    seen_docs: set[str] = set()
    for hit in document_result.hits:
        if hit.doc_id in seen_docs or hit.policy_id is None:
            continue
        seen_docs.add(hit.doc_id)
        candidates.append((hit.doc_id, hit.policy_id))
        if len(candidates) == max_documents:
            break
    focused_requests = []
    for ordinal, (_, policy_id) in enumerate(candidates, start=1):
        filters = request.filters.model_copy(
            update={"policy_ids": [policy_id]}
        )
        focused_request = request.model_copy(
            update={
                "request_id": _drilldown_request_id(
                    request.request_id,
                    ordinal,
                ),
                "purpose": "evaluate FinanceBench document page drilldown",
                "filters": filters,
                "top_k": chunks_per_doc,
                "candidate_k": max(request.candidate_k, chunks_per_doc),
                "mode": mode,
                "include_parent": False,
                "max_chunks_per_doc": chunks_per_doc,
            }
        )
        focused_requests.append(focused_request)
    if not focused_requests:
        return [], 0
    search_many = getattr(backend, "search_many", None)
    if callable(search_many):
        raw_results = list(search_many(focused_requests))
    else:
        raw_results = [backend.search(item) for item in focused_requests]
    if len(raw_results) != len(focused_requests):
        raise ValueError(
            "page drilldown backend returned a different result count"
        )
    for focused_request, result in zip(
        focused_requests,
        raw_results,
        strict=True,
    ):
        if result.request_id != focused_request.request_id:
            raise ValueError(
                "page drilldown backend returned results out of order"
            )
    focused_results = [list(item.hits) for item in raw_results]
    selected = _weighted_document_pages(focused_results, output_k)
    return selected, len(focused_results)


def _drilldown_request_id(request_id: str, ordinal: int) -> str:
    suffix = f"-page-{ordinal}"
    return f"{request_id[: 200 - len(suffix)]}{suffix}"


def _weighted_document_pages(
    focused_results: Sequence[Sequence[Any]],
    output_k: int,
) -> list[Any]:
    if not focused_results:
        return []
    quotas = [1] * len(focused_results)
    quotas[0] += max(0, output_k - len(focused_results))
    selected: list[Any] = []
    seen_chunks: set[str] = set()
    for result, quota in zip(focused_results, quotas, strict=True):
        for hit in result:
            if hit.chunk_id in seen_chunks:
                continue
            seen_chunks.add(hit.chunk_id)
            selected.append(hit)
            if sum(
                item.doc_id == hit.doc_id for item in selected
            ) == quota:
                break
    return selected[:output_k]


def _read_json_array(path: Path) -> list[Any]:
    content = Path(path).read_bytes()
    if not content or len(content) > 64 * 1024 * 1024:
        raise ValueError(f"FinanceBench page input is empty or too large: {path.name}")
    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid FinanceBench page input: {path.name}") from exc
    if not isinstance(value, list):
        raise ValueError(f"FinanceBench page input must be an array: {path.name}")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _canonical_json_bytes(value: Any) -> bytes:
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _mean(values) -> float:
    items = list(values)
    if not items:
        raise ValueError("mean requires values")
    return sum(items) / len(items)


def _nearest_rank_index(count: int, percentile: float) -> int:
    return max(0, min(count - 1, int((count * percentile) + 0.999999) - 1))


__all__ = [
    "FinanceBenchPageCaseResult",
    "FinanceBenchPageFreezeConfiguration",
    "FinanceBenchPageFreezeProtocol",
    "FinanceBenchPageRunManifest",
    "FinanceBenchPageRunSummary",
    "build_financebench_page_manifest",
    "evaluate_financebench_page_cases",
    "load_financebench_bundle",
    "load_financebench_dev_bundle",
    "load_financebench_page_freeze_protocol",
    "publish_financebench_page_run",
    "summarize_financebench_page_cases",
    "verify_financebench_page_run",
]
