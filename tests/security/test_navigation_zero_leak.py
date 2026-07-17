from __future__ import annotations

from app.domain.agent import ToolError
from app.domain.queries import FindRequest, FindResult, OpenRequest, UserContext
from app.retrieval.navigation import DocumentNavigator


USER = UserContext(
    user_id="employee-one",
    tenant_id="tenant-one",
    region="cn",
    groups=["employees"],
)


def _secure_snapshot(chunk_factory, document_factory, snapshot_factory):
    visible_document = document_factory(
        doc_id="public-doc",
        title="Public Policy",
        source_path="documents/public.md",
        text="Public policy document.",
    )
    denied_document = document_factory(
        doc_id="secret-board-doc",
        title="Board Acquisition Secret",
        source_path="vault/board-acquisition-secret.md",
        policy_id="board-secret",
        acl_groups=["board_only"],
        text="Project NIGHTFALL acquisition price is 900 million.",
    )
    visible_chunk = chunk_factory(
        chunk_id="public-chunk",
        doc_id="public-doc",
        source_path="documents/public.md",
        text="Public approval guidance.",
    )
    inconsistent_denied_chunk = chunk_factory(
        chunk_id="secret-child-id",
        doc_id="public-doc",
        source_path="vault/secret-child.md",
        acl_groups=["board_only"],
        text="NIGHTFALL password=never-show-this",
    )
    denied_chunk = chunk_factory(
        chunk_id="secret-board-chunk",
        doc_id="secret-board-doc",
        source_path="vault/board-acquisition-secret.md",
        policy_id="board-secret",
        acl_groups=["board_only"],
        text="Project NIGHTFALL acquisition price is 900 million.",
    )
    return snapshot_factory(
        [visible_chunk, inconsistent_denied_chunk, denied_chunk],
        documents=[visible_document, denied_document],
    )


def test_denied_and_missing_targets_share_public_message_without_metadata(
    chunk_factory,
    document_factory,
    snapshot_factory,
) -> None:
    snapshot = _secure_snapshot(
        chunk_factory,
        document_factory,
        snapshot_factory,
    )
    navigator = DocumentNavigator(snapshot)

    denied = navigator.open(
        OpenRequest(
            user=USER,
            target_type="document",
            target_id="secret-board-doc",
        )
    )
    missing = navigator.open(
        OpenRequest(
            user=USER,
            target_type="document",
            target_id="unknown-doc",
        )
    )

    assert isinstance(denied, ToolError)
    assert isinstance(missing, ToolError)
    assert denied.code == "permission"
    assert missing.code == "not_found"
    assert denied.safe_message == missing.safe_message
    serialized = denied.model_dump_json()
    for forbidden in [
        "secret-board-doc",
        "Board Acquisition Secret",
        "board-acquisition-secret.md",
        "NIGHTFALL",
        "900 million",
    ]:
        assert forbidden not in serialized


def test_find_never_matches_a_denied_chunk_inside_visible_document(
    chunk_factory,
    document_factory,
    snapshot_factory,
) -> None:
    snapshot = _secure_snapshot(
        chunk_factory,
        document_factory,
        snapshot_factory,
    )
    result = DocumentNavigator(snapshot).find(
        FindRequest(
            user=USER,
            doc_id="public-doc",
            pattern="NIGHTFALL",
        )
    )

    assert isinstance(result, FindResult)
    assert result.stop_reason == "not_found"
    assert result.matches == []
    assert "secret-child-id" not in result.model_dump_json()
    assert "never-show-this" not in result.model_dump_json()


def test_open_rechecks_chunk_acl_instead_of_trusting_visible_document(
    chunk_factory,
    document_factory,
    snapshot_factory,
) -> None:
    snapshot = _secure_snapshot(
        chunk_factory,
        document_factory,
        snapshot_factory,
    )
    result = DocumentNavigator(snapshot).open(
        OpenRequest(
            user=USER,
            target_type="chunk",
            target_id="secret-child-id",
        )
    )

    assert isinstance(result, ToolError)
    assert result.code == "permission"
    serialized = result.model_dump_json()
    assert "secret-child-id" not in serialized
    assert "never-show-this" not in serialized
