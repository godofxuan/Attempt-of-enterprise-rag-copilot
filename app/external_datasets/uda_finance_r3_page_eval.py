from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.documents import ChunkRecord
from app.domain.queries import SearchHit, SearchRequest, SearchResult
from app.external_datasets.uda_finance_page_eval import (
    UdaFinancePageCaseResult,
    UdaFinancePageSummary,
)
from app.external_datasets.uda_finance_r3 import R3Split


R3PageStrategy = Literal[
    "dense_chunk",
    "dense_page_max",
    "dense_page_neighbor",
    "dense_page_structure",
]
R3_PAGE_PROTOCOL_PATH = (
    Path("docs") / "r3" / "evidence" / "uda_finance_r3_page_protocol_v1.json"
)
_NUMBER = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)*(?:%|x)?", re.IGNORECASE)
_ARITHMETIC_CUES = (
    "percent",
    "percentage",
    "ratio",
    "average",
    "increase",
    "decrease",
    "change",
    "difference",
    "growth",
    "how much",
    "what was",
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class R3StrategyRun(_StrictModel):
    strategy: R3PageStrategy
    summary: UdaFinancePageSummary
    details_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class R3PageCampaignManifest(_StrictModel):
    schema_version: Literal["uda_finance_r3_page_campaign_v1"] = (
        "uda_finance_r3_page_campaign_v1"
    )
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    split: R3Split
    code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    dataset_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cases_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    index_run_id: str = Field(min_length=1)
    index_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_model: str = Field(min_length=1)
    candidate_k: int = Field(ge=5, le=200)
    strategies: list[R3StrategyRun] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_strategies(self) -> "R3PageCampaignManifest":
        names = [item.strategy for item in self.strategies]
        if len(names) != len(set(names)):
            raise ValueError("R3 page campaign strategies must be unique")
        return self


def page_key(hit: SearchHit) -> tuple[str, int] | None:
    locator = hit.locator
    if locator is None or locator.kind != "page" or locator.end != locator.start:
        return None
    return hit.doc_id, locator.start


def build_page_representatives(
    chunks: Sequence[ChunkRecord],
) -> dict[tuple[str, int], SearchHit]:
    grouped: dict[tuple[str, int], list[ChunkRecord]] = defaultdict(list)
    for chunk in chunks:
        if chunk.locator.kind == "page" and chunk.locator.end == chunk.locator.start:
            grouped[(chunk.doc_id, chunk.locator.start)].append(chunk)
    representatives: dict[tuple[str, int], SearchHit] = {}
    for key, values in grouped.items():
        chunk = min(values, key=lambda item: (-len(item.text), item.chunk_id))
        representatives[key] = SearchHit(
            index_run_id="placeholder",
            chunk_id=chunk.chunk_id,
            doc_id=chunk.doc_id,
            parent_chunk_id=chunk.parent_chunk_id,
            policy_id=chunk.policy_id,
            source_path=chunk.source_path,
            section_path=chunk.section_path,
            locator=chunk.locator,
            matched_text=chunk.text,
            context_text=chunk.text,
            tenant_id=chunk.tenant_id,
            region=chunk.region,
            acl_groups=chunk.acl_groups,
            version_id=chunk.version_id,
            version=chunk.version,
            status=chunk.status,
            authority_level=chunk.authority_level,
            variant=chunk.variant,
            fact_ids=chunk.fact_ids,
            fused_score=0.0,
        )
    return representatives


def rerank_page_hits(
    hits: Sequence[SearchHit],
    *,
    query: str,
    strategy: R3PageStrategy,
    page_representatives: Mapping[tuple[str, int], SearchHit],
    limit: int = 5,
) -> list[SearchHit]:
    rows = list(hits)
    if strategy == "dense_chunk":
        return rows[:limit]
    by_page: dict[tuple[str, int], list[SearchHit]] = defaultdict(list)
    for hit in rows:
        key = page_key(hit)
        if key is not None:
            by_page[key].append(hit)
    scored: dict[tuple[str, int], tuple[float, SearchHit]] = {}
    for key, page_hits in by_page.items():
        best = max(page_hits, key=lambda item: (item.fused_score, item.chunk_id))
        score = best.fused_score
        if strategy == "dense_page_structure":
            scale = max(abs(score), 1e-6)
            score += scale * 0.05 * min(2, len(page_hits) - 1)
            text = "\n".join(item.matched_text for item in page_hits)
            if _is_arithmetic_question(query) and len(_NUMBER.findall(text)) >= 8:
                score += scale * 0.03
        scored[key] = (score, best)
    if strategy == "dense_page_neighbor":
        contributions = list(scored.items())
        for (doc_id, page), (score, source_hit) in contributions:
            for neighbor_page in (page - 1, page + 1):
                key = (doc_id, neighbor_page)
                representative = page_representatives.get(key)
                if representative is None:
                    continue
                if not _same_security_boundary(source_hit, representative):
                    continue
                neighbor_score = score * 0.7
                current = scored.get(key)
                if current is None or neighbor_score > current[0]:
                    scored[key] = (
                        neighbor_score,
                        representative.model_copy(
                            update={
                                "index_run_id": source_hit.index_run_id,
                                "fused_score": neighbor_score,
                            }
                        ),
                    )
    ordered = sorted(
        scored.items(),
        key=lambda item: (-item[1][0], item[0][0], item[0][1], item[1][1].chunk_id),
    )
    return [
        hit.model_copy(update={"fused_score": score})
        for _, (score, hit) in ordered[:limit]
    ]


class R3PageStrategyPipeline:
    def __init__(self, base_pipeline, *, strategy: R3PageStrategy, snapshot) -> None:
        self.base_pipeline = base_pipeline
        self.strategy = strategy
        self.page_representatives = build_page_representatives(snapshot.chunks)

    def search(self, request: SearchRequest) -> SearchResult:
        if self.strategy == "dense_chunk":
            return self.base_pipeline.search(request)
        source_request = request.model_copy(
            update={
                "top_k": 20,
                "candidate_k": max(40, request.candidate_k),
                "max_chunks_per_doc": 10,
                "mode": "dense",
                "include_parent": False,
            }
        )
        source = self.base_pipeline.search(source_request)
        hits = rerank_page_hits(
            source.hits,
            query=request.query,
            strategy=self.strategy,
            page_representatives=self.page_representatives,
            limit=request.top_k,
        )
        stop_reason = source.stop_reason
        if stop_reason == "ok" and not hits:
            stop_reason = "no_match"
        return SearchResult(
            request_id=source.request_id,
            query=source.query,
            mode=source.mode,
            index_run_id=source.index_run_id,
            manifest_sha256=source.manifest_sha256,
            hits=hits,
            visible_candidate_count=source.visible_candidate_count,
            internal_denied_count=source.internal_denied_count,
            stage_counts={**source.stage_counts, "page_strategy_returned": len(hits)},
            stop_reason=stop_reason,
        )


def publish_r3_page_campaign(
    *,
    root: Path,
    manifest_fields: dict,
    details_by_strategy: Mapping[R3PageStrategy, Sequence[UdaFinancePageCaseResult]],
    summaries: Mapping[R3PageStrategy, UdaFinancePageSummary],
) -> Path:
    run_dir = Path(root).resolve() / manifest_fields["run_id"]
    run_dir.mkdir(parents=True, exist_ok=False)
    strategy_runs: list[R3StrategyRun] = []
    for strategy in details_by_strategy:
        detail_bytes = b"".join(
            canonical_json_bytes(item.model_dump(mode="json"))
            for item in details_by_strategy[strategy]
        )
        (run_dir / f"{strategy}.jsonl").write_bytes(detail_bytes)
        strategy_runs.append(
            R3StrategyRun(
                strategy=strategy,
                summary=summaries[strategy],
                details_sha256=hashlib.sha256(detail_bytes).hexdigest(),
            )
        )
    manifest = R3PageCampaignManifest(
        **manifest_fields,
        strategies=strategy_runs,
    )
    (run_dir / "manifest.json").write_bytes(
        canonical_json_bytes(manifest.model_dump(mode="json"))
    )
    return run_dir


def verify_r3_page_campaign(path: Path) -> R3PageCampaignManifest:
    run_dir = Path(path).resolve()
    manifest = R3PageCampaignManifest.model_validate_json(
        (run_dir / "manifest.json").read_bytes()
    )
    for strategy in manifest.strategies:
        path = run_dir / f"{strategy.strategy}.jsonl"
        if hashlib.sha256(path.read_bytes()).hexdigest() != strategy.details_sha256:
            raise ValueError(f"R3 page campaign {strategy.strategy} details hash mismatch")
    return manifest


def load_page_protocol(path: Path = R3_PAGE_PROTOCOL_PATH) -> tuple[dict, str]:
    content = Path(path).resolve().read_bytes()
    payload = json.loads(content.decode("utf-8"))
    if payload.get("schema_version") != "uda_finance_r3_page_protocol_v1":
        raise ValueError("R3 page protocol schema is invalid")
    return payload, hashlib.sha256(content).hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _is_arithmetic_question(question: str) -> bool:
    normalized = question.casefold()
    return any(cue in normalized for cue in _ARITHMETIC_CUES)


def _same_security_boundary(left: SearchHit, right: SearchHit) -> bool:
    return (
        left.doc_id == right.doc_id
        and left.policy_id == right.policy_id
        and left.tenant_id == right.tenant_id
        and left.region == right.region
        and left.acl_groups == right.acl_groups
        and left.version_id == right.version_id
        and left.status == right.status
    )


__all__ = [
    "R3_PAGE_PROTOCOL_PATH",
    "R3PageCampaignManifest",
    "R3PageStrategyPipeline",
    "build_page_representatives",
    "load_page_protocol",
    "publish_r3_page_campaign",
    "rerank_page_hits",
    "verify_r3_page_campaign",
]
