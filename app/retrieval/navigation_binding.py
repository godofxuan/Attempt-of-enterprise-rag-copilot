"""Check navigation output against the registry's original in-memory snapshot.

This is an internal runtime contract, not a serialized provenance signature.
The runner separately verifies active-index identity before publication.
"""

from app.domain.documents import DocumentRecord
from app.domain.queries import FindResult, OpenResult
from app.retrieval.navigation import _preview, _text_matches


def validate_navigation_binding(navigator, snapshot, action, result) -> None:
    if navigator.snapshot is not snapshot:
        raise ValueError("navigation snapshot changed")
    request = action.open_request if action.tool == "open" else action.find_request
    if result.request_id != request.request_id:
        raise ValueError("navigation request identity mismatch")
    policy = navigator.access_policy
    if isinstance(result, OpenResult):
        if (result.target_type, result.target_id) != (request.target_type, request.target_id):
            raise ValueError("navigation target mismatch")
        if request.target_type == "document":
            resource = snapshot.documents_by_id.get(request.target_id)
        elif request.target_type == "parent":
            resource = snapshot.parents_by_id.get(request.target_id)
        else:
            index = snapshot.chunk_index_by_id.get(request.target_id)
            resource = snapshot.chunks[index] if index is not None else None
        if resource is None or not policy.evaluate(request.user, resource).allowed:
            raise ValueError("navigation target unavailable")
        sections = [] if isinstance(resource, DocumentRecord) else resource.section_path
        if (
            result.doc_id != resource.doc_id
            or result.source_path != resource.source_path
            or result.section_path != sections
            or result.content != resource.text[: request.max_chars]
            or result.truncated != (len(resource.text) > request.max_chars)
        ):
            raise ValueError("navigation content does not match bound snapshot")
    elif isinstance(result, FindResult):
        document = snapshot.documents_by_id.get(request.doc_id)
        if document is None or not policy.evaluate(request.user, document).allowed:
            raise ValueError("navigation document unavailable")
        if result.doc_id != request.doc_id or len(result.matches) > request.max_results:
            raise ValueError("navigation document or limit mismatch")
        if len({match.chunk_id for match in result.matches}) != len(result.matches):
            raise ValueError("navigation matches must be unique")
        if (result.stop_reason == "ok") != bool(result.matches):
            raise ValueError("navigation outcome mismatch")
        for match in result.matches:
            chunk = snapshot.all_chunks_by_id.get(match.chunk_id)
            if (
                chunk is None
                or chunk.doc_id != request.doc_id
                or match.doc_id != request.doc_id
                or not policy.evaluate(request.user, chunk).allowed
                or match.section_path != chunk.section_path
                or not _text_matches(request.pattern, chunk.text)
                or match.preview != _preview(chunk.text, request.pattern)
            ):
                raise ValueError("navigation preview does not match bound snapshot")
    else:
        raise TypeError("navigation binding requires a navigation result")
