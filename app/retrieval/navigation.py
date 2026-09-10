from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

from app.domain.agent import ToolError, ToolErrorCode
from app.domain.documents import ChunkRecord, DocumentRecord
from app.domain.queries import (
    FindMatch,
    FindRequest,
    FindResult,
    OpenRequest,
    OpenResult,
    SearchRequest,
    SearchResult,
)
from app.retrieval.pipeline import HybridRetrievalPipeline, RankedSearchPool, _matches_filters
from app.retrieval.snapshot import V2IndexSnapshot
from app.security.access import AccessPolicy
from app.utils import tokenize_for_bm25


class SearchPipeline(Protocol):
    def search(self, request: SearchRequest) -> SearchResult: ...

    def ranked_candidates_for_guard(
        self,
        request: SearchRequest,
    ) -> RankedSearchPool: ...


Clock = Callable[[], float]
SearchOutcome = SearchResult | ToolError
RankedSearchOutcome = RankedSearchPool | ToolError
FindOutcome = FindResult | ToolError
OpenOutcome = OpenResult | ToolError

_RESOURCE_UNAVAILABLE = "The requested resource is unavailable."


class DocumentNavigator:
    def __init__(
        self,
        snapshot: V2IndexSnapshot,
        *,
        pipeline: SearchPipeline | None = None,
        access_policy: AccessPolicy | None = None,
        clock: Clock = time.monotonic,
    ) -> None:
        self.snapshot = snapshot
        self.access_policy = access_policy or AccessPolicy()
        self.pipeline = pipeline or HybridRetrievalPipeline(
            snapshot,
            access_policy=self.access_policy,
        )
        self.clock = clock

    def search(self, request: SearchRequest) -> SearchOutcome:
        started = self.clock()
        if self._expired(started, request.timeout_ms):
            return _tool_error("timeout")
        try:
            result = self.pipeline.search(request)
        except ValueError:
            return _tool_error("invalid_args")
        except Exception:
            return _tool_error("system")
        if self._expired(started, request.timeout_ms):
            return _tool_error("timeout")
        if result.stop_reason == "timeout":
            return _tool_error("timeout")
        return result

    def search_ranked(self, request: SearchRequest) -> RankedSearchOutcome:
        started = self.clock()
        if self._expired(started, request.timeout_ms):
            return _tool_error("timeout")
        try:
            result = self.pipeline.ranked_candidates_for_guard(request)
        except ValueError:
            return _tool_error("invalid_args")
        except Exception:
            return _tool_error("system")
        if self._expired(started, request.timeout_ms):
            return _tool_error("timeout")
        if result.stop_reason == "timeout":
            return _tool_error("timeout")
        return result

    def find(self, request: FindRequest) -> FindOutcome:
        started = self.clock()
        if self._expired(started, request.timeout_ms):
            return _tool_error("timeout")

        document = self.snapshot.documents_by_id.get(request.doc_id)
        if document is None:
            return _tool_error("not_found")
        if not self.access_policy.evaluate(request.user, document).allowed:
            return _tool_error("permission")
        if request.anchor_chunk_id and not self.bound_resource_allowed(request, document):
            return _tool_error("not_found")

        candidates = sorted(
            (
                chunk
                for chunk in self.snapshot.all_chunks_by_id.values()
                if chunk.doc_id == request.doc_id
            ),
            key=_chunk_order,
        )
        matches: list[FindMatch] = []
        for chunk in candidates:
            if self._expired(started, request.timeout_ms):
                return _tool_error("timeout")
            if not self.access_policy.evaluate(request.user, chunk).allowed:
                continue
            if request.anchor_chunk_id and (
                not chunk.indexable or not self.bound_resource_allowed(request, chunk)
            ):
                continue
            if not _text_matches(request.pattern, chunk.text):
                continue
            matches.append(
                FindMatch(
                    doc_id=chunk.doc_id,
                    chunk_id=chunk.chunk_id,
                    section_path=chunk.section_path,
                    preview=_preview(chunk.text, request.pattern),
                )
            )
            if len(matches) == request.max_results:
                break

        if self._expired(started, request.timeout_ms):
            return _tool_error("timeout")
        return FindResult(
            request_id=request.request_id,
            doc_id=request.doc_id,
            matches=matches,
            stop_reason="ok" if matches else "not_found",
        )

    def open(self, request: OpenRequest) -> OpenOutcome:
        started = self.clock()
        if self._expired(started, request.timeout_ms):
            return _tool_error("timeout")

        resource = self._resolve_target(request)
        if resource is None:
            return _tool_error("not_found")
        if not self.access_policy.evaluate(request.user, resource).allowed:
            return _tool_error("permission")
        if request.anchor_chunk_id and not self.bound_resource_allowed(request, resource):
            return _tool_error("not_found")

        if isinstance(resource, DocumentRecord):
            doc_id = resource.doc_id
            content = resource.text
            source_path = resource.source_path
            section_path: list[str] = []
        else:
            doc_id = resource.doc_id
            content = resource.text
            source_path = resource.source_path
            section_path = resource.section_path

        if self._expired(started, request.timeout_ms):
            return _tool_error("timeout")
        truncated = len(content) > request.max_chars
        return OpenResult(
            request_id=request.request_id,
            target_type=request.target_type,
            target_id=request.target_id,
            doc_id=doc_id,
            content=content[: request.max_chars],
            truncated=truncated,
            source_path=source_path,
            section_path=section_path,
        )

    def bound_resource_allowed(self, request, resource) -> bool:
        """Navigation cannot expand beyond the admitted anchor's retrieval scope."""
        anchor = self.snapshot.all_chunks_by_id.get(request.anchor_chunk_id)
        if anchor is None or request.filters is None:
            return False
        if not self.access_policy.evaluate(request.user, anchor).allowed:
            return False
        if not _matches_filters(anchor, request.filters):
            return False
        document = self.snapshot.documents_by_id.get(anchor.doc_id)
        if document is None or not self.access_policy.evaluate(request.user, document).allowed:
            return False
        if (document.document_version.version_id, document.tenant_id, document.policy_id) != (
            anchor.version_id, anchor.tenant_id, anchor.policy_id
        ):
            return False
        if resource.doc_id != anchor.doc_id or not self.access_policy.evaluate(request.user, resource).allowed:
            return False
        if isinstance(resource, DocumentRecord):
            return resource.doc_id == document.doc_id
        return (
            (resource.version_id, resource.tenant_id, resource.region, resource.policy_id) ==
            (anchor.version_id, anchor.tenant_id, anchor.region, anchor.policy_id)
            and _matches_filters(resource, request.filters)
        )

    def _resolve_target(
        self,
        request: OpenRequest,
    ) -> DocumentRecord | ChunkRecord | None:
        if request.target_type == "document":
            return self.snapshot.documents_by_id.get(request.target_id)
        if request.target_type == "parent":
            return self.snapshot.parents_by_id.get(request.target_id)
        index = self.snapshot.chunk_index_by_id.get(request.target_id)
        if index is None:
            return None
        return self.snapshot.chunks[index]

    def _expired(self, started: float, timeout_ms: int) -> bool:
        return (self.clock() - started) * 1000 > timeout_ms


def _chunk_order(chunk: ChunkRecord) -> tuple[int, int, str]:
    return (
        chunk.locator.start,
        chunk.locator.end if chunk.locator.end is not None else chunk.locator.start,
        chunk.chunk_id,
    )


def _text_matches(pattern: str, text: str) -> bool:
    normalized_pattern = pattern.casefold()
    normalized_text = text.casefold()
    if normalized_pattern in normalized_text:
        return True
    pattern_tokens = {
        token.casefold() for token in tokenize_for_bm25(pattern) if token.strip()
    }
    text_tokens = {
        token.casefold() for token in tokenize_for_bm25(text) if token.strip()
    }
    return bool(pattern_tokens) and pattern_tokens.issubset(text_tokens)


def _preview(text: str, pattern: str, max_chars: int = 240) -> str:
    position = text.casefold().find(pattern.casefold())
    if position < 0:
        position = 0
    start = max(0, position - max_chars // 3)
    end = min(len(text), start + max_chars)
    start = max(0, end - max_chars)
    return text[start:end]


def _tool_error(code: ToolErrorCode) -> ToolError:
    messages = {
        "invalid_args": (False, "The tool request could not be processed."),
        "not_found": (False, _RESOURCE_UNAVAILABLE),
        "permission": (False, _RESOURCE_UNAVAILABLE),
        "timeout": (True, "The tool call exceeded its deadline."),
        "system": (True, "The tool is temporarily unavailable."),
        "budget": (False, "The tool budget has been exhausted."),
    }
    retryable, message = messages[code]
    return ToolError(code=code, retryable=retryable, safe_message=message)


__all__ = [
    "DocumentNavigator",
    "FindOutcome",
    "OpenOutcome",
    "RankedSearchOutcome",
    "SearchOutcome",
    "SearchPipeline",
]
