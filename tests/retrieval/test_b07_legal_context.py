from datetime import date

from app.agent.evidence_ledger import _numeric_conflicts
from app.domain.documents import DocumentVersion
from app.ingestion.chunking import ChunkerConfig, chunk_document
from app.retrieval.pipeline import HybridRetrievalPipeline
from tests.retrieval.test_pipeline_ranking import search_request
from tests.v2_test_support import admit_search_hit


def test_scope_in_legally_chunked_parent(document_factory, snapshot_factory):
    documents, chunks = [], []
    for i, (scope, number) in enumerate([("报销退款", 7), ("采购退款", 30)]):
        prefix = f"本规定仅适用于{scope}。"
        document = document_factory(
            doc_id=str(i), policy_id=str(i), text=prefix + f"处理期限为{number}天。"
        )
        documents.append(document)
        chunks.extend(
            chunk_document(
                document,
                ChunkerConfig(
                    mode="parent_child", child_size=len(prefix), parent_size=500, overlap=0
                ),
            )
        )
    children = [c for c in chunks if c.indexable]
    parents = [c for c in chunks if not c.indexable]
    pipeline = HybridRetrievalPipeline(
        snapshot_factory(children, parents=parents, documents=documents)
    )
    result = pipeline.search(
        search_request(query="处理期限", include_parent=True, max_chunks_per_doc=5)
    )
    values = [admit_search_hit(h) for h in result.hits if h.matched_text.startswith("处理期限")]
    assert len(values) == 2 and all(v.hit.context_from_parent for v in values)
    assert not _numeric_conflicts({"deadline": values})
    assert _numeric_conflicts({"deadline": values}, scope_ambiguity=True)


def test_future_parent_children_share_dates_and_current_excludes_them(
    document_factory, snapshot_factory
):
    document = document_factory(
        text="Future policy needle. More text.",
        document_version=DocumentVersion(
            version_id="future@2099",
            version="2099",
            status="active",
            effective_from=date(2099, 1, 1),
            authority_level=100,
        ),
    )
    chunks = chunk_document(
        document, ChunkerConfig(mode="parent_child", child_size=12, parent_size=500, overlap=0)
    )
    assert all(c.effective_from == document.document_version.effective_from for c in chunks)
    assert all(c.effective_to == document.document_version.effective_to for c in chunks)
    assert all(c.doc_id == document.doc_id and c.acl_groups == document.acl_groups for c in chunks)
    pipeline = HybridRetrievalPipeline(
        snapshot_factory(
            [c for c in chunks if c.indexable],
            parents=[c for c in chunks if not c.indexable],
            documents=[document],
        )
    )
    assert not pipeline.search(search_request(query="needle", include_parent=True)).hits
