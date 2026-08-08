from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.domain.queries import QueryFilters, SearchRequest, UserContext
from app.evaluation.page_retrieval import (
    PageReference,
    PageRetrievalCaseScore,
    score_page_retrieval,
)
from app.external_datasets.uda_finance import UdaFinancePreparedCase


RetrievalArm = Literal["bm25", "dense", "hybrid_rrf"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class UdaFinancePageCaseResult(_StrictModel):
    case_id: str = Field(min_length=1)
    gold_doc_id: str = Field(min_length=1)
    gold_page_number: int = Field(ge=1)
    score: PageRetrievalCaseScore
    latency_ms: float = Field(ge=0)
    stage_counts: dict[str, int] = Field(default_factory=dict)


class UdaFinancePageSummary(_StrictModel):
    schema_version: Literal["uda_finance_page_summary_v1"] = (
        "uda_finance_page_summary_v1"
    )
    case_count: int = Field(ge=1)
    page_hit_at_1: float = Field(ge=0, le=1)
    page_hit_at_3: float = Field(ge=0, le=1)
    page_hit_at_5: float = Field(ge=0, le=1)
    page_mrr_at_5: float = Field(ge=0, le=1)
    page_ndcg_at_5: float = Field(ge=0, le=1)
    macro_page_recall_at_5: float = Field(ge=0, le=1)
    page_locator_coverage_at_5: float = Field(ge=0, le=1)
    latency_ms_mean: float = Field(ge=0)
    latency_ms_p50: float = Field(ge=0)
    latency_ms_p95: float = Field(ge=0)
    embedding_calls: int = Field(ge=0)


class UdaFinancePageRunManifest(_StrictModel):
    schema_version: Literal["uda_finance_page_run_v1"] = (
        "uda_finance_page_run_v1"
    )
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    split: Literal["dev", "test"]
    retrieval_arm: RetrievalArm
    code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cases_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    index_run_id: str = Field(min_length=1)
    index_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_model: str = Field(min_length=1)
    candidate_k: int = Field(ge=5, le=200)
    max_chunks_per_doc: int = Field(ge=5, le=10)
    include_parent: bool
    summary: UdaFinancePageSummary
    details_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    summary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def load_uda_finance_cases(
    prepared_root: Path, *, split: Literal["dev", "test"]
) -> tuple[list[UdaFinancePreparedCase], str]:
    path = Path(prepared_root).resolve() / "eval" / f"{split}_evidence.json"
    content = path.read_bytes()
    cases = [
        UdaFinancePreparedCase.model_validate(item)
        for item in json.loads(content.decode("utf-8"))
    ]
    if not cases or any(case.split != split for case in cases):
        raise ValueError(f"UDA {split} case bundle is empty or misaligned")
    return cases, hashlib.sha256(content).hexdigest()


def evaluate_uda_finance_pages(
    *,
    cases: Sequence[UdaFinancePreparedCase],
    pipeline,
    retrieval_arm: RetrievalArm,
    candidate_k: int = 20,
    max_chunks_per_doc: int = 5,
    include_parent: bool = False,
) -> list[UdaFinancePageCaseResult]:
    if candidate_k < 5 or candidate_k > 200:
        raise ValueError("UDA candidate_k must be between 5 and 200")
    if max_chunks_per_doc < 5 or max_chunks_per_doc > 10:
        raise ValueError("UDA max_chunks_per_doc must be between 5 and 10")
    mode = {
        "bm25": "bm25",
        "dense": "dense",
        "hybrid_rrf": "hybrid",
    }[retrieval_arm]
    user = UserContext(
        user_id="uda-evaluator",
        tenant_id="uda-external",
        region="global",
        groups=["uda-evaluator"],
    )
    results: list[UdaFinancePageCaseResult] = []
    for case in cases:
        request = SearchRequest(
            request_id=f"eval-{case.case_id}",
            query=case.question,
            purpose=f"UDA document-conditioned {retrieval_arm} page retrieval",
            user=user,
            filters=QueryFilters(
                policy_ids=[case.gold_doc_id],
                temporal_scope="all",
                authoritative_only=False,
            ),
            top_k=5,
            candidate_k=candidate_k,
            mode=mode,
            include_parent=include_parent,
            max_chunks_per_doc=max_chunks_per_doc,
            timeout_ms=120_000,
        )
        started = time.perf_counter()
        response = pipeline.search(request)
        latency_ms = (time.perf_counter() - started) * 1000
        score = score_page_retrieval(
            case_id=case.case_id,
            hits=response.hits,
            gold_pages=[
                PageReference(
                    doc_id=case.gold_doc_id,
                    page_number=case.page_number,
                )
            ],
        )
        results.append(
            UdaFinancePageCaseResult(
                case_id=case.case_id,
                gold_doc_id=case.gold_doc_id,
                gold_page_number=case.page_number,
                score=score,
                latency_ms=latency_ms,
                stage_counts=response.stage_counts,
            )
        )
    return results


def summarize_uda_finance_pages(
    details: Sequence[UdaFinancePageCaseResult], *, embedding_calls: int
) -> UdaFinancePageSummary:
    rows = list(details)
    if not rows:
        raise ValueError("UDA page summary requires cases")
    latencies = sorted(item.latency_ms for item in rows)
    hit_by_cutoff = {
        cutoff: sum(
            next(metric for metric in row.score.cutoffs if metric.cutoff == cutoff).page_hit
            for row in rows
        )
        / len(rows)
        for cutoff in (1, 3, 5)
    }
    reciprocal_ranks: list[float] = []
    discounted_gains: list[float] = []
    for row in rows:
        rank = next(
            (
                page.first_hit_rank
                for page in row.score.ranked_pages
                if page.doc_id == row.gold_doc_id
                and page.page_number == row.gold_page_number
                and page.first_hit_rank <= 5
            ),
            None,
        )
        reciprocal_ranks.append(0.0 if rank is None else 1.0 / rank)
        discounted_gains.append(
            0.0 if rank is None else 1.0 / math.log2(rank + 1)
        )
    at_five = [
        next(metric for metric in row.score.cutoffs if metric.cutoff == 5)
        for row in rows
    ]
    return UdaFinancePageSummary(
        case_count=len(rows),
        page_hit_at_1=hit_by_cutoff[1],
        page_hit_at_3=hit_by_cutoff[3],
        page_hit_at_5=hit_by_cutoff[5],
        page_mrr_at_5=sum(reciprocal_ranks) / len(rows),
        page_ndcg_at_5=sum(discounted_gains) / len(rows),
        macro_page_recall_at_5=sum(item.page_recall for item in at_five) / len(rows),
        page_locator_coverage_at_5=(
            sum(item.page_locator_coverage for item in at_five) / len(rows)
        ),
        latency_ms_mean=sum(latencies) / len(latencies),
        latency_ms_p50=latencies[_nearest_rank_index(len(latencies), 0.50)],
        latency_ms_p95=latencies[_nearest_rank_index(len(latencies), 0.95)],
        embedding_calls=embedding_calls,
    )


def publish_uda_finance_page_run(
    *,
    root: Path,
    run_id: str,
    split: Literal["dev", "test"],
    retrieval_arm: RetrievalArm,
    code_revision: str,
    protocol_sha256: str,
    dataset_manifest_sha256: str,
    cases_sha256: str,
    index_run_id: str,
    index_manifest_sha256: str,
    embedding_model: str,
    candidate_k: int,
    max_chunks_per_doc: int,
    include_parent: bool,
    details: Sequence[UdaFinancePageCaseResult],
    summary: UdaFinancePageSummary,
) -> Path:
    run_dir = Path(root).resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    detail_bytes = b"".join(
        _canonical_json_bytes(item.model_dump(mode="json")) for item in details
    )
    summary_bytes = _canonical_json_bytes(summary.model_dump(mode="json"))
    manifest = UdaFinancePageRunManifest(
        run_id=run_id,
        split=split,
        retrieval_arm=retrieval_arm,
        code_revision=code_revision,
        protocol_sha256=protocol_sha256,
        dataset_manifest_sha256=dataset_manifest_sha256,
        cases_sha256=cases_sha256,
        index_run_id=index_run_id,
        index_manifest_sha256=index_manifest_sha256,
        embedding_model=embedding_model,
        candidate_k=candidate_k,
        max_chunks_per_doc=max_chunks_per_doc,
        include_parent=include_parent,
        summary=summary,
        details_sha256=hashlib.sha256(detail_bytes).hexdigest(),
        summary_sha256=hashlib.sha256(summary_bytes).hexdigest(),
    )
    (run_dir / "details.jsonl").write_bytes(detail_bytes)
    (run_dir / "summary.json").write_bytes(summary_bytes)
    (run_dir / "manifest.json").write_bytes(
        _canonical_json_bytes(manifest.model_dump(mode="json"))
    )
    return run_dir


def verify_uda_finance_page_run(path: Path) -> UdaFinancePageRunManifest:
    run_dir = Path(path).resolve()
    manifest = UdaFinancePageRunManifest.model_validate_json(
        (run_dir / "manifest.json").read_bytes()
    )
    for name, expected in (
        ("details.jsonl", manifest.details_sha256),
        ("summary.json", manifest.summary_sha256),
    ):
        if hashlib.sha256((run_dir / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"UDA page run {name} hash mismatch")
    return manifest


def _canonical_json_bytes(value: object) -> bytes:
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


def _nearest_rank_index(count: int, percentile: float) -> int:
    return max(0, math.ceil(percentile * count) - 1)


__all__ = [
    "UdaFinancePageCaseResult",
    "UdaFinancePageRunManifest",
    "UdaFinancePageSummary",
    "evaluate_uda_finance_pages",
    "load_uda_finance_cases",
    "publish_uda_finance_page_run",
    "summarize_uda_finance_pages",
    "verify_uda_finance_page_run",
]
