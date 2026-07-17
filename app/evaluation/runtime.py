from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.agent.generation_v2 import GenerationV2ResponseBuilder
from app.agent.runner_v2 import V2AgentRunner, budget_from_settings
from app.agent.tools_v2 import V2ToolRegistry
from app.config import Settings, get_settings
from app.domain.agent import AgentBudget
from app.indexing.store import build_index_version
from app.ingestion.chunking import ChunkerConfig
from app.ollama_chat import chat_with_ollama
from app.retrieval.navigation import DocumentNavigator
from app.retrieval.pipeline import HybridRetrievalPipeline
from app.retrieval.snapshot import V2IndexSnapshot
from app.retriever import _embed_text
from app.utils import tokenize_for_bm25


class EvaluationRuntimeError(RuntimeError):
    pass


@dataclass
class RuntimeCallCounters:
    embedding_calls: int = 0
    generation_calls: int = 0

    @property
    def model_calls(self) -> int:
        return self.embedding_calls + self.generation_calls


@dataclass(frozen=True)
class EvaluationRuntime:
    mode: str
    variant: str
    index_root: Path
    snapshot: V2IndexSnapshot
    pipeline: HybridRetrievalPipeline
    navigator: DocumentNavigator
    runner: V2AgentRunner
    budget: AgentBudget
    counters: RuntimeCallCounters
    embedding_model: str
    chat_model: str | None
    llm_endpoint: str | None = None

    def metadata(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "variant": self.variant,
            "index_root": str(self.index_root),
            "index_run_id": self.snapshot.version.manifest.run_id,
            "embedding_model": self.embedding_model,
            "chat_model": self.chat_model,
            "llm_endpoint": self.llm_endpoint,
            "embedding_calls": self.counters.embedding_calls,
            "generation_calls": self.counters.generation_calls,
            "model_calls": self.counters.model_calls,
            "budget": self.budget.model_dump(mode="json"),
        }


def build_deterministic_runtime(
    corpus_dir: Path,
    temp_root: Path,
    *,
    budget: AgentBudget | None = None,
) -> EvaluationRuntime:
    corpus_dir = Path(corpus_dir).resolve()
    temp_root = Path(temp_root).resolve()
    index_root = temp_root / "indexes-v2"
    active_budget = budget or budget_from_settings()
    build_index_version(
        root=index_root,
        input_dir=corpus_dir,
        run_id="deterministic-eval",
        chunker_config=ChunkerConfig(mode="fixed", chunk_size=500, overlap=80),
        embedding_model="deterministic-hash-128",
        embed_text=deterministic_embedding,
        activate=True,
    )
    snapshot = V2IndexSnapshot.load(index_root)
    pipeline = HybridRetrievalPipeline(
        snapshot,
        embed_text=deterministic_embedding,
    )
    navigator = DocumentNavigator(snapshot, pipeline=pipeline)
    counters = RuntimeCallCounters()
    runner = V2AgentRunner(
        registry=V2ToolRegistry(navigator),
        budget=active_budget,
    )
    return EvaluationRuntime(
        mode="deterministic",
        variant="fixed-500-80-hash-128-extractive",
        index_root=index_root,
        snapshot=snapshot,
        pipeline=pipeline,
        navigator=navigator,
        runner=runner,
        budget=active_budget,
        counters=counters,
        embedding_model="deterministic-hash-128",
        chat_model=None,
    )


def build_live_runtime(
    settings: Settings | None = None,
    *,
    budget: AgentBudget | None = None,
) -> EvaluationRuntime:
    active_settings = settings or get_settings()
    index_root = Path(active_settings.v2_indexes_dir).resolve()
    if not (index_root / "active.json").is_file():
        raise EvaluationRuntimeError(
            f"live evaluation requires an active v2 index: {index_root}"
        )
    try:
        snapshot = V2IndexSnapshot.load(index_root)
    except Exception as exc:
        raise EvaluationRuntimeError(
            f"failed to load active v2 index: {index_root}"
        ) from exc

    counters = RuntimeCallCounters()

    def tracked_embedding(text: str) -> list[float]:
        counters.embedding_calls += 1
        return _embed_text(active_settings.embedding_model, text)

    def tracked_chat(
        model: str,
        messages: list[dict],
        *,
        response_format: str | dict | None = None,
        think: bool | str | None = None,
    ) -> str:
        counters.generation_calls += 1
        return chat_with_ollama(
            model,
            messages,
            response_format=response_format,
            think=think,
        )

    pipeline = HybridRetrievalPipeline(snapshot, embed_text=tracked_embedding)
    navigator = DocumentNavigator(snapshot, pipeline=pipeline)
    active_budget = budget or budget_from_settings(active_settings)
    runner = V2AgentRunner(
        registry=V2ToolRegistry(navigator),
        response_builder=GenerationV2ResponseBuilder(
            chat_fn=tracked_chat,
            model=active_settings.chat_model,
        ),
        budget=active_budget,
    )
    return EvaluationRuntime(
        mode="live",
        variant="active-v2-index-configured-models",
        index_root=index_root,
        snapshot=snapshot,
        pipeline=pipeline,
        navigator=navigator,
        runner=runner,
        budget=active_budget,
        counters=counters,
        embedding_model=active_settings.embedding_model,
        chat_model=active_settings.chat_model,
        llm_endpoint=_safe_endpoint(active_settings.llm_base_url),
    )


def deterministic_embedding(text: str, dimension: int = 128) -> list[float]:
    vector = [0.0] * dimension
    for token in tokenize_for_bm25(text):
        normalized = token.casefold().strip()
        if not normalized:
            continue
        digest = hashlib.sha256(normalized.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    if not any(vector):
        vector[0] = 1.0
    return vector


def _safe_endpoint(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"{parsed.scheme}://{host}{port}"


__all__ = [
    "EvaluationRuntime",
    "EvaluationRuntimeError",
    "RuntimeCallCounters",
    "build_deterministic_runtime",
    "build_live_runtime",
    "deterministic_embedding",
]
