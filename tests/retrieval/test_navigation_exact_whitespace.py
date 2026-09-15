import pytest
from pydantic import ValidationError

from app.domain.agent import AgentAction
from app.domain.queries import FindMatch, FindRequest, OpenRequest, OpenResult
from app.retrieval.navigation import DocumentNavigator
from app.retrieval.navigation_binding import validate_navigation_binding
from tests.retrieval import conftest as fixtures
from tests.v2_test_support import user_context

chunk_factory = fixtures.chunk_factory
document_factory = fixtures.document_factory
snapshot_factory = fixtures.snapshot_factory


@pytest.mark.parametrize("raw", [" \t原文片段。\n", "原文中的尾随空格 "])
def test_navigation_text_fields_preserve_original_bytes(raw):
    found = FindMatch(doc_id="doc", chunk_id="chunk", section_path=["section"], preview=raw)
    opened = OpenResult(
        request_id="r",
        doc_id="doc",
        target_type="chunk",
        target_id="chunk",
        source_path="file.md",
        section_path=["section"],
        content=raw,
        truncated=True,
    )
    assert found.preview == raw
    assert opened.content == raw


@pytest.mark.parametrize(
    "model,kwargs",
    [
        (FindMatch, dict(doc_id="d", chunk_id="c", section_path=["s"], preview=" \n")),
        (
            OpenResult,
            dict(
                doc_id="d",
                target_type="chunk",
                target_id="c",
                source_path="f.md",
                section_path=["s"],
                content=" \n",
                truncated=False,
            ),
        ),
    ],
)
def test_whitespace_only_navigation_remains_invalid(model, kwargs):
    with pytest.raises(ValidationError):
        model(**kwargs)


@pytest.mark.parametrize("tool", ["find", "open"])
def test_window_ending_in_space_passes_unchanged_binding(
    tool, snapshot_factory, document_factory, chunk_factory
):
    text = "甲" * 239 + " " + "后续条款必须保留。"
    chunk = chunk_factory(chunk_id="chunk-a", text=text)
    snapshot = snapshot_factory([chunk], documents=[document_factory(text=text)])
    nav = DocumentNavigator(snapshot)
    if tool == "find":
        request = FindRequest(user=user_context(), doc_id=chunk.doc_id, pattern="甲")
        result = nav.find(request)
        action = AgentAction(sequence=1, tool="find", purpose="exact window", find_request=request)
        assert result.matches[0].preview == text[:240]
    else:
        request = OpenRequest(
            user=user_context(), target_type="chunk", target_id=chunk.chunk_id, max_chars=240
        )
        result = nav.open(request)
        action = AgentAction(sequence=1, tool="open", purpose="exact window", open_request=request)
        assert result.content == text[:240]
    validate_navigation_binding(nav, snapshot, action, result)
